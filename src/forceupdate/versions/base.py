"""L'interface commune des versions : lire, comparer, classer l'écart, tester une contrainte.

Chaque écosystème a ses règles (PEP 440 pour PyPI, semver pour npm…), et comparer
deux versions comme des chaînes donne ``"1.10" < "1.9"``. Les modèles gardent les
versions et les contraintes en chaînes, telles qu'écrites ; une ``VersionScheme``
les interprète. Toute comparaison de versions du code passe par elle.

Ce qui est commun à tous les écosystèmes est écrit ici une fois :

- l'écart entre deux versions (``gap``), avec la règle du 0.x ;
- les candidates : les pré-versions sont écartées, sauf celles de la version actuelle
  quand c'en est une ;
- la plus haute version qui respecte une contrainte (``max_satisfying``).

Un écosystème n'écrit que la lecture d'une version et d'une contrainte.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any, Generic, Protocol, TypeVar

from forceupdate.models import Ecosystem, Gap


class InvalidVersion(ValueError):
    """Une version illisible selon les règles de son écosystème."""


class InvalidConstraint(ValueError):
    """Une contrainte illisible, ou qu'on ne sait pas interpréter seule (``catalog:``)."""


class _Comparable(Protocol):
    def __lt__(self, other: Any, /) -> bool: ...


V = TypeVar("V", bound=_Comparable)
"""Une version lue : un objet comparable (``packaging.version.Version``, ``SemVer``…)."""


class Constraint(ABC, Generic[V]):
    """Une contrainte lue : l'ensemble des versions qu'elle accepte."""

    @abstractmethod
    def contains(self, version: V) -> bool:
        """Vrai si ``version`` respecte la contrainte."""

    @abstractmethod
    def lower_bound(self) -> str | None:
        """La plus petite version que la contrainte accepte ; ``None`` si elle n'a pas de
        borne basse (``*``, ``<2``, une étiquette npm)."""

    def exact(self) -> str | None:
        """La version qu'impose une contrainte exacte (``==1.2.3``, ``1.2.3`` pour npm) ;
        ``None`` si elle en accepte plusieurs."""
        return None


