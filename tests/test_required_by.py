"""Qui requiert chaque paquet, et dans quelle plage (``Dependency.required_by``, session 37 puis
E37) : lu dans les lockfiles des mini-projets, faits par les vrais outils. ``package-lock.json``,
``yarn.lock`` (Yarn 1 et 2+) et ``poetry.lock`` disent les plages ; ``pnpm-lock.yaml`` et
``uv.lock`` seulement qui requiert quoi (la plage est lue au registre : ``update.blockers``)."""

from pathlib import Path

import pytest

from forceupdate import engine
from forceupdate.models import Dependency, Ecosystem, Requirement
from forceupdate.parsers.lockfiles import LockedPackage, Lockfile, required_by
from forceupdate.parsers.npm import parse_package_lock_json, parse_pnpm_lock_yaml, parse_yarn_lock
from forceupdate.sources.local import LocalSource

PROJECTS = Path(__file__).parent / "projects"


def dependency(mini: str, name: str, project: str = ".") -> Dependency:
    report = engine.inventory(LocalSource(PROJECTS / mini))
    found = next(p for p in report.projects if p.path == project)
    return next(d for d in found.dependencies if d.name == name)


def requirement(name: str, version: str, wanted: str, *, peer: bool = False) -> Requirement:
    return Requirement(name=name, version=version, range=wanted, peer=peer)


@pytest.mark.parametrize("mini", ["npm", "yarn1", "yarn4"])
def test_the_lockfile_says_the_range_of_each_parent(mini: str) -> None:
    """Yarn 2+ écrit ``npm:^4.1.0`` : la plage est ce qui suit ``npm:``."""
    assert dependency(mini, "ansi-styles").required_by == (requirement("chalk", "4.1.2", "^4.1.0"),)
    assert dependency(mini, "supports-color").required_by == (
        requirement("chalk", "4.1.2", "^7.1.0"),
    )


def test_poetry_lock_says_the_ranges() -> None:
    assert dependency("poetry", "urllib3").required_by == (
        requirement("requests", "2.34.2", ">=1.26,<3"),
    )


@pytest.mark.parametrize(
    ("mini", "name", "parent"),
    [("pnpm9", "ansi-styles", "chalk 4.1.2"), ("uv", "httpcore", "httpx 0.28.1")],
)
def test_pnpm_and_uv_say_who_requires_not_the_range(mini: str, name: str, parent: str) -> None:
    (found,) = dependency(mini, name).required_by
    assert f"{found.name} {found.version}" == parent
    assert found.range == ""


def test_a_peer_of_a_direct() -> None:
    """pnpm : ``react-dom`` demande ``react ^18.3.1`` comme dépendance pair ; ``react`` est une
    directe du projet. Une directe a aussi ses ``required_by`` (E37 : son refus prévu)."""
    react = dependency("pnpm9", "react", "packages/app")
    assert react.direct
    assert react.required_by == (requirement("react-dom", "18.3.1", "^18.3.1", peer=True),)


def test_not_the_project_nor_a_workspace_member() -> None:
    """Leurs plages sont les contraintes de leurs manifestes, réécrites par le plan."""
    found = dependency("npm-workspace", "ms", "packages/a")
    assert [r.name for r in found.required_by] == ["debug"]


def test_an_optional_peer_is_left_out() -> None:
    """npm ne l'impose que si le paquet la voit installée, ce qu'on ne sait pas dire."""
    lock = parse_package_lock_json(
        "package-lock.json",
        """{
          "lockfileVersion": 3,
          "packages": {
            "": {"dependencies": {"vite": "^8", "yaml": "^1"}},
            "node_modules/vite": {
              "version": "8.3.5",
              "peerDependencies": {"yaml": "^2.4.2", "terser": "^5"},
              "peerDependenciesMeta": {"yaml": {"optional": true}}
            },
            "node_modules/yaml": {"version": "1.10.3"},
            "node_modules/terser": {"version": "4.8.1"}
          }
        }""",
    )
    vite = lock.nodes["node_modules/vite"]
    assert vite.peers == {"terser": "^5"}
    found = required_by(lock.lockfile)
    assert ("yaml", "1.10.3") not in found
    assert found[("terser", "4.8.1")] == [requirement("vite", "8.3.5", "^5", peer=True)]


def test_yarn_berry_peers_and_pnpm_peers() -> None:
    berry = parse_yarn_lock(
        "yarn.lock",
        """__metadata:
  version: 8

"react-dom@npm:^18.3.1":
  version: 18.3.1
  resolution: "react-dom@npm:18.3.1"
  dependencies:
    loose-envify: "npm:^1.1.0"
  peerDependencies:
    react: ^18.3.1

"react@npm:^18.3.1":
  version: 18.3.1
  resolution: "react@npm:18.3.1"

"loose-envify@npm:^1.1.0":
  version: 1.4.0
  resolution: "loose-envify@npm:1.4.0"
""",
    )
    found = required_by(berry.lockfile)
    assert found[("react", "18.3.1")] == [requirement("react-dom", "18.3.1", "^18.3.1", peer=True)]
    assert found[("loose-envify", "1.4.0")] == [requirement("react-dom", "18.3.1", "^1.1.0")]
    pnpm = parse_pnpm_lock_yaml(
        "pnpm-lock.yaml",
        (PROJECTS / "pnpm9" / "pnpm-lock.yaml").read_text(encoding="utf-8"),
    )
    assert not pnpm.lockfile.ranges
    assert pnpm.nodes["react-dom@18.3.1(react@18.3.1)"].peers == {"react": "^18.3.1"}


def test_other_lockfiles_say_nothing() -> None:
    """Un lockfile qui a un graphe mais pas de plages (Cargo, Composer…) : rien."""
    lock = Lockfile(
        path="Cargo.lock",
        ecosystem=Ecosystem.CRATES_IO,
        packages=(
            LockedPackage(name="a", version="1.0.0", dependencies=(("b", frozenset()),)),
            LockedPackage(name="b", version="2.0.0"),
        ),
        graph=True,
    )
    assert required_by(lock) == {}
