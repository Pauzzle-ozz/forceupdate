"""Les dépôts Composer déclarés (E33) : ``repositories`` de ``composer.json``, et ``auth.json``.

``repositories`` (une liste, ou un objet par nom) :

- un dépôt ``{"type": "composer", "url": …}`` (Satis, Private Packagist, un miroir) est demandé
  avant Packagist, et le premier dépôt qui a un paquet l'emporte : c'est ce que fait Composer 2
  (``canonical``, par défaut ; vérifié avec Composer 2.11.0 : un paquet trouvé dans le dépôt
  déclaré en vient). ``exclude`` retire des paquets d'un dépôt ;
- ``only`` réserve des paquets à un dépôt : ceux-là sont **privés par leur nom**, jamais demandés
  à Packagist ni à OSV ;
- ``{"packagist.org": false}`` (ou ``"packagist": false``) retire Packagist ; un dépôt
  ``composer`` à l'adresse de Packagist, c'est Packagist ;
- les autres types (``vcs``, ``package``, ``path``, ``artifact``) restent ceux du parseur
  (``parsers.php``).

Les identifiants, comme Composer : ``COMPOSER_AUTH`` (du JSON), puis ``auth.json`` à côté de
``composer.json``, puis celui de ``COMPOSER_HOME`` (``%APPDATA%\\Composer`` sous Windows,
``$XDG_CONFIG_HOME/composer`` ou ``~/.composer`` ailleurs) ; ``http-basic`` (un nom et un mot de
passe) et ``bearer`` (un jeton), chacun pour un hôte (``hôte`` ou ``hôte:port``).
"""

import json
import posixpath
import sys
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from forceupdate import userfiles
from forceupdate.models import Dependency, Project
from forceupdate.net.auth import Credential, basic, bearer, bound_or_none, split_userinfo
from forceupdate.parsers.base import ReadText
from forceupdate.routing import PUBLIC, Declared, Reading, Route, Router, User

PACKAGIST_HOSTS = frozenset({"repo.packagist.org", "packagist.org"})
"""Packagist lui-même, déclaré comme un dépôt ``composer``."""


@dataclass(frozen=True, kw_only=True)
class Repository:
    """Un dépôt ``composer`` de ``repositories``."""

    declared: Declared
    only: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()

    def serves(self, name: str) -> bool:
        if self.only and not _matches(self.only, name):
            return False
        return not _matches(self.exclude, name)


def _matches(patterns: tuple[str, ...], name: str) -> bool:
    return any(fnmatchcase(name, pattern.lower()) for pattern in patterns)


def composer_home() -> Path:
    """Le dossier de Composer de la personne (``COMPOSER_HOME``)."""
    configured = userfiles.env("COMPOSER_HOME")
    if configured:
        return Path(configured)
    if sys.platform == "win32":
        return userfiles.config_home() / "Composer"
    candidates = [userfiles.xdg_config_home() / "composer", userfiles.home() / ".composer"]
    return next((path for path in candidates if path.is_dir()), candidates[-1])


def read(project: Project, read_text: ReadText, user: User) -> Reading | None:
    """L'aiguillage des paquets Composer de ``project`` : les dépôts de son ``composer.json``."""
    manifest = posixpath.join(project.path, "composer.json").removeprefix("./")
    data = _json(_read(read_text, manifest))
    if not isinstance(data, dict):
        return None
    credentials: list[Credential] = []
    repositories, packagist = _repositories(data.get("repositories"), manifest, credentials)
    if not repositories and packagist:
        return None
    credentials += _auth(_json(userfiles.env("COMPOSER_AUTH") or ""), "COMPOSER_AUTH")
    auth_file = posixpath.join(project.path, "auth.json").removeprefix("./")
    credentials += _auth(_json(_read(read_text, auth_file)), auth_file)
    credentials += user.memo("composer.auth", _personal_auth)
    return Reading(router=_router(repositories, packagist), credentials=credentials)


