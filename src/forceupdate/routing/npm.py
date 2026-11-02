"""Les registres npm (E33) : ``.npmrc`` (npm, pnpm, Yarn 1), ``.yarnrc.yml`` (Yarn 2 et plus).

``.npmrc`` (vérifié le 2026-11-02 avec npm 11.6.2 : ``npm config get``, ``npm config list``) :

- celui du projet (son dossier, puis ses dossiers parents dans la source : la racine d'un
  workspace), puis celui de la personne (``~/.npmrc``, ou ``NPM_CONFIG_USERCONFIG``) ;
  ``npm_config_registry`` de l'environnement passe devant ; pour une même clé, le plus proche
  l'emporte ;
- des lignes ``clé = valeur``, des commentaires ``;`` et ``#``, une valeur entre guillemets ;
  ``${NOM}`` remplacé par la variable d'environnement (ici, seulement dans un fichier de la
  personne) ; une section ``[…]`` n'est pas de la configuration ;
- ``registry`` : le registre de tous les paquets (un miroir) ; ``@portée:registry`` : celui des
  paquets de cette portée, **privés par leur nom** ;
- les identifiants, par adresse sans schéma : ``//hôte[:port]/chemin/:_authToken`` (un jeton),
  ``:_auth`` (``nom:mot de passe`` en base 64), ``:username`` et ``:_password`` (en base 64).

``.yarnrc.yml`` (Yarn 2 et plus ne lit pas ``.npmrc``) : ceux du projet et de ses parents, puis
``~/.yarnrc.yml`` ; ``npmRegistryServer``, ``npmScopes.<portée>.npmRegistryServer``, avec leurs
``npmAuthToken`` ou ``npmAuthIdent`` (``nom:mot de passe``), et ``npmRegistries`` par adresse.
"""

import base64
import binascii
import json
import posixpath
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

from forceupdate import userfiles
from forceupdate.models import Dependency, Notice, Project
from forceupdate.net.auth import Credential, basic, bearer, bound_or_none, split_userinfo
from forceupdate.parsers.base import ReadText
from forceupdate.routing import PUBLIC, Declared, Reading, Route, Router, User

PUBLIC_HOSTS = frozenset({"registry.npmjs.org", "registry.npmjs.com", "registry.yarnpkg.com"})
"""Le registre public (``registry.yarnpkg.com`` en est un autre nom)."""

USER_NPMRC = "~/.npmrc"
USER_YARNRC = "~/.yarnrc.yml"


@dataclass(kw_only=True)
class NpmConfig:
    """La configuration lue : les registres et les identifiants, et ce qu'il faut en dire."""

    registry: Declared | None = None
    scopes: dict[str, Declared] = field(default_factory=dict)
    credentials: list[Credential] = field(default_factory=list)
    notices: list[Notice] = field(default_factory=list)
    personal_file: str = USER_NPMRC
    """Le fichier de la personne, où mettre un identifiant (pour les remarques)."""

    def value(self, raw: str, file: str, key: str, personal: bool) -> str | None:
        """``raw``, ses variables développées pour un fichier de la personne ; ``None`` si elle
        n'est pas utilisable (une variable d'un fichier du projet, ou qui manque), et dit."""
        if personal:
            value = userfiles.expand(raw)
            if value is None:
                message = f"« {key} » utilise une variable d'environnement absente : pas utilisé."
                self.notices.append(Notice(file=file, message=message))
            return value
        if userfiles.unexpanded(raw):
            self.notices.append(
                Notice(file=file, message=unexpanded_message(key, self.personal_file))
            )
            return None
        return raw

    def declared(self, value: str, file: str) -> Declared | None:
        """Le registre d'adresse ``value`` ; les identifiants écrits dans l'adresse
        (``https://nom:secret@hôte/``) deviennent un identifiant lié à elle."""
        url, userinfo = split_userinfo(value.strip())
        if urlsplit(url).scheme.lower() not in ("http", "https"):
            return None
        if userinfo is not None and userinfo[0]:
            self.credential(url, basic(*userinfo), file)
        return Declared(url=url, file=file)

    def credential(self, url: str, value: str, file: str) -> None:
        credential = bound_or_none(url, value=value, source=file, with_scheme=False)
        if credential is not None:
            self.credentials.append(credential)


