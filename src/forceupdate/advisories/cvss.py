"""Le score CVSS d'une faille, calculé depuis son vecteur, sans dépendance.

OSV donne la gravité d'une faille sous forme de vecteur (``CVSS:3.1/AV:N/AC:L/…``), pas de
score. Le calcul suit la spécification de FIRST (CVSS 3.1, section 7.1), y compris son
arrondi (annexe A), qui évite les erreurs de calcul en virgule flottante : un arrondi naïf
(``ceil(x * 10) / 10``) donne parfois un dixième de trop. Les vecteurs CVSS 3.0 ont les mêmes
formules ; seul leur arrondi diffère, et ne change le score que dans ces cas d'erreur.

CVSS 4.0 n'est pas calculé (il faut les tables de la spécification) : OSV le donne rarement
seul, et GitHub ajoute alors sa propre gravité, que lit ``advisories.osv``.

Repris de ``reference/argos_sca_parsers.py`` (``_cvss_base_score_from_vector``,
``_cvss_to_severity``), puis adapté : ``Severity`` de ``models`` (``ARGOS (1)``), métriques
lues dans n'importe quel ordre, arrondi de la spécification, ``None`` pour un vecteur
illisible au lieu de 0.
"""

import re

from forceupdate.models import Severity

_PREFIX = re.compile(r"^CVSS:3\.[01]/")
_LEADING_SCORE = re.compile(r"^(\d{1,2}\.\d)/")
"""Un score écrit devant le vecteur (``9.8/CVSS:3.1/…``), comme certaines bases le font."""

_WEIGHTS: dict[str, dict[str, float]] = {
    "AV": {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2},
    "AC": {"L": 0.77, "H": 0.44},
    "UI": {"N": 0.85, "R": 0.62},
    "C": {"H": 0.56, "L": 0.22, "N": 0.0},
    "I": {"H": 0.56, "L": 0.22, "N": 0.0},
    "A": {"H": 0.56, "L": 0.22, "N": 0.0},
}
_PRIVILEGES = {"N": 0.85, "L": 0.62, "H": 0.27}
_PRIVILEGES_CHANGED = {"N": 0.85, "L": 0.68, "H": 0.5}
"""PR pèse plus quand la faille sort de son périmètre (``S:C``)."""


def base_score(vector: str) -> float | None:
    """Le score de base (0 à 10) d'un vecteur CVSS 3.0 ou 3.1 ; ``None`` s'il est illisible.

    Les métriques temporelles et environnementales (``E:``, ``RL:``…) sont ignorées : le
    score de base est celui que publient les avis.
    """
    vector = vector.strip()
    leading = _LEADING_SCORE.match(vector)
    if leading:
        return float(leading.group(1))
    if not _PREFIX.match(vector):
        return None
    metrics: dict[str, str] = {}
    for part in vector.split("/")[1:]:
        name, _, value = part.partition(":")
        metrics.setdefault(name, value)
    try:
        scope_changed = {"U": False, "C": True}[metrics["S"]]
        privileges = (_PRIVILEGES_CHANGED if scope_changed else _PRIVILEGES)[metrics["PR"]]
        weights = {name: _WEIGHTS[name][metrics[name]] for name in _WEIGHTS}
    except KeyError:
        return None
    iss = 1 - (1 - weights["C"]) * (1 - weights["I"]) * (1 - weights["A"])
    impact = (7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15) if scope_changed else 6.42 * iss
    if impact <= 0:
        return 0.0
    exploitability = 8.22 * weights["AV"] * weights["AC"] * privileges * weights["UI"]
    total = impact + exploitability
    if scope_changed:
        total *= 1.08
    return _roundup(min(total, 10.0))


def _roundup(value: float) -> float:
    """Le plus petit nombre à une décimale qui est au moins ``value`` (CVSS 3.1, annexe A).

    Calculé en entiers : ``ceil(4.000000000000001 * 10) / 10`` donnerait 4.1 au lieu de 4.0.
    """
    integer = round(value * 100_000)
    if integer % 10_000 == 0:
        return integer / 100_000
    return (integer // 10_000 + 1) / 10


def severity(score: float) -> Severity:
    """La gravité d'un score CVSS, selon l'échelle de la spécification : critique à partir de
    9, élevée à partir de 7, moyenne à partir de 4, faible au-dessus de 0. Un score nul
    (aucun impact) donne ``INFO``."""
    if score >= 9.0:
        return Severity.CRITICAL
    if score >= 7.0:
        return Severity.HIGH
    if score >= 4.0:
        return Severity.MEDIUM
    if score > 0.0:
        return Severity.LOW
    return Severity.INFO
