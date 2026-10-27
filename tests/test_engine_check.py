"""Le moteur qui vérifie : registres, constats, événements, options. Hors ligne, sur les
réponses enregistrées (fixture ``recorded``)."""

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import respx

from forceupdate import engine
from forceupdate.models import (
    Event,
    EventKind,
    Finding,
    FindingKind,
    Gap,
    Report,
    ScanOptions,
    Severity,
)
from forceupdate.net import Cache, CacheKind, HttpClient
from forceupdate.registries import Registry
from forceupdate.sources.local import LocalSource

MakeTree = Callable[..., Path]
Routes = dict[str, respx.Route]

REQUIREMENTS = """\
flask==2.0.1
requests==2.32.0
aioredis>=1.3
private-package>=1.0
"""
PACKAGE_JSON = {
    "name": "web",
    "dependencies": {"left-pad": "^1.1.0", "colors": "1.4.1"},
    "devDependencies": {"@hapi/joi": "^17.0.0", "local-lib": "file:../lib"},
}


async def no_sleep(_: float) -> None:
    pass


def analyze(root: Path, options: ScanOptions | None = None, **kwargs: Any) -> Report:
    async def main() -> Report:
        async with HttpClient(offline=bool(options and options.offline), sleep=no_sleep) as http:
            return await engine.analyze(LocalSource(root), options, http=http, **kwargs)

    return asyncio.run(main())


def by_name(findings: list[Finding]) -> dict[str, list[FindingKind]]:
    found: dict[str, list[FindingKind]] = {}
    for finding in findings:
        assert finding.dependency is not None
        found.setdefault(finding.dependency.name, []).append(finding.kind)
    return found


@pytest.fixture
def monorepo(make_tree: MakeTree) -> Path:
    return make_tree(
        {
            "api/requirements.txt": REQUIREMENTS,
            "web/package.json": json.dumps(PACKAGE_JSON),
        }
    )


def test_findings_of_a_python_and_npm_monorepo(recorded: Routes, monorepo: Path) -> None:
    report = analyze(monorepo, cache=Cache.disabled())
    api, web = report.projects
    assert by_name(api.findings) == {
        "requests": [FindingKind.YANKED, FindingKind.OUTDATED],
        "aioredis": [FindingKind.DEPRECATED, FindingKind.OUTDATED],
        "flask": [FindingKind.OUTDATED],
        "private-package": [FindingKind.UNVERIFIABLE],
    }
    # Du plus grave au moins grave : retirée, dépréciée, majeure, mineure, non vérifiable.
    assert [f.kind for f in api.findings] == [
        FindingKind.YANKED,
        FindingKind.DEPRECATED,
        FindingKind.OUTDATED,
        FindingKind.OUTDATED,
        FindingKind.OUTDATED,
        FindingKind.UNVERIFIABLE,
    ]
    flask = next(f for f in api.findings if f.dependency and f.dependency.name == "flask")
    assert (flask.current_version, flask.target_version, flask.gap) == ("2.0.1", "3.1.3", Gap.MAJOR)
    yanked = api.findings[0]
    assert (yanked.current_version, yanked.target_version) == ("2.32.0", "2.32.2")
    assert yanked.detail == "Yanked due to conflicts with CVE-2024-35195 mitigation"
    assert api.findings[-1].message == (
        "private-package est introuvable sur PyPI : paquet privé, ou nom mal écrit ?"
    )

    assert by_name(web.findings) == {
        "@hapi/joi": [FindingKind.DEPRECATED, FindingKind.OUTDATED],
        "left-pad": [FindingKind.DEPRECATED, FindingKind.OUTDATED],
        "local-lib": [FindingKind.UNVERIFIABLE],
        "colors": [FindingKind.INCONCLUSIVE],
    }
    colors = next(f for f in web.findings if f.dependency and f.dependency.name == "colors")
    assert colors.message.startswith("Version 1.4.1 inconnue de npm : dépubliée")
    left_pad = [f for f in web.findings if f.dependency and f.dependency.name == "left-pad"]
    assert left_pad[1].current_is_approximate
    assert (left_pad[1].current_version, left_pad[1].target_version) == ("1.1.0", "1.3.0")
    local = next(f for f in web.findings if f.kind is FindingKind.UNVERIFIABLE)
    assert local.message == "Non vérifiable : chemin local."

    assert report.options == ScanOptions()
    assert report.scanned_at is not None and report.oldest_data is not None
    assert report.scanned_at <= report.oldest_data


