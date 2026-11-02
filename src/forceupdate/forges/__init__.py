"""Les forges : GitHub, GitLab, Bitbucket Cloud (brief, « Forges » ; PLAN, phase E).

- ``base.py`` : l'interface ``Forge`` et ses types, la seule que connaît le reste de l'outil ;
  ``OAuthFlow``, la connexion d'un compte par la page d'autorisation d'une forge ;
- ``github.py`` : le client REST de GitHub, et la connexion d'un compte (OAuth, device flow,
  token collé, ``gh``) ;
- ``gitlab.py`` : le client REST de GitLab (gitlab.com, ou une instance auto-hébergée), et la
  connexion d'un compte (OAuth avec PKCE sur gitlab.com, token collé) (E19) ;
- ``bitbucket.py`` : le client REST de Bitbucket Cloud, et la connexion d'un compte (OAuth, token
  d'API Atlassian collé) (E20). Bitbucket Data Center (auto-hébergé, une autre API) : hors V1 ;
- ``git.py`` : git, pour cloner un dépôt et y pousser une branche, le token passé par un
  credential helper éphémère (E18) ;
- ``accounts.py`` : les comptes connectés, leurs tokens dans le trousseau du système.

``FORGES`` dit lesquelles existent et lesquelles se connectent déjà ; ``client`` rend la forge
d'un token ; ``parse_repository`` lit un dépôt donné par son nom ou son adresse.
"""

import re
import threading
import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass
from typing import NamedTuple

from forceupdate.forges.base import Forge, ForgeKind, Renew
from forceupdate.forges.bitbucket import Bitbucket
from forceupdate.forges.github import GitHub
from forceupdate.forges.gitlab import GitLab
from forceupdate.net import HttpClient


@dataclass(frozen=True, kw_only=True)
class ForgeInfo:
    kind: ForgeKind
    name: str
    """Le nom à montrer : « GitHub »."""
    host: str
    """L'hôte de son service en ligne."""
    available: bool
    """La connexion est prête ; sinon, elle arrive à une étape à venir."""
    self_hosted: bool = False
    """On peut aussi y connecter une instance auto-hébergée, par son adresse et un token."""
    request: str = "PR"
    """Le nom d'une proposition de changements : « PR », « MR » sur GitLab."""


FORGES = (
    ForgeInfo(kind=ForgeKind.GITHUB, name="GitHub", host="github.com", available=True),
    ForgeInfo(
        kind=ForgeKind.GITLAB,
        name="GitLab",
        host="gitlab.com",
        available=True,
        self_hosted=True,
        request="MR",
    ),
    ForgeInfo(kind=ForgeKind.BITBUCKET, name="Bitbucket", host="bitbucket.org", available=True),
)


HOSTS = {forge.kind: forge.host for forge in FORGES}


def info(kind: ForgeKind) -> ForgeInfo:
    return next(forge for forge in FORGES if forge.kind is kind)


def label(kind: ForgeKind, host: str) -> str:
    """Le nom d'une forge sur un hôte : « GitLab », ou « GitLab (gitlab.example.com) » pour une
    instance."""
    name = info(kind).name
    return name if host == HOSTS[kind] else f"{name} ({host})"


class RepositoryName(NamedTuple):
    """Un dépôt donné par son nom ou son adresse (``parse_repository``)."""

    forge: ForgeInfo
    host: str
    full_name: str


_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
_REPO = re.compile(r"[A-Za-z0-9._-]{1,100}")
_WORKSPACE = re.compile(r"[A-Za-z0-9_-]{1,62}")
"""L'identifiant d'un workspace de Bitbucket (lettres, chiffres, ``-`` et ``_``)."""
_GITLAB_SEGMENT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,254}")
MAX_GITLAB_DEPTH = 21
"""Segments au plus d'un chemin de projet GitLab (20 niveaux de groupes, puis le projet)."""