def unexpanded_message(key: str, personal_file: str) -> str:
    """Ce qu'on dit d'une variable d'environnement dans un fichier du projet."""
    return (
        f"« {key} » utilise une variable d'environnement : forceupdate ne développe jamais celles "
        "d'un fichier du projet (un dépôt pourrait faire partir un secret vers l'adresse de son "
        f"choix). Mettre l'identifiant dans le fichier de la personne ({personal_file})."
    )


def is_public(url: str) -> bool:
    return (urlsplit(url).hostname or "").lower() in PUBLIC_HOSTS


def read(project: Project, read_text: ReadText, user: User) -> Reading | None:
    """L'aiguillage des paquets npm de ``project``."""
    yarn = project_files(project, read_text, ".yarnrc.yml")
    if yarn:
        config = _yarn_config(yarn, user)
    else:
        config = _npm_config(project_files(project, read_text, ".npmrc"), user)
    if not (config.registry or config.scopes or config.credentials or config.notices):
        return None
    return Reading(router=_router(config), credentials=config.credentials, notices=config.notices)


def _router(config: NpmConfig) -> Router:
    def route(dependency: Dependency) -> Route:
        name = dependency.name
        if name.startswith("@") and "/" in name:
            scoped = config.scopes.get(name.partition("/")[0])
            if scoped is not None:
                if is_public(scoped.url):
                    return PUBLIC
                return Route(registries=(scoped,), public=False, private=True)
        if config.registry is not None and not is_public(config.registry.url):
            return Route(registries=(config.registry,), public=False)
        return PUBLIC

    return route


def project_files(project: Project, read_text: ReadText, name: str) -> list[tuple[str, str]]:
    """Les fichiers ``name`` du dossier du projet puis de ses parents dans la source, du plus
    proche au plus lointain : (chemin, texte)."""
    found = []
    directory = project.path or "."
    while True:
        path = name if directory == "." else posixpath.join(directory, name)
        try:
            text = read_text(path)
        except ValueError:
            text = None
        if text is not None:
            found.append((path, text))
        if directory == ".":
            return found
        directory = posixpath.dirname(directory) or "."


# -- .npmrc ---------------------------------------------------------------------------


def parse_npmrc(text: str) -> dict[str, str]:
    """Les clés de premier niveau d'un ``.npmrc``, telles qu'écrites (variables comprises)."""
    values: dict[str, str] = {}
    in_section = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith((";", "#")):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_section = True
            continue
        if in_section or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key.endswith("[]"):
            continue
        if len(value) >= 2 and value[0] == value[-1] == '"':
            try:
                value = json.loads(value)
            except ValueError:
                value = value[1:-1]
        elif len(value) >= 2 and value[0] == value[-1] == "'":
            value = value[1:-1]
        values[key] = value
    return values


def _user_npmrc(user: User) -> dict[str, str] | None:
    def load() -> dict[str, str] | None:
        configured = userfiles.env("NPM_CONFIG_USERCONFIG") or userfiles.env(
            "npm_config_userconfig"
        )
        path = Path(configured) if configured else userfiles.home() / ".npmrc"
        text = userfiles.read(path)
        return None if text is None else parse_npmrc(text)

    return user.memo("npm.npmrc", load)


def _npm_config(project_npmrc: list[tuple[str, str]], user: User) -> NpmConfig:
    """La configuration npm : l'environnement, les ``.npmrc`` du projet (le plus proche d'abord),
    celui de la personne."""
    layers: list[tuple[str, dict[str, str], bool]] = []
    environment = userfiles.env("npm_config_registry") or userfiles.env("NPM_CONFIG_REGISTRY")
    if environment:
        layers.append(("npm_config_registry", {"registry": environment}, True))
    layers += [(path, parse_npmrc(text), False) for path, text in project_npmrc]
    mine = _user_npmrc(user)
    if mine is not None:
        layers.append((USER_NPMRC, mine, True))
    config = NpmConfig()
    seen: set[str] = set()
    auth: dict[str, dict[str, tuple[str, str]]] = {}
    for file, values, personal in layers:
        for key, raw in values.items():
            if key in seen:
                continue
            seen.add(key)
            if key == "registry" or (key.startswith("@") and key.endswith(":registry")):
                value = config.value(raw, file, key, personal)
                declared = config.declared(value, file) if value is not None else None
                if declared is None:
                    continue
                if key == "registry":
                    config.registry = declared
                else:
                    config.scopes[key.removesuffix(":registry")] = declared
            elif key.startswith("//") and ":" in key[2:]:
                value = config.value(raw, file, key, personal)
                if value is not None:
                    where, _, setting = key.rpartition(":")
                    auth.setdefault(where, {})[setting] = (value, file)
    for where, settings in auth.items():
        _npm_credential(config, where, settings)
    return config


