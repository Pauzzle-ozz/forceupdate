"""Les versions Go (modules) : semver avec ``v``, pseudo-versions, ``+incompatible``.

Une version de module s'écrit ``v1.2.3`` : semver 2.0 strict, ``v`` devant, comme le lit le
paquet ``golang.org/x/mod/semver`` dont se sert ``go``. En plus :

- **pseudo-versions** : un commit sans étiquette, ``v0.0.0-20230101120000-abcdef123456`` (aucune
  version étiquetée avant lui), ``v1.2.4-0.20230101120000-abcdef123456`` (après ``v1.2.3``),
  ``v1.2.3-pre.0.20230101120000-abcdef123456`` (après ``v1.2.3-pre``). Pour semver ce sont des
  pré-versions ; leur horodatage (14 chiffres, UTC) vient en tête de l'identifiant comparé comme
  du texte : l'ordre de semver les range par date. Le proxy ne les liste pas (``@v/list``) :
  elles sont « non listées » (``unlisted``), pas dépubliées ;
- ``+incompatible`` : une v2 ou plus d'un dépôt sans ``go.mod``, publiée sous le chemin sans
  ``/v2``. C'est une métadonnée de build : pour l'ordre, ``v2.0.0+incompatible`` vaut ``v2.0.0`` ;
- OSV écrit les versions de ses avis Go sans ``v`` (``"fixed": "0.3.8"``, vérifié le
  2026-10-30) : elles se lisent aussi, et ``canonical`` remet le ``v``.

**Une version de go.mod n'est pas une plage.** C'est un minimum : ``go`` construit avec la plus
haute des versions minimales que demandent le module et ses dépendances (sélection de version
minimale), et ``go mod tidy`` écrit cette version-là dans ``go.mod`` (vérifié avec Go 1.27 : une
dépendance qui en demande une plus haute fait monter la ligne). La version écrite est donc la
version utilisée, et aucune autre ne s'obtient sans réécrire ``go.mod``. Une contrainte Go
n'accepte que sa version (``satisfies``) ; c'est aussi sa borne basse et sa version exacte.

**Le chemin du module dit sa majeure** : ``github.com/foo/bar`` pour v0 et v1 (et les
``+incompatible``), ``github.com/foo/bar/v2`` pour v2, ``gopkg.in/yaml.v3`` pour v3. Changer de
majeure, c'est changer de module, et tous les imports du code (``moved``).
"""

import functools
import re

from forceupdate.models import Ecosystem
from forceupdate.versions.base import Constraint, InvalidConstraint, InvalidVersion, VersionScheme
from forceupdate.versions.npm import SemVer

_NUMBER = r"0|[1-9]\d*"
_PRE_ID = r"(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
_BUILD_ID = r"[0-9A-Za-z-]+"

_VERSION = re.compile(
    rf"v?(?P<major>{_NUMBER})\.(?P<minor>{_NUMBER})\.(?P<patch>{_NUMBER})"
    rf"(?:-(?P<pre>{_PRE_ID}(?:\.{_PRE_ID})*))?"
    rf"(?:\+(?P<build>{_BUILD_ID}(?:\.{_BUILD_ID})*))?",
    re.ASCII,
)
"""Une version : semver strict, ``v`` devant (facultatif pour lire les avis d'OSV)."""

_PSEUDO = re.compile(
    r"v?[0-9]+\.(?:0\.0-|\d+\.\d+-(?:[^+]*\.)?0\.)\d{14}-[A-Za-z0-9]+"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?",
    re.ASCII,
)
"""Une pseudo-version : l'expression de ``golang.org/x/mod/module`` (``pseudoVersionRE``)."""

_SLASH_MAJOR = re.compile(r"(?P<prefix>.+)/v(?P<major>[2-9]|[1-9]\d+)", re.ASCII)
"""Un chemin de module à suffixe de majeure : ``github.com/foo/bar/v2`` (pas ``/v1`` ni
``/v0``)."""

_GOPKG = re.compile(
    r"(?P<prefix>gopkg\.in/(?:[^/]+/)?[^/.]+)\.v(?P<major>0|[1-9]\d*)(?P<unstable>-unstable)?",
    re.ASCII,
)
"""Un chemin ``gopkg.in`` : la majeure suit un point (``gopkg.in/yaml.v3``)."""

