"""Les modules Go privés (E33) : ``GOPRIVATE``, ``GONOPROXY``, ``GOPROXY``, ``GOAUTH``.

Vérifié le 2026-11-02 avec Go 1.27.3 :

- lus dans l'environnement, sinon dans le fichier de ``go env -w`` (``GOENV`` ; par défaut
  ``%APPDATA%\\go\\env`` sous Windows, ``os.UserConfigDir()/go/env`` ailleurs ; ``GOENV=off`` :
  aucun) : des lignes ``CLÉ=valeur``, que l'environnement remplace ;
- ``GONOPROXY`` vaut ``GOPRIVATE`` s'il n'est pas donné (``none`` : aucun module) ;
- des motifs séparés par des virgules (``*.corp.example.com,github.com/acme/*``), comparés aux
  premiers éléments du chemin d'un module (``module.MatchPrefixPatterns``) ;
- **le proxy public cherche lui-même un module chez son hôte** : demander
  ``github.com/acme/prive`` à proxy.golang.org lui fait lancer ``git ls-remote`` vers GitHub
  (404, « could not read Username »), un hôte d'entreprise une requête https (« no such host ») :
  le chemin du module est connu de lui, et de l'hôte.

Ce qu'on en fait, comme ``go`` :

- un module de ``GONOPROXY`` : ``go`` le prend chez son hôte (git), personne n'est interrogé :
  « privé : non vérifié » ; un module de ``GOPRIVATE`` n'est jamais demandé à OSV ;
- ``GOPROXY`` : les proxys jusqu'au premier ``direct`` ou ``off`` ; proxy.golang.org est le
  public ; un autre est un miroir, demandé avec les identifiants de ``.netrc`` (``GOAUTH=netrc``,
  la valeur par défaut) ou de son adresse ; ``direct`` ou ``off`` en premier : chaque module est
  pris chez son hôte, personne n'est interrogé ;
- un module de ``GOPRIVATE`` hors de ``GONOPROXY`` (``GONOPROXY=none``) : demandé aux proxys de
  la personne, jamais à proxy.golang.org.
"""

import re
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path

from forceupdate import userfiles
from forceupdate.models import Dependency, Project
from forceupdate.net.auth import Credential, basic, bound_or_none, split_userinfo
from forceupdate.parsers.base import ReadText
from forceupdate.routing import PUBLIC, Declared, Reading, Route, Router, User
from forceupdate.routing.netrc import netrc_credentials

PUBLIC_PROXY = "https://proxy.golang.org"
DEFAULT_GOPROXY = "https://proxy.golang.org,direct"
KEYS = ("GOPRIVATE", "GONOPROXY", "GOPROXY", "GOAUTH")


@dataclass(frozen=True, kw_only=True)
class GoEnv:
    """Ce que ``go`` lirait (``go env``) : chaque clé, et d'où elle vient."""

    values: dict[str, str] = field(default_factory=dict)
    origins: dict[str, str] = field(default_factory=dict)

    def get(self, key: str) -> str | None:
        return self.values.get(key)


def goenv_path() -> Path | None:
    """Le fichier de ``go env -w`` ; ``None`` avec ``GOENV=off``."""
    configured = userfiles.env("GOENV")
    if configured == "off":
        return None
    if configured:
        return Path(configured)
    return userfiles.config_home() / "go" / "env"


def parse_goenv(text: str) -> dict[str, str]:
    """Les lignes ``CLÉ=valeur`` du fichier de ``go env -w``."""
    values = {}
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if separator and re.fullmatch(r"[A-Z0-9_]+", key.strip()):
            values[key.strip()] = value.strip()
    return values


def go_env(user: User) -> GoEnv:
    """``GOPRIVATE``, ``GONOPROXY``, ``GOPROXY`` et ``GOAUTH`` de la personne."""

    def load() -> GoEnv:
        path = goenv_path()
        text = userfiles.read(path) if path is not None else None
        written = parse_goenv(text) if text is not None else {}
        values: dict[str, str] = {}
        origins: dict[str, str] = {}
        for key in KEYS:
            if (value := userfiles.environ().get(key)) is not None:
                values[key], origins[key] = value, key
            elif key in written:
                values[key], origins[key] = written[key], f"{key} (go env -w)"
        return GoEnv(values=values, origins=origins)

    return user.memo("go.env", load)


