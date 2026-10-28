"""Le marqueur ``network`` : sauté par défaut, lancé avec ``--run-network``."""

from pathlib import Path

import pytest

CONFTEST = Path(__file__).with_name("conftest.py")

NETWORK_TEST = """
import pytest

@pytest.mark.network
def test_touches_network():
    pass

def test_offline():
    pass
"""


@pytest.fixture
def network_suite(pytester: pytest.Pytester) -> pytest.Pytester:
    pytester.makeconftest(CONFTEST.read_text(encoding="utf-8"))
    pytester.makepyfile(NETWORK_TEST)
    return pytester


def test_network_tests_are_skipped_by_default(network_suite: pytest.Pytester) -> None:
    result = network_suite.runpytest("--strict-markers")
    result.assert_outcomes(passed=1, skipped=1)


def test_run_network_option_runs_them(network_suite: pytest.Pytester) -> None:
    result = network_suite.runpytest("--strict-markers", "--run-network")
    result.assert_outcomes(passed=2)


def test_no_real_lockfile_tool_outside_network_tests() -> None:
    """Les outils de lockfile (npm, uv…) touchent le vrai registre : hors des tests ``network``,
    ``update.lockfiles`` les croit absents, et refuse d'en lancer un."""
    from forceupdate.update import lockfiles

    assert lockfiles._which("npm") is None
    assert lockfiles._which("uv") is None
    with pytest.raises(RuntimeError, match="outil réel refusé"):
        lockfiles._spawn(["npm", "install"])
