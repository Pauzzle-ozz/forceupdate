"""Les forges : GitHub, GitLab, Bitbucket Cloud (brief, « Forges » ; PLAN, phase E).

- ``base.py`` : l'interface ``Forge`` et ses types, la seule que connaît le reste de l'outil ;
- ``github.py`` : le client REST de GitHub, et la connexion d'un compte (OAuth, device flow,
  token collé, ``gh``) ;
- ``accounts.py`` : les comptes connectés, leurs tokens dans le trousseau du système.

``FORGES`` dit lesquelles existent et lesquelles se connectent déjà ; ``client`` rend la forge
d'un token.
"""

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


def info(kind: ForgeKind) -> ForgeInfo:
    return next(forge for forge in FORGES if forge.kind is kind)


def client(kind: ForgeKind, http: HttpClient, token: str) -> Forge:
    """La forge ``kind``, vue avec ``token``."""
    if kind is ForgeKind.GITHUB:
        return GitHub(http, token)
    raise NotImplementedError(f"{info(kind).name} : la connexion n'est pas encore disponible")
