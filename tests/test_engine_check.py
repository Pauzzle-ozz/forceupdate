"""Le moteur qui vérifie : registres, constats, événements, options. Hors ligne, sur les
réponses enregistrées (fixture ``recorded``)."""

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
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
VULNS_CHECKED = EventKind.VULNERABILITIES_CHECKED

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
    assert len(checked) == 7  # local-lib n'est pas demandé
    # Plus une étape pour les failles, cherchées en même temps que les paquets.
    steps = [e for e in events if e.kind in (EventKind.PACKAGE_CHECKED, VULNS_CHECKED)]
    assert events[2].total == len(steps) == 8
    assert [event.done for event in steps] == list(range(1, 9))
    assert sum(1 for event in steps if event.kind is VULNS_CHECKED) == 1
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
    assert [f.kind for f in report.findings] == [FindingKind.INCONCLUSIVE] * 2
    assert [f.message for f in report.findings] == [
        "PyPI : mode hors ligne, et flask n'est pas dans le cache.",
        "Failles non vérifiées. OSV : mode hors ligne, sans réponse en cache.",
    ]
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
    """Bout en bout, sur les vrais PyPI, npm et OSV : des constats qui ne bougent plus. De
    nouvelles failles peuvent s'ajouter à celles-ci, jamais les remplacer."""
    root = make_tree(
        {
            "api/requirements.txt": "requests==2.32.0\nflask==2.0.1\n",
            "web/package.json": json.dumps({"dependencies": {"request": "2.88.0"}}),
        }
    )
    report = engine.scan(LocalSource(root), ScanOptions(cache=False))
    api, web = report.projects
    others = [f for f in api.findings if f.kind is not FindingKind.VULNERABLE]
    assert by_name(others) == {
        "requests": [FindingKind.YANKED, FindingKind.OUTDATED],
        "flask": [FindingKind.OUTDATED],
    }
    assert others[0].target_version == "2.32.2"
    assert ("CVE-2023-30861", "2.2.5") in vulnerabilities(api.findings, "flask")
    assert ("CVE-2024-47081", "2.32.4") in vulnerabilities(api.findings, "requests")
    # request est déprécié, et sa faille SSRF n'a jamais été corrigée.
    assert ("CVE-2023-28155", None) in vulnerabilities(web.findings, "request")
    others = [f for f in web.findings if f.kind is not FindingKind.VULNERABLE]
    assert by_name(others) == {"request": [FindingKind.DEPRECATED, FindingKind.OUTDATED]}
    assert FindingKind.INCONCLUSIVE not in {f.kind for f in report.findings}


# -- failles (OSV) -------------------------------------------------------------

VULNERABLE = Path(__file__).parent / "projects" / "vulnerable"
"""Le mini-projet du critère de fin de E08 : lodash 4.17.15, flask 0.12 et ses dépendances de
fin 2018 (``requirements.txt`` compilé par uv)."""


def vulnerabilities(findings: list[Finding], name: str) -> list[tuple[str, str | None]]:
    """Les failles de ``name`` : premier identifiant et version corrigée."""
    return [
        (f.identifiers[0], f.target_version)
        for f in findings
        if f.kind is FindingKind.VULNERABLE and f.dependency and f.dependency.name == name
    ]