def _router(repositories: list[Repository], packagist: bool) -> Router:
    def route(dependency: Dependency) -> Route:
        name = dependency.name.lower()
        reserved = [r.declared for r in repositories if r.only and r.serves(name)]
        if reserved:
            return Route(registries=tuple(reserved), public=False, private=True)
        usable = tuple(r.declared for r in repositories if r.serves(name))
        if not usable and not packagist:
            return Route(
                public=False,
                unchecked=(
                    "Non vérifié : aucun dépôt de « repositories » ne sert ce paquet, et Packagist "
                    "est retiré"
                ),
            )
        if not usable:
            return PUBLIC
        return Route(registries=usable, public=packagist)

    return route


def _repositories(
    value: Any, manifest: str, credentials: list[Credential]
) -> tuple[list[Repository], bool]:
    """Les dépôts ``composer`` de ``repositories``, dans l'ordre, et si Packagist reste. Les
    identifiants écrits dans l'adresse d'un dépôt vont dans ``credentials``, liés à elle."""
    entries: list[tuple[str | None, Any]]
    if isinstance(value, dict):
        entries = list(value.items())
    elif isinstance(value, list):
        entries = [(None, entry) for entry in value]
    else:
        return [], True
    found: list[Repository] = []
    packagist = True
    for key, entry in entries:
        if key in ("packagist.org", "packagist") and entry is False:
            packagist = False
            continue
        if not isinstance(entry, dict):
            continue
        if entry.get("packagist.org") is False or entry.get("packagist") is False:
            packagist = False
            continue
        if entry.get("type") != "composer" or not isinstance(entry.get("url"), str):
            continue
        url, userinfo = split_userinfo(entry["url"].strip().rstrip("/"))
        host = (urlsplit(url).hostname or "").lower()
        if urlsplit(url).scheme.lower() not in ("http", "https") or host in PACKAGIST_HOSTS:
            continue
        if userinfo is not None and userinfo[0] and not userfiles.unexpanded(userinfo[1]):
            credential = bound_or_none(url, value=basic(*userinfo), source=manifest)
            if credential is not None:
                credentials.append(credential)
        found.append(
            Repository(
                declared=Declared(url=url, file=manifest, kind="composer"),
                only=_names(entry.get("only")),
                exclude=_names(entry.get("exclude")),
            )
        )
    return found, packagist


def _names(value: Any) -> tuple[str, ...]:
    return tuple(v for v in value if isinstance(v, str)) if isinstance(value, list) else ()


def _read(read_text: ReadText, path: str) -> str | None:
    try:
        return read_text(path)
    except ValueError:
        return None


def _json(text: str | None) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def _personal_auth() -> list[Credential]:
    path = composer_home() / "auth.json"
    return _auth(_json(userfiles.read(path)), "auth.json (COMPOSER_HOME)")


def _auth(data: Any, source: str) -> list[Credential]:
    """Les identifiants ``http-basic`` et ``bearer`` d'un ``auth.json`` (ou de ``COMPOSER_AUTH``),
    chacun lié à son hôte."""
    if not isinstance(data, dict):
        return []
    found = []
    basics = data.get("http-basic")
    for host, entry in basics.items() if isinstance(basics, dict) else ():
        if isinstance(host, str) and isinstance(entry, dict):
            username, password = entry.get("username"), entry.get("password")
            if isinstance(username, str) and isinstance(password, str):
                found.append((host, basic(username, password)))
    bearers = data.get("bearer")
    for host, token in bearers.items() if isinstance(bearers, dict) else ():
        if isinstance(host, str) and isinstance(token, str):
            found.append((host, bearer(token)))
    credentials = []
    for host, value in found:
        credential = bound_or_none(
            f"https://{host}/", value=value, source=source, with_scheme=False
        )
        if credential is not None:
            credentials.append(credential)
    return credentials