def match_prefix_patterns(globs: str, target: str) -> bool:
    """``module.MatchPrefixPatterns`` de Go : un motif de N+1 éléments est comparé aux N+1
    premiers éléments du chemin ``target`` (``path.Match``)."""
    for glob in globs.split(","):
        glob = glob.strip().removesuffix("/")
        if not glob:
            continue
        slashes = glob.count("/")
        parts = target.split("/")
        if len(parts) <= slashes:
            continue
        if fnmatchcase("/".join(parts[: slashes + 1]), glob):
            return True
    return False


def proxies(value: str) -> tuple[list[str], str | None]:
    """Les proxys de ``GOPROXY`` avant le premier ``direct`` ou ``off``, et celui-ci (``None``
    s'il n'y en a pas)."""
    found = []
    for entry in re.split(r"[,|]", value):
        entry = entry.strip()
        if entry in ("direct", "off"):
            return found, entry
        if entry:
            found.append(entry)
    return found, None


def read(project: Project, read_text: ReadText, user: User) -> Reading | None:
    """L'aiguillage des modules Go : d'après ``go env`` de la personne (rien du projet)."""
    env = go_env(user)
    private = env.get("GOPRIVATE") or ""
    noproxy = env.get("GONOPROXY")
    if noproxy is None:
        noproxy = private
    elif noproxy == "none":
        noproxy = ""
    listed, stop = proxies(env.get("GOPROXY") or DEFAULT_GOPROXY)
    credentials: list[Credential] = []
    mirrors: list[Declared] = []
    public = False
    for entry in listed:
        url, userinfo = split_userinfo(entry)
        if url.rstrip("/") == PUBLIC_PROXY:
            public = True
            break  # le public répond pour tout ; ce qui suit ne sert qu'en cas d'erreur
        source = env.origins.get("GOPROXY", "GOPROXY")
        mirrors.append(Declared(url=url, file=source))
        credential = None
        if userinfo is not None and userinfo[0]:
            credential = bound_or_none(url, value=basic(*userinfo), source=source)
        if credential is not None:
            credentials.append(credential)
    if mirrors and (env.get("GOAUTH") or "netrc").split(";")[0].strip() == "netrc":
        credentials += netrc_credentials(user)
    if not private and not noproxy and not mirrors and public:
        return None
    return Reading(
        router=_router(env, private, noproxy, tuple(mirrors), public, stop),
        credentials=credentials,
    )


def _router(
    env: GoEnv,
    private: str,
    noproxy: str,
    mirrors: tuple[Declared, ...],
    public: bool,
    stop: str | None,
) -> Router:
    def route(dependency: Dependency) -> Route:
        module = dependency.name
        is_private = bool(private) and match_prefix_patterns(private, module)
        if noproxy and match_prefix_patterns(noproxy, module):
            origin = env.origins.get("GONOPROXY") or env.origins.get("GOPRIVATE", "GOPRIVATE")
            return Route(
                public=False,
                private=True,
                unchecked=(
                    f"Privé : non vérifié : module de {origin}, que go prend directement chez son "
                    "hôte ; ni le proxy public ni OSV ne sont interrogés"
                ),
            )
        if is_private:
            if not mirrors:
                return Route(
                    public=False,
                    private=True,
                    unchecked=(
                        "Privé : non vérifié : module de GOPRIVATE, et pas d'autre proxy que "
                        "proxy.golang.org dans GOPROXY, qui ne sera pas interrogé"
                    ),
                )
            return Route(registries=mirrors, public=False, private=True)
        if not mirrors and not public:
            origin = env.origins.get("GOPROXY", "GOPROXY")
            return Route(
                public=False,
                unchecked=(
                    f"Non vérifié : {origin}={stop or 'direct'}, go prend chaque module chez son "
                    "hôte ; forceupdate ne demande pas le proxy public à sa place"
                ),
            )
        if mirrors:
            return Route(registries=mirrors, public=public)
        return PUBLIC

    return route