def test_the_vulnerable_mini_project(recorded: Routes) -> None:
    """Le critère de fin de E08 : les CVE attendues, avec la bonne version corrigée."""
    report = analyze(VULNERABLE, cache=Cache.disabled())
    (project,) = report.projects
    findings = project.findings
    assert sorted(vulnerabilities(findings, "lodash")) == [
        ("CVE-2020-28500", "4.17.21"),
        ("CVE-2020-8203", "4.17.19"),
        ("CVE-2021-23337", "4.17.21"),
        ("CVE-2025-13465", "4.17.23"),
        ("CVE-2026-2950", "4.18.0"),
        ("CVE-2026-4800", "4.18.0"),
    ]
    assert sorted(vulnerabilities(findings, "flask")) == [
        ("CVE-2018-1000656", "0.12.3"),
        ("CVE-2019-1010083", "1.0"),
        ("CVE-2023-30861", "2.2.5"),
        ("CVE-2026-27205", "3.1.3"),
    ]
    # Les indirectes aussi, sans --transitive : jinja2 2.10 et werkzeug 0.14.1.
    assert ("CVE-2019-10906", "2.10.1") in vulnerabilities(findings, "jinja2")
    assert len(vulnerabilities(findings, "jinja2")) == 6
    assert len(vulnerabilities(findings, "werkzeug")) == 12
    for name in ("click", "itsdangerous", "markupsafe"):
        assert vulnerabilities(findings, name) == []
    # Les failles d'abord, les plus graves en tête.
    assert findings[0].kind is FindingKind.VULNERABLE
    assert findings[0].severity is Severity.HIGH
    assert FindingKind.INCONCLUSIVE not in {f.kind for f in findings}
    # Une requête querybatch pour les 7 versions utilisées, une autre pour toutes les versions
    # proposées (E10), et chaque avis demandé une fois.
    assert recorded["osv:querybatch"].call_count == 2
    first, second = (json.loads(call.request.content) for call in recorded["osv:querybatch"].calls)
    assert len(first["queries"]) == 7
    proposed = {(q["package"]["name"], q["version"]) for q in second["queries"]}
    assert {("lodash", "4.18.1"), ("flask", "0.12.5"), ("werkzeug", "3.1.9")} <= proposed
    assert recorded["osv:GHSA-35jh-r3h4-6jhm"].call_count == 1
    # Les registres sont interrogés pour les directes, et pour les indirectes en faille (pour
    # choisir la version qui corrige) ; une seule fois chacune.
    for name in ("lodash", "flask", "jinja2", "werkzeug"):
        assert recorded[name].call_count == 1


def test_the_plan_of_the_vulnerable_mini_project(recorded: Routes) -> None:
    """Le critère de fin de E09, de bout en bout : la sélection par défaut."""
    report = analyze(VULNERABLE, cache=Cache.disabled())
    (project,) = report.projects
    updates = {update.name: update for update in project.updates}
    assert sorted(updates) == ["flask", "jinja2", "lodash", "werkzeug"]
    # lodash : 4.18.0 corrige tout mais est dépréciée ; la mineure 4.18.1, pré-cochée.
    lodash = updates["lodash"]
    assert [(o.version, o.gap) for o in lodash.options] == [
        ("4.17.23", Gap.PATCH),
        ("4.18.1", Gap.MINOR),
    ]
    assert lodash.selected == "4.18.1"
    assert len(lodash.options[1].fixes) == 6
    edit = lodash.options[1].edits[0]
    assert (edit.file, edit.old, edit.new) == ("package.json", "4.17.15", "4.18.1")
    assert lodash.options[1].lockfile == "package-lock.json"
    # flask : le correctif pré-coché ; la majeure qui corrige tout, proposée sans être cochée.
    flask = updates["flask"]
    assert [(o.version, o.gap) for o in flask.options] == [
        ("0.12.5", Gap.PATCH),
        ("3.1.3", Gap.MAJOR),
    ]
    assert flask.selected == "0.12.5"
    major = flask.options[1]
    assert len(major.fixes) == 4
    assert major.warnings == ("Majeure : peut demander d'adapter le code.",)
    assert [(e.file, e.old, e.new) for e in major.edits] == [
        ("requirements.in", "==0.12", "==3.1.3")
    ]
    assert major.lockfile == "requirements.txt"
    # Les indirectes : le lockfile seul.
    jinja2 = updates["jinja2"]
    assert not jinja2.direct
    assert jinja2.selected == "2.11.3"
    assert all(o.edits == () and o.lockfile == "requirements.txt" for o in jinja2.options)
    assert updates["werkzeug"].selected is None  # seule une majeure corrige
    assert [o.version for o in updates["werkzeug"].options] == ["3.1.9"]


def test_vulnerabilities_follow_no_dev(recorded: Routes, make_tree: MakeTree) -> None:
    root = make_tree({"package.json": json.dumps({"devDependencies": {"lodash": "4.17.15"}})})
    assert len(vulnerabilities(analyze(root, cache=Cache.disabled()).findings, "lodash")) == 6
    report = analyze(root, ScanOptions(dev=False), cache=Cache.disabled())
    assert report.findings == []
    # Les deux requêtes de la première analyse (versions utilisées, puis proposées) ; la
    # seconde ne demande rien.
    assert recorded["osv:querybatch"].call_count == 2


