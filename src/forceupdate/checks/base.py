"""Ce que partagent les contrôles : la version actuelle d'une dépendance, la plus proche
version de remplacement, les noms des écarts.

La version actuelle (brief, décision n°2) est celle du lockfile. Sans lockfile, c'est la
version qu'impose une contrainte exacte (``==1.2.3``), sinon la borne basse de la contrainte,
marquée « approximative » : la version réellement installée peut être plus haute. Sans borne
basse (``*``, ``<2``, une étiquette npm), on ne la connaît pas, et on le dit.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from forceupdate import versions
from forceupdate.models import Dependency, Gap
from forceupdate.versions import InvalidConstraint, VersionScheme
from forceupdate.versions.npm import NpmRange

GAP_LABELS = {Gap.MAJOR: "majeure", Gap.MINOR: "mineure", Gap.PATCH: "correctif"}
"""L'écart en français, tel qu'on l'affiche."""


@dataclass(frozen=True, kw_only=True)
class Current:
    """La version actuelle d'une dépendance : celle qu'on compare à ce que dit le registre."""

    version: str | None
    """L'installée ; sinon celle qu'impose une contrainte exacte ; sinon la borne basse de la
    contrainte. ``None`` si on ne peut rien en dire (voir ``unknown``)."""
    approximate: bool = False
    """Vrai pour une borne basse : la version réellement installée peut être plus haute."""
    constraint: str | None = None
    """La contrainte à interpréter (``Dependency.effective_constraint``) ; ``None`` si elle est
    illisible (ou un ``catalog:`` introuvable) : on se fie alors à la version installée."""
    unknown: str | None = None
    """Pourquoi la version actuelle est inconnue, en français, quand ``version`` est ``None``."""


def current_version(dependency: Dependency) -> Current:
    """La version actuelle de ``dependency`` (voir ``Current``)."""
    scheme = versions.for_ecosystem(dependency.ecosystem)
    text = dependency.effective_constraint
    try:
        parsed = scheme.parse_constraint(text)
    except InvalidConstraint:
        parsed = None
    constraint = None if parsed is None else text
    if dependency.installed is not None:
        return Current(version=dependency.installed, constraint=constraint)
    if parsed is None:
        if dependency.constraint.startswith("catalog:") and dependency.resolved_constraint is None:
            why = f"la plage de « {dependency.constraint} » est introuvable"
        else:
            why = f"la contrainte « {text} » est illisible"
        return Current(version=None, unknown=f"{why}, et pas de version installée")
    exact = parsed.exact()
    if exact is not None:
        return Current(version=exact, constraint=constraint)
    lower = parsed.lower_bound()
    if lower is not None:
        return Current(version=lower, approximate=True, constraint=constraint)
    if not text.strip():
        why = "aucune contrainte"
    elif isinstance(parsed, NpmRange) and parsed.tag is not None:
        why = f"l'étiquette « {parsed.tag} » suit le registre"
    else:
        why = f"la contrainte « {text} » n'a pas de borne basse"
    return Current(
        version=None, constraint=constraint, unknown=f"{why}, et pas de version installée"
    )


def sentence(text: str) -> str:
    """``text`` terminé par un point, sans en doubler un (le message d'un registre ou d'un avis
    peut déjà finir par ``.``, ``!``, ``?`` ou ``…``)."""
    text = text.rstrip()
    return text if text.endswith((".", "!", "?", "…")) else text + "."


def nearest(scheme: VersionScheme, current: str, choices: Iterable[str]) -> str | None:
    """La version de ``choices`` la plus proche de ``current``, pour remplacer une version
    retirée ou dépréciée : la plus petite au-dessus sans changer de majeure (souvent celle
    qui corrige), sinon la plus haute en dessous, sinon la plus petite au-dessus. Parmi les
    candidates seulement (pas de pré-version, sauf celles de ``current`` si c'en est une).
    ``None`` s'il n'y en a aucune."""
    above, below = [], []
    for version in scheme.candidates(choices, current):
        order = scheme.compare(version, current)
        if order > 0:
            above.append(version)
        elif order < 0:
            below.append(version)
    above.sort(key=scheme.sort_key)
    same_line = [v for v in above if scheme.gap(current, v) is not Gap.MAJOR]
    if same_line:
        return same_line[0]
    if below:
        return max(below, key=scheme.sort_key)
    return above[0] if above else None
