"""Les forges : GitHub, GitLab, Bitbucket Cloud (brief, « Forges » ; PLAN, phase E).

- ``base.py`` : l'interface ``Forge`` et ses types, la seule que connaît le reste de l'outil ;
- ``github.py`` : le client REST de GitHub, et la connexion d'un compte (OAuth, device flow,
  token collé, ``gh``) ;
- ``git.py`` : git, pour cloner un dépôt et y pousser une branche, le token passé par un
  credential helper éphémère (E18) ;
- ``accounts.py`` : les comptes connectés, leurs tokens dans le trousseau du système.

``FORGES`` dit lesquelles existent et lesquelles se connectent déjà ; ``client`` rend la forge
d'un token ; ``parse_repository`` lit un dépôt donné par son nom ou son adresse.
"""

import re
import urllib.parse
from dataclasses import dataclass

from forceupdate.forges.base import Forge, ForgeKind
from forceupdate.forges.github import GitHub
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


FORGES = (
    ForgeInfo(kind=ForgeKind.GITHUB, name="GitHub", host="github.com", available=True),
    ForgeInfo(kind=ForgeKind.GITLAB, name="GitLab", host="gitlab.com", available=False),
    ForgeInfo(kind=ForgeKind.BITBUCKET, name="Bitbucket", host="bitbucket.org", available=False),
)


HOSTS = {forge.kind: forge.host for forge in FORGES}


def info(kind: ForgeKind) -> ForgeInfo:
    return next(forge for forge in FORGES if forge.kind is kind)


_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
_REPO = re.compile(r"[A-Za-z0-9._-]{1,100}")


def parse_repository(text: str) -> tuple[ForgeInfo, str]:
    """La forge et le nom (``owner/nom``) d'un dépôt donné par la personne : ``owner/nom``
    (GitHub), ou son adresse (``https://github.com/owner/nom``, ``…/nom.git``,
    ``git@github.com:owner/nom.git``, une page du dépôt). Lève ``ValueError`` avec un message
    à montrer."""
    value = text.strip()
    if value.startswith("git@"):
        host, _, path = value[4:].partition(":")
    elif "://" in value or value.split("/", 1)[0].count(".") >= 1:
        parsed = urllib.parse.urlsplit(value if "://" in value else f"https://{value}")
        if parsed.scheme not in ("https", "http"):
            raise ValueError(f"« {text} » : donner owner/nom, ou l'adresse https du dépôt.")
        host, path = (parsed.hostname or ""), parsed.path
    else:
        host, path = HOSTS[ForgeKind.GITHUB], value
    host = host.lower().removeprefix("www.")
    forge = next((f for f in FORGES if f.host == host), None)
    if forge is None:
        raise ValueError(f"« {host} » : seuls GitHub, GitLab et Bitbucket sont connus.")
    parts = [part for part in path.strip("/").split("/") if part]
    if len(parts) < 2:
        raise ValueError(f"« {text} » : donner owner/nom, ou l'adresse du dépôt.")
    owner, name = parts[0], parts[1].removesuffix(".git")
    if not _NAME.fullmatch(owner) or not _REPO.fullmatch(name) or name in (".", ".."):
        raise ValueError(f"« {owner}/{name} » n'est pas un nom de dépôt.")
    return forge, f"{owner}/{name}"


def client(kind: ForgeKind, http: HttpClient, token: str | None) -> Forge:
    """La forge ``kind``, vue avec ``token`` ; sans token, ses dépôts publics seulement."""
    if kind is ForgeKind.GITHUB:
        return GitHub(http, token)
    raise NotImplementedError(f"{info(kind).name} : la connexion n'est pas encore disponible")