def parse_repository(
    text: str, *, instances: Mapping[str, ForgeKind] | None = None
) -> RepositoryName:
    """La forge, l'hôte et le nom d'un dépôt donné par la personne : ``owner/nom`` (GitHub),
    ou son adresse (``https://github.com/owner/nom``, ``…/nom.git``, ``git@github.com:owner/
    nom.git``, une page du dépôt ; sur Bitbucket, ``workspace/dépôt``). Sur GitLab, le nom est
    le chemin complet du projet, groupes et sous-groupes compris (``groupe/sous-groupe/
    projet``) ; ``instances`` : les hôtes des instances auto-hébergées connectées. Lève
    ``ValueError`` avec un message à montrer."""
    value = text.strip()
    if value.startswith("git@"):
        host, _, path = value[4:].partition(":")
    elif "://" in value or value.split("/", 1)[0].count(".") >= 1:
        parsed = urllib.parse.urlsplit(value if "://" in value else f"https://{value}")
        if parsed.scheme not in ("https", "http"):
            raise ValueError(f"« {text} » : donner owner/nom, ou l'adresse https du dépôt.")
        host, path = (parsed.netloc.rpartition("@")[2]), parsed.path
    else:
        host, path = HOSTS[ForgeKind.GITHUB], value
    host = host.lower().removeprefix("www.")
    forge = next((f for f in FORGES if f.host == host), None)
    if forge is None and instances and host in instances:
        forge = info(instances[host])
    if forge is None:
        raise ValueError(
            f"« {host} » : seuls GitHub, GitLab et Bitbucket sont connus (et les instances "
            "GitLab connectées)."
        )
    parts = [part for part in path.strip("/").split("/") if part]
    if forge.kind is ForgeKind.GITLAB:
        return RepositoryName(forge, host, _gitlab_path(text, parts))
    if len(parts) < 2:
        raise ValueError(f"« {text} » : donner owner/nom, ou l'adresse du dépôt.")
    owner, name = parts[0], parts[1].removesuffix(".git")
    owner_pattern = _WORKSPACE if forge.kind is ForgeKind.BITBUCKET else _NAME
    if not owner_pattern.fullmatch(owner) or not _REPO.fullmatch(name) or name in (".", ".."):
        raise ValueError(f"« {owner}/{name} » n'est pas un nom de dépôt.")
    return RepositoryName(forge, host, f"{owner}/{name}")


def _gitlab_path(text: str, parts: list[str]) -> str:
    """Le chemin complet d'un projet GitLab : les segments jusqu'à ``-`` (qui sépare, dans une
    adresse de GitLab, le projet de sa page : ``…/projet/-/tree/main``)."""
    if "-" in parts:
        parts = parts[: parts.index("-")]
    if parts:
        parts[-1] = parts[-1].removesuffix(".git")
    if len(parts) < 2:
        raise ValueError(f"« {text} » : donner groupe/projet, ou l'adresse du projet.")
    if len(parts) > MAX_GITLAB_DEPTH or not all(
        _GITLAB_SEGMENT.fullmatch(part) and not part.endswith(".") for part in parts
    ):
        raise ValueError(f"« {'/'.join(parts)} » n'est pas un chemin de projet GitLab.")
    return "/".join(parts)


def client(
    kind: ForgeKind,
    http: HttpClient,
    token: str | None,
    *,
    host: str | None = None,
    renew: Renew | None = None,
    cancel: threading.Event | None = None,
) -> Forge:
    """La forge ``kind`` (sur ``host`` : par défaut son service en ligne), vue avec ``token`` ;
    sans token, ses dépôts publics seulement. ``renew`` renouvelle un token qui expire ;
    ``cancel`` levé arrête ses commandes git (``Forge.cancel``)."""
    forge: Forge
    if kind is ForgeKind.GITHUB:
        forge = GitHub(http, token)
    elif kind is ForgeKind.GITLAB:
        forge = GitLab(http, token, host=host or HOSTS[kind], renew=renew)
    else:
        forge = Bitbucket(http, token, renew=renew)
    forge.cancel = cancel
    return forge