def test_events(recorded: Routes, monorepo: Path) -> None:
    events: list[Event] = []
    analyze(monorepo, cache=Cache.disabled(), on_event=events.append)
    kinds = [event.kind for event in events]
    assert kinds[:3] == [EventKind.READING, EventKind.PROJECTS_FOUND, EventKind.CHECKING]
    assert kinds[-1] is EventKind.FINISHED
    assert events[1].total == 2
    checked = [event for event in events if event.kind is EventKind.PACKAGE_CHECKED]
    assert events[2].total == len(checked) == 7  # local-lib n'est pas demandé
    assert [event.done for event in checked] == list(range(1, 8))
    assert {event.name for event in checked} == {
        "flask",
        "requests",
        "aioredis",
        "private-package",
        "left-pad",
        "colors",
        "@hapi/joi",
    }


def test_a_package_is_asked_once(recorded: Routes, make_tree: MakeTree) -> None:
    """Déclaré deux fois dans un projet, et dans deux projets : une seule requête."""
    root = make_tree(
        {
            "a/pyproject.toml": (
                '[project]\nname = "a"\ndependencies = ["Flask>=2"]\n'
                '[dependency-groups]\ndev = ["flask>=3"]\n'
            ),
            "b/requirements.txt": "flask==3.1.3\n",
        }
    )
    report = analyze(root, cache=Cache.disabled())
    assert recorded["flask"].call_count == 1
    a, b = report.projects
    assert [f.dependency.scope for f in a.findings if f.dependency] == ["runtime", "dev"]
    assert b.findings == []


def test_a_registry_error_is_inconclusive(recorded: Routes, make_tree: MakeTree) -> None:
    recorded["flask"].respond(503)
    report = analyze(make_tree({"requirements.txt": "flask==2.0.1\n"}), cache=Cache.disabled())
    (finding,) = report.findings
    assert finding.kind is FindingKind.INCONCLUSIVE
    assert finding.severity is Severity.INFO
    assert finding.message.startswith("PyPI : ")


