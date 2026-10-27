"""Le score CVSS 3 d'un vecteur, et la gravité qui va avec. Les scores attendus sont ceux que
publie NVD pour ces vecteurs."""

import pytest

from forceupdate.advisories import cvss
from forceupdate.models import Severity


@pytest.mark.parametrize(
    ("vector", "score"),
    [
        ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", 9.8),
        ("CVSS:3.1/AV:N/AC:L/PR:H/UI:N/S:U/C:H/I:H/A:H", 7.2),  # CVE-2021-23337, lodash
        ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:L", 5.3),  # CVE-2020-28500, lodash
        ("CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:N/I:H/A:H", 7.4),  # CVE-2020-8203, lodash
        ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H", 7.5),  # CVE-2018-1000656, flask
        ("CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N", 6.1),  # une XSS typique
        ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H", 10.0),  # plafonné à 10
        ("CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:C/C:H/I:H/A:H", 9.9),  # PR pèse plus, périmètre changé
        ("CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H", 7.8),
        ("CVSS:3.1/AV:P/AC:H/PR:H/UI:R/S:U/C:L/I:N/A:N", 1.6),
        ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:N", 0.0),  # aucun impact
        ("CVSS:3.0/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N", 7.5),  # crossenv, en CVSS 3.0
    ],
)
def test_base_score(vector: str, score: float) -> None:
    assert cvss.base_score(vector) == score


def test_metrics_in_any_order_and_temporal_metrics_ignored() -> None:
    vector = "CVSS:3.1/S:U/AV:N/C:H/AC:L/I:H/PR:N/A:H/UI:N/E:P/RL:O/RC:C"
    assert cvss.base_score(vector) == 9.8


def test_a_score_written_before_the_vector() -> None:
    assert cvss.base_score("9.8/CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H") == 9.8


@pytest.mark.parametrize(
    "vector",
    [
        "",
        "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N",
        "AV:N/AC:L/Au:N/C:P/I:P/A:P",  # CVSS 2
        "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H",  # A manque
        "CVSS:3.1/AV:X/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",  # valeur inconnue
    ],
)
def test_unreadable_vectors(vector: str) -> None:
    assert cvss.base_score(vector) is None


def test_roundup_of_the_specification() -> None:
    """L'arrondi de l'annexe A : au dixième supérieur, sans l'erreur de la virgule flottante
    (un arrondi naïf donnerait 4.1 pour 4.000000000000001)."""
    assert cvss._roundup(4.02) == 4.1
    assert cvss._roundup(4.0) == 4.0
    assert cvss._roundup(4.000000000000001) == 4.0


@pytest.mark.parametrize(
    ("score", "severity"),
    [
        (10.0, Severity.CRITICAL),
        (9.0, Severity.CRITICAL),
        (8.9, Severity.HIGH),
        (7.0, Severity.HIGH),
        (6.9, Severity.MEDIUM),
        (4.0, Severity.MEDIUM),
        (3.9, Severity.LOW),
        (0.1, Severity.LOW),
        (0.0, Severity.INFO),
    ],
)
def test_severity(score: float, severity: Severity) -> None:
    assert cvss.severity(score) is severity