class VersionScheme(ABC, Generic[V]):
    """Les règles de version d'un écosystème.

    Les versions et les contraintes entrent et sortent en chaînes, comme dans les
    modèles. Une version illisible lève ``InvalidVersion``, une contrainte illisible
    ``InvalidConstraint`` ; dans une liste de versions publiées, une version illisible
    est sautée (un registre en garde parfois de très anciennes, hors normes).
    """

    ecosystem: Ecosystem

    # -- à écrire pour chaque écosystème ------------------------------------

    @abstractmethod
    def parse(self, version: str) -> V:
        """La version lue, comparable avec ``<`` ; lève ``InvalidVersion``."""

    @abstractmethod
    def parse_constraint(self, constraint: str) -> Constraint[V]:
        """La contrainte lue, telle qu'écrite dans le manifeste ; lève ``InvalidConstraint``."""

    @abstractmethod
    def _release(self, version: V) -> tuple[int, int, int]:
        """Les trois premiers nombres de la version (majeure, mineure, correctif)."""

    @abstractmethod
    def _is_pre(self, version: V) -> bool:
        """Vrai pour une pré-version (``1.0.0-beta``, ``2.0.0rc1``)."""

    def _same_release(self, a: V, b: V) -> bool:
        """Vrai si ``a`` et ``b`` sont deux états de la même version (``2.0.0rc1`` et
        ``2.0.0rc2``, ``2.0.0-beta.1`` et ``2.0.0``)."""
        return self._release(a) == self._release(b)

    # -- commun --------------------------------------------------------------

    def compare(self, a: str, b: str) -> int:
        """``-1`` si ``a`` est plus ancienne que ``b``, ``0`` si égales, ``1`` si plus récente."""
        first, second = self.parse(a), self.parse(b)
        return -1 if first < second else 1 if second < first else 0

    def is_prerelease(self, version: str) -> bool:
        """Vrai pour une pré-version : ``1.0.0-beta`` (npm), ``2.0.0rc1`` ou ``1.0.dev1`` (PyPI)."""
        return self._is_pre(self.parse(version))

    def sort_key(self, version: str) -> tuple[int, Any]:
        """Une clé de tri qui ne lève jamais : les versions lisibles dans leur ordre, puis
        les autres (une référence git…) dans l'ordre du texte."""
        try:
            return (0, self.parse(version))
        except InvalidVersion:
            return (1, version)

    def gap(self, current: str, target: str) -> Gap | None:
        """L'écart pour passer de ``current`` à ``target`` ; ``None`` si ``target`` n'est
        pas plus récente.

        C'est le premier nombre qui change : de ``2.3.1``, ``2.3.4`` est un correctif,
        ``2.9.0`` une mineure, ``3.0.0`` une majeure. Deux règles s'y ajoutent :

        - **0.x** : une majeure est ce qui sort de ``^current``. En ``0.y.z``, ``y`` joue
          le rôle de la majeure (``0.2.3`` → ``0.3.0`` est majeure, ``0.2.3`` →
          ``0.2.4`` un correctif) ; en ``0.0.z``, tout changement est majeur ;
        - **pré-version** : ``X.Y.Z-rc.1`` est juste sous ``X.Y.Z``. Vers sa version
          finale, l'écart est celui de ``X.Y.Z`` : ``1.0.0-rc.1`` → ``1.0.0`` est majeure,
          ``1.2.0-rc.1`` → ``1.2.0`` mineure, ``1.2.3-rc.1`` → ``1.2.3`` un correctif.
          Une pré-version de ``X.0.0`` vient d'avant ``X.0.0`` : tout ce qui suit est
          majeur (``1.0.0-rc.1`` → ``1.1.1``). C'est la règle de ``semver.diff``.
        """
        a, b = self.parse(current), self.parse(target)
        if not a < b:
            return None
        return self._gap(a, b)

    def _gap(self, a: V, b: V) -> Gap:
        major, minor, patch = self._release(a)
        target = self._release(b)
        level: Gap
        if self._is_pre(a) and ((minor, patch) == (0, 0) or self._same_release(a, b)):
            if (minor, patch) == (0, 0):
                level = Gap.MAJOR
            else:
                level = Gap.MINOR if patch == 0 else Gap.PATCH
        elif target[0] != major:
            level = Gap.MAJOR
        elif target[1] != minor:
            level = Gap.MINOR
        else:
            level = Gap.PATCH
        if major == 0 and (minor == 0 or level is Gap.MINOR):
            return Gap.MAJOR
        return level

    def satisfies(self, constraint: str, version: str) -> bool:
        """Vrai si ``version`` respecte ``constraint``."""
        return self.parse_constraint(constraint).contains(self.parse(version))

    def lower_bound(self, constraint: str) -> str | None:
        """La plus petite version que ``constraint`` accepte (``^1.2`` → ``1.2.0`` pour npm,
        ``1.2`` pour PyPI) ; ``None`` sans borne basse (``*``, ``<2``).

        C'est la version actuelle approximative d'une dépendance sans lockfile (E07).
        """
        return self.parse_constraint(constraint).lower_bound()

    def exact(self, constraint: str) -> str | None:
        """La version qu'impose ``constraint`` si elle est exacte (``==1.2.3``) ; ``None``
        sinon. Sans lockfile, c'est une version actuelle qui n'a rien d'approximatif."""
        return self.parse_constraint(constraint).exact()

    def candidates(self, versions: Iterable[str], current: str | None = None) -> list[str]:
        """Les versions qu'on peut proposer, dans leur ordre : les versions lisibles, sans
        les pré-versions.

        Si ``current`` est une pré-version, celles de la même version restent :
        de ``2.0.0-rc.1``, on propose ``2.0.0-rc.2``, mais pas ``2.1.0-beta.1``.
        """
        return [text for text, _ in self._candidates(versions, current)]

    def _candidates(self, versions: Iterable[str], current: str | None) -> list[tuple[str, V]]:
        line = None
        if current is not None:
            parsed = self.parse(current)
            line = parsed if self._is_pre(parsed) else None
        kept = []
        for text in versions:
            try:
                version = self.parse(text)
            except InvalidVersion:
                continue
            if self._is_pre(version) and (line is None or not self._same_release(version, line)):
                continue
            kept.append((text, version))
        return kept

    def latest(self, versions: Iterable[str], current: str | None = None) -> str | None:
        """La plus haute des candidates (voir ``candidates``) ; ``None`` s'il n'y en a pas."""
        return _highest(self._candidates(versions, current))

    def max_satisfying(
        self, constraint: str, versions: Iterable[str], current: str | None = None
    ) -> str | None:
        """La plus haute des candidates (voir ``candidates``) qui respecte ``constraint`` :
        celle-là se met à jour sans toucher au manifeste. ``None`` s'il n'y en a pas."""
        parsed = self.parse_constraint(constraint)
        return _highest(
            (text, version)
            for text, version in self._candidates(versions, current)
            if parsed.contains(version)
        )

    def highest(self, versions: Iterable[str]) -> str | None:
        """La plus haute des versions lisibles, pré-versions comprises ; ``None`` s'il n'y
        en a pas."""
        readable = []
        for text in versions:
            try:
                readable.append((text, self.parse(text)))
            except InvalidVersion:
                continue
        return _highest(readable)


def _highest(pairs: Iterable[tuple[str, V]]) -> str | None:
    """Le texte de la plus haute version ; la première rencontrée en cas d'égalité
    (``1.0`` et ``1.0.0`` pour PyPI)."""
    best: tuple[str, V] | None = None
    for pair in pairs:
        if best is None or best[1] < pair[1]:
            best = pair
    return None if best is None else best[0]