def test_a_bug_is_not_hidden(
    recorded: Routes, make_tree: MakeTree, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(self: Registry, name: str) -> None:
        raise ZeroDivisionError

    monkeypatch.setattr(Registry, "package", broken)
    with pytest.raises(ZeroDivisionError):
        analyze(make_tree({"requirements.txt": "flask==2.0.1\n"}), cache=Cache.disabled())


def test_without_dev_dependencies(recorded: Routes, monorepo: Path) -> None:
    report = analyze(monorepo, ScanOptions(dev=False), cache=Cache.disabled())
    assert "@hapi/joi" not in by_name(report.findings)
    assert "local-lib" not in by_name(report.findings)
    assert recorded["@hapi/joi"].call_count == 0


def test_transitive_dependencies(recorded: Routes, make_tree: MakeTree) -> None:
    lock = {
        "name": "web",
        "lockfileVersion": 3,
        "packages": {
            "": {"name": "web", "dependencies": {"left-pad": "^1.3.0"}},
            "node_modules/left-pad": {"version": "1.3.0", "dependencies": {"colors": "^1.3.0"}},
            "node_modules/colors": {"version": "1.3.3"},
        },
    }
    root = make_tree(
        {
            "package.json": json.dumps({"dependencies": {"left-pad": "^1.3.0"}}),
            "package-lock.json": json.dumps(lock),
        }
    )
    assert "colors" not in by_name(analyze(root, cache=Cache.disabled()).findings)

    report = analyze(root, ScanOptions(transitive=True), cache=Cache.disabled())
    colors = [f for f in report.findings if f.dependency and f.dependency.name == "colors"]
    assert [(f.kind, f.current_version, f.target_version) for f in colors] == [
        (FindingKind.OUTDATED, "1.3.3", "1.4.0")
    ]
    assert colors[0].wanted_version is None
    assert not colors[0].dependency.direct  # type: ignore[union-attr]


def test_a_workspace_member_has_no_finding(make_tree: MakeTree) -> None:
    root = make_tree(
        {
            "package.json": json.dumps({"workspaces": ["packages/*"]}),
            "packages/a/package.json": json.dumps({"name": "a", "version": "1.0.0"}),
            "packages/b/package.json": json.dumps(
                {"name": "b", "dependencies": {"a": "workspace:*"}}
            ),
        }
    )
    report = analyze(root, cache=Cache.disabled())
    assert report.findings == []


def test_offline_uses_stale_cache_and_dates_it(
    recorded: Routes, make_tree: MakeTree, tmp_path: Path
) -> None:
    root = make_tree({"proj/requirements.txt": "flask==2.0.1\nrequests>=2\n"})
    week_ago = datetime(2026, 10, 20, 9, 30, tzinfo=UTC).timestamp()
    disk = Cache(tmp_path / "c.sqlite3", clock=lambda: week_ago)
    analyze(root, cache=disk)  # range flask et requests dans le cache, datés d'il y a une semaine
    disk.close()
    recorded["flask"].reset()

    later = Cache(tmp_path / "c.sqlite3")
    report = analyze(root, ScanOptions(offline=True), cache=later)
    later.close()
    assert recorded["flask"].call_count == 0
    assert report.options is not None and report.options.offline
    assert report.oldest_data == datetime(2026, 10, 20, 9, 30, tzinfo=UTC)
    assert [f.kind for f in report.findings] == [FindingKind.OUTDATED, FindingKind.OUTDATED]


def test_offline_without_cache_is_inconclusive(make_tree: MakeTree) -> None:
    root = make_tree({"requirements.txt": "flask==2.0.1\n"})
    report = analyze(root, ScanOptions(offline=True), cache=Cache.disabled())
    (finding,) = report.findings
    assert finding.kind is FindingKind.INCONCLUSIVE
    assert finding.message == "PyPI : mode hors ligne, et flask n'est pas dans le cache."
    assert report.oldest_data is None


def test_the_cache_follows_the_options(recorded: Routes, make_tree: MakeTree) -> None:
    """Sans ``cache=``, l'analyse ouvre ``Cache.default()`` (dans les tests, un cache propre
    au test), sauf avec ``cache=False`` dans les options."""
    root = make_tree({"requirements.txt": "flask==2.0.1\n"})
    analyze(root, ScanOptions(cache=False))
    assert Cache.default().get(CacheKind.VERSIONS, "https://pypi.org/simple/flask/") is None
    analyze(root)
    assert Cache.default().get(CacheKind.VERSIONS, "https://pypi.org/simple/flask/") is not None


def test_scan_runs_the_coroutine(recorded: Routes, make_tree: MakeTree) -> None:
    root = make_tree({"requirements.txt": "flask==3.1.3\n"})
    report = engine.scan(LocalSource(root), ScanOptions(cache=False))
    assert report.findings == []
    assert report.options == ScanOptions(cache=False)


def test_inventory_does_not_check(make_tree: MakeTree) -> None:
    report = engine.inventory(LocalSource(make_tree({"requirements.txt": "flask==2.0.1\n"})))
    assert report.options is None and report.scanned_at is None
    assert report.findings == []


@pytest.mark.network
def test_the_real_registries(make_tree: MakeTree) -> None:
    """Bout en bout, sur les vrais PyPI et npm : des constats qui ne bougent plus."""
    root = make_tree(
        {
            "api/requirements.txt": "requests==2.32.0\nflask==2.0.1\n",
            "web/package.json": json.dumps({"dependencies": {"request": "2.88.0"}}),
        }
    )
    report = engine.scan(LocalSource(root), ScanOptions(cache=False))
    api, web = report.projects
    assert by_name(api.findings) == {
        "requests": [FindingKind.YANKED, FindingKind.OUTDATED],
        "flask": [FindingKind.OUTDATED],
    }
    assert api.findings[0].target_version == "2.32.2"
    assert by_name(web.findings) == {"request": [FindingKind.DEPRECATED, FindingKind.OUTDATED]}