def test_every_installed_version_of_an_npm_package(recorded: Routes, make_tree: MakeTree) -> None:
    """lodash à jour en direct, mais 4.17.15 imbriqué sous un autre paquet : celle-là aussi."""
    lock = {
        "name": "web",
        "lockfileVersion": 3,
        "packages": {
            "": {"name": "web", "dependencies": {"lodash": "^4.17.21", "old": "1.0.0"}},
            "node_modules/lodash": {"version": "4.17.21"},
            "node_modules/old": {"version": "1.0.0", "dependencies": {"lodash": "4.17.15"}},
            "node_modules/old/node_modules/lodash": {"version": "4.17.15"},
        },
    }
    root = make_tree(
        {
            "package.json": json.dumps({"dependencies": {"lodash": "^4.17.21", "old": "1.0.0"}}),
            "package-lock.json": json.dumps(lock),
        }
    )
    report = analyze(root, cache=Cache.disabled())
    found = [f for f in report.findings if f.kind is FindingKind.VULNERABLE]
    assert len(found) == 6
    assert {(f.dependency.direct, f.current_version) for f in found if f.dependency} == {
        (False, "4.17.15")
    }
    body = json.loads(recorded["osv:querybatch"].calls[0].request.content)
    asked = sorted((q["package"]["name"], q["version"]) for q in body["queries"])
    assert asked == [("lodash", "4.17.15"), ("lodash", "4.17.21"), ("old", "1.0.0")]


def test_a_malicious_package_is_a_critical_vulnerability(
    recorded: Routes, make_tree: MakeTree
) -> None:
    """crossenv, retiré par npm : plus seulement un paquet déprécié (E07)."""
    root = make_tree({"package.json": json.dumps({"dependencies": {"crossenv": "1.0.0"}})})
    report = analyze(root, cache=Cache.disabled())
    assert [(f.kind, f.severity) for f in report.findings][:2] == [
        (FindingKind.VULNERABLE, Severity.CRITICAL),
        (FindingKind.DEPRECATED, Severity.LOW),
    ]
    assert report.findings[0].message.startswith("Code malveillant (CVE-2017-16074")


def test_osv_unreachable_is_never_no_vulnerability(recorded: Routes) -> None:
    """Les directes ont un constat « non concluant » ; les indirectes, une remarque."""
    recorded["osv:querybatch"].mock(side_effect=httpx.ConnectError("refusé"))
    report = analyze(VULNERABLE, cache=Cache.disabled())
    (project,) = report.projects
    error = "OSV : api.osv.dev injoignable (ConnectError)."
    inconclusive = [f for f in project.findings if f.kind is FindingKind.INCONCLUSIVE]
    assert sorted((f.dependency.name, f.message) for f in inconclusive if f.dependency) == [
        ("flask", f"Failles non vérifiées. {error}"),
        ("lodash", f"Failles non vérifiées. {error}"),
    ]
    assert FindingKind.VULNERABLE not in {f.kind for f in project.findings}
    # Les versions proposées (flask et lodash sont dépassées) ne sont pas vérifiées non plus :
    # une remarque, et leurs options ne changent pas.
    assert [(n.file, n.message) for n in project.notices] == [
        ("requirements.txt", f"Failles non vérifiées pour 5 dépendances indirectes. {error}"),
        ("requirements.in", f"Failles non vérifiées pour 4 versions proposées. {error}"),
    ]
    assert all(not o.introduced for u in project.updates for o in u.options)


def test_offline_vulnerabilities_come_from_the_cache(recorded: Routes, tmp_path: Path) -> None:
    disk = Cache(tmp_path / "c.sqlite3")
    online = analyze(VULNERABLE, cache=disk)
    recorded["osv:querybatch"].reset()
    offline = analyze(VULNERABLE, ScanOptions(offline=True), cache=disk)
    disk.close()
    assert recorded["osv:querybatch"].call_count == 0
    assert [f.message for f in offline.findings] == [f.message for f in online.findings]
    assert offline.oldest_data is not None

    empty = analyze(VULNERABLE, ScanOptions(offline=True), cache=Cache.disabled())
    (project,) = empty.projects
    assert FindingKind.VULNERABLE not in {f.kind for f in project.findings}
    assert [n.message for n in project.notices] == [
        "Failles non vérifiées pour 5 dépendances indirectes. OSV : mode hors ligne, sans "
        "réponse en cache."
    ]