def _npm_credential(config: NpmConfig, where: str, settings: dict[str, tuple[str, str]]) -> None:
    """L'identifiant de l'adresse sans schéma ``where`` (``//hôte/chemin/``)."""
    url = f"https:{where if where.endswith('/') else where + '/'}"
    if "_authToken" in settings:
        token, file = settings["_authToken"]
        config.credential(url, bearer(token), file)
    elif "_auth" in settings:
        token, file = settings["_auth"]
        config.credential(url, f"Basic {token}", file)
    elif "username" in settings and "_password" in settings:
        username, file = settings["username"]
        encoded, _ = settings["_password"]
        try:
            password = base64.b64decode(encoded, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            message = f"« {where}:_password » n'est pas en base 64 : pas utilisé."
            config.notices.append(Notice(file=file, message=message))
            return
        config.credential(url, basic(username, password), file)


# -- .yarnrc.yml ----------------------------------------------------------------------


def _load_yaml(text: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _yarn_config(project_yarnrc: list[tuple[str, str]], user: User) -> NpmConfig:
    """La configuration de Yarn 2 et plus : les ``.yarnrc.yml`` du projet (le plus proche
    d'abord), puis celui de la personne."""
    layers = [(path, _load_yaml(text), False) for path, text in project_yarnrc]

    def load() -> dict[str, Any] | None:
        text = userfiles.read(userfiles.home() / ".yarnrc.yml")
        return None if text is None else _load_yaml(text)

    mine = user.memo("npm.yarnrc", load)
    if mine is not None:
        layers.append((USER_YARNRC, mine, True))
    config = NpmConfig(personal_file=USER_YARNRC)
    for file, data, personal in layers:
        server = data.get("npmRegistryServer")
        if config.registry is None and isinstance(server, str):
            value = config.value(server, file, "npmRegistryServer", personal)
            declared = config.declared(value, file) if value is not None else None
            if declared is not None:
                config.registry = declared
                _yarn_auth(config, data, declared.url, file, personal)
        scopes = data.get("npmScopes")
        for scope, settings in scopes.items() if isinstance(scopes, dict) else ():
            name = f"@{scope}"
            if not isinstance(settings, dict) or name in config.scopes:
                continue
            server = settings.get("npmRegistryServer")
            if isinstance(server, str):
                value = config.value(server, file, f"npmScopes.{scope}", personal)
                declared = config.declared(value, file) if value is not None else None
                if declared is not None:
                    config.scopes[name] = declared
                    _yarn_auth(config, settings, declared.url, file, personal)
        registries = data.get("npmRegistries")
        for where, settings in registries.items() if isinstance(registries, dict) else ():
            if isinstance(settings, dict) and isinstance(where, str):
                url = where if "://" in where else f"https:{where}"
                _yarn_auth(config, settings, url, file, personal)
    return config


def _yarn_auth(
    config: NpmConfig, settings: dict[str, Any], url: str, file: str, personal: bool
) -> None:
    token = settings.get("npmAuthToken")
    ident = settings.get("npmAuthIdent")
    if isinstance(token, str):
        value = config.value(token, file, "npmAuthToken", personal)
        if value is not None:
            config.credential(url, bearer(value), file)
    elif isinstance(ident, str):
        value = config.value(ident, file, "npmAuthIdent", personal)
        if value is not None:
            username, _, password = value.partition(":")
            config.credential(url, basic(username, password), file)