INCOMPATIBLE = "+incompatible"


class GoRequirement(Constraint[SemVer]):
    """Une version de ``go.mod`` : elle n'accepte qu'elle-même (voir la docstring du module)."""

    def __init__(self, text: str, version: SemVer) -> None:
        self.text = text
        self.version = version

    def __str__(self) -> str:
        return self.text

    def __repr__(self) -> str:
        return f"GoRequirement({self.text!r})"

    def contains(self, version: SemVer) -> bool:
        return version == self.version

    def lower_bound(self) -> str | None:
        return self.text

    def exact(self) -> str | None:
        return self.text


class GoVersions(VersionScheme[SemVer]):
    """semver avec ``v``, pseudo-versions et ``+incompatible`` ; une contrainte est une version."""

    ecosystem = Ecosystem.GO

    def parse(self, version: str) -> SemVer:
        return _parse(version)

    def parse_constraint(self, constraint: str) -> GoRequirement:
        text = canonical(constraint.strip())
        try:
            return GoRequirement(text, _parse(text))
        except InvalidVersion:
            raise InvalidConstraint(f"version de module illisible : {constraint!r}") from None

    def _release(self, version: SemVer) -> tuple[int, int, int]:
        return version.release

    def _is_pre(self, version: SemVer) -> bool:
        return bool(version.prerelease)

    def written(self, version: str) -> str:
        return canonical(version)

    def unlisted(self, version: str) -> bool:
        return is_pseudo(version)

    def moved(self, name: str, version: str) -> str | None:
        """Le chemin du module où se publie ``version``, quand ce n'est pas ``name`` : une autre
        majeure (``github.com/foo/bar`` → ``github.com/foo/bar/v2``) ; ``None`` sinon."""
        try:
            parsed = _parse(version)
        except InvalidVersion:
            return None
        path = module_path(name, parsed.major, incompatible=INCOMPATIBLE in version)
        return None if path == name else path


GO = GoVersions()


def canonical(version: str) -> str:
    """``version`` avec son ``v`` (``0.3.8`` → ``v0.3.8``), comme l'écrit ``go.mod``."""
    return version if version.startswith("v") else f"v{version}"


def is_pseudo(version: str) -> bool:
    """Vrai pour une pseudo-version (``v0.0.0-20230101120000-abcdef123456``)."""
    return _PSEUDO.fullmatch(version) is not None


def path_major(path: str) -> int | None:
    """La majeure que dit le chemin du module : 2 pour ``…/v2``, 3 pour ``gopkg.in/yaml.v3`` ;
    ``None`` pour un chemin sans suffixe (v0, v1, et les ``+incompatible``)."""
    found = _GOPKG.fullmatch(path) or _SLASH_MAJOR.fullmatch(path)
    return None if found is None else int(found["major"])


def module_path(path: str, major: int, *, incompatible: bool = False) -> str:
    """Le chemin du module ``path`` pour la majeure ``major`` : le même s'il la porte déjà, sinon
    celui de l'autre majeure (``github.com/foo/bar`` en 2 : ``github.com/foo/bar/v2``). Une
    version ``+incompatible`` reste sous un chemin sans suffixe."""
    gopkg = _GOPKG.fullmatch(path)
    if gopkg is not None:
        if int(gopkg["major"]) == major:
            return path
        return f"{gopkg['prefix']}.v{major}{gopkg['unstable'] or ''}"
    slash = _SLASH_MAJOR.fullmatch(path)
    prefix = path if slash is None else slash["prefix"]
    current = None if slash is None else int(slash["major"])
    if current == major or (current is None and (major <= 1 or incompatible)):
        return path
    return prefix if major <= 1 else f"{prefix}/v{major}"


def _identifiers(text: str | None) -> tuple[int | str, ...]:
    if not text:
        return ()
    return tuple(int(part) if part.isdigit() else part for part in text.split("."))


@functools.lru_cache(maxsize=4096)
def _parse(version: str) -> SemVer:
    match = _VERSION.fullmatch(version.strip())
    if match is None:
        raise InvalidVersion(f"version de module Go illisible : {version!r}")
    build = match.group("build")
    return SemVer(
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        _identifiers(match.group("pre")),
        tuple(build.split(".")) if build else (),
    )
