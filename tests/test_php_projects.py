"""Le mini-projet PHP de ``tests/projects/`` : ``composer``.

Son ``composer.lock`` a été fait par Composer 2.11 (voir ``tests/projects/README.md``). On y
vérifie l'inventaire, puis l'analyse (réponses enregistrées : fixture ``recorded``), le plan, et
``forceupdate scan`` et ``update`` en ligne de commande (``composer`` simulé)."""

import asyncio
import json
import shutil
from collections.abc import Callable, Iterable
from pathlib import Path

import pytest
import respx
from conftest import FakeTools, ToolCall
from typer.testing import CliRunner

from forceupdate import engine
from forceupdate.cli import app
from forceupdate.models import EditKind, FindingKind, Gap, Project, Report, Scope, UpdateReason
from forceupdate.net import Cache, HttpClient
from forceupdate.parsers.base import REASON_LOCAL
from forceupdate.parsers.php import REASON_BRANCH, parse_composer_json
from forceupdate.sources.local import LocalSource
from forceupdate.versions.composer import COMPOSER

PROJECT = Path(__file__).parent / "projects" / "composer"
GUZZLE, PSR7, TWIG, MONOLOG = "guzzlehttp/guzzle", "guzzlehttp/psr7", "twig/twig", "monolog/monolog"
CONSOLE, LOG, CACHE = "symfony/console", "psr/log", "doctrine/cache"
FACTORY = "php-http/message-factory"
Routes = dict[str, respx.Route]
MakeTree = Callable[..., Path]
runner = CliRunner()


def scan(root: Path) -> list[Project]:
    return engine.inventory(LocalSource(root)).projects


def analyze(root: Path) -> Report:
    async def main() -> Report:
        async with HttpClient() as http:
            return await engine.analyze(LocalSource(root), http=http, cache=Cache.disabled())

    return asyncio.run(main())


def test_every_location_points_at_its_constraint() -> None:
    source = LocalSource(PROJECT)
    (project,) = scan(PROJECT)
    text = source.read_text("composer.json")
    assert text is not None
    located = [d for d in project.dependencies if d.location is not None]
    assert located and all(d.location.extract(text) == d.constraint for d in located)  # type: ignore[union-attr]


def test_the_composer_mini_project() -> None:
    (project,) = scan(PROJECT)  # third_party/acme-tools est écarté (dossier vendorisé)
    assert (project.manifests, project.lockfiles) == (["composer.json"], ["composer.lock"])
    directs = [
        (d.name, d.constraint, d.installed, d.scope) for d in project.dependencies if d.direct
    ]
    assert directs == [
        ("acme/tools", "^1.0", "1.0.0", Scope.RUNTIME),
        (GUZZLE, "7.4.0", "7.4.0", Scope.RUNTIME),
        (MONOLOG, "^2.3", "2.3.5", Scope.RUNTIME),
        (FACTORY, "^1.0", "v1.0.2", Scope.RUNTIME),
        ("psr/container", "dev-master", "dev-master", Scope.RUNTIME),
        (LOG, "^1.1 || ^2.0", "1.1.4", Scope.RUNTIME),
        (CONSOLE, "~5.4", "v5.4.10", Scope.RUNTIME),
        (TWIG, "3.4.*", "v3.4.1", Scope.RUNTIME),
        (CACHE, "^1.12", "1.12.1", Scope.DEV),
    ]
    found = {d.name: d for d in project.dependencies}
    assert found["acme/tools"].unverifiable_reason == REASON_LOCAL
    assert found["psr/container"].unverifiable_reason == REASON_BRANCH
    assert found[MONOLOG].excluded == ("2.11.*",)
    transitives = [(d.name, d.installed) for d in project.dependencies if not d.direct]
    assert (PSR7, "2.1.0") in transitives and len(transitives) == 13
    # php, ext-json et les polyfills remplacés (replace) ne sont pas des dépendances.
    assert not {"php", "ext-json", "symfony/polyfill-php80"} & set(found)
    assert {d.lockfile for d in project.dependencies} == {"composer.lock"}
    assert project.notices == []


def vulnerabilities(project: Project, name: str) -> list[tuple[str, str | None]]:
    return [
        (f.identifiers[0], f.target_version)
        for f in project.findings
        if f.kind is FindingKind.VULNERABLE and f.dependency and f.dependency.name == name
    ]


def messages(project: Project, kind: FindingKind, name: str) -> list[str]:
    return [
        f.message
        for f in project.findings
        if f.kind is kind and f.dependency is not None and f.dependency.name == name
    ]


def test_findings_of_the_composer_mini_project(recorded: Routes) -> None:
    (project,) = analyze(PROJECT).projects
    # Les avis d'OSV pour Packagist écrivent les versions sans le v des étiquettes de twig. Les
    # 17 de « composer audit » : 15 d'OSV, plus deux qui ne viennent que de FriendsOfPHP, lus chez
    # Packagist (E34).
    assert len(vulnerabilities(project, TWIG)) == 17
    assert ("CVE-2022-39261", "3.4.3") in vulnerabilities(project, TWIG)
    assert ("CVE-2026-46627", "3.26.0") in vulnerabilities(project, TWIG)
    assert ("CVE-2026-46636", "3.27.0") in vulnerabilities(project, TWIG)
    assert len(vulnerabilities(project, GUZZLE)) == 13
    assert ("CVE-2022-29248", "7.4.3") in vulnerabilities(project, GUZZLE)
    assert sorted(vulnerabilities(project, PSR7)) == [
        ("CVE-2022-24775", "2.1.1"),
        ("CVE-2023-29197", "2.4.5"),
        ("CVE-2026-48998", "2.10.2"),
        ("CVE-2026-49214", "2.10.2"),
        ("CVE-2026-55766", "2.12.1"),
        ("CVE-2026-59882", "2.12.3"),
    ]
    assert messages(project, FindingKind.DEPRECATED, FACTORY) == [
        "Paquet déprécié : abandonné sur Packagist, remplacé par psr/http-factory."
    ]
    assert messages(project, FindingKind.DEPRECATED, CACHE) == [
        "Paquet déprécié : abandonné sur Packagist, sans remplaçant indiqué."
    ]
    outdated = {
        f.dependency.name: (f.target_version, f.wanted_version, f.gap)
        for f in project.findings
        if f.kind is FindingKind.OUTDATED and f.dependency
    }
    assert outdated[TWIG] == ("v3.30.0", "v3.4.3", Gap.MINOR)  # pas la 4.0.0-alpha1
    assert outdated[GUZZLE] == ("8.3.1", "7.4.0", Gap.MAJOR)
    assert outdated[MONOLOG] == ("3.12.1", "2.10.0", Gap.MAJOR)  # 2.11.* écartées (conflict)
    # ~5.4 : jusqu'à 6.0 ; symfony/console 7 et 8 demandent un PHP plus récent que celui du projet
    # (8.1) : la plus haute qui convient est v6.4.49, comme pour « composer outdated » (E27).
    assert outdated[CONSOLE] == ("v6.4.49", "v5.4.55", Gap.MAJOR)
    assert messages(project, FindingKind.OUTDATED, CONSOLE) == [
        "Version v6.4.49 disponible (majeure) ; utilisée : v5.4.10. La contrainte accepte jusqu'à "
        "v5.4.55. La v8.1.10 n'est pas proposée : elle demande PHP >=8.4.1 ; le projet : 8.1 et "
        "plus (composer.json)."
    ]
    assert outdated[LOG] == ("3.0.2", "2.0.0", Gap.MAJOR)
    assert messages(project, FindingKind.UNVERIFIABLE, "psr/container") == [
        "Non vérifiable : branche de développement."
    ]
    # E27 : PHP 8.1 (config.platform.php) est en fin de vie ; symfony/console 5.4 non (LTS, 2029).
    assert [f.message for f in project.findings if f.kind is FindingKind.EOL] == [
        "PHP 8.1 : fin de vie depuis le 31/12/2025. Lu dans composer.json : config.platform.php "
        '= "8.1.30". Cycle conseillé : 8.5, dernière version 8.5.12.'
    ]


def test_plan_of_the_composer_mini_project(recorded: Routes) -> None:
    (project,) = analyze(PROJECT).projects
    updates = {u.name: u for u in project.updates}
    twig = updates[TWIG]
    assert twig.selected == "v3.30.0"
    option = twig.option("v3.30.0")
    assert option is not None and option.lockfile == "composer.lock"
    (edit,) = option.edits
    assert (edit.kind, edit.file, edit.old, edit.new) == (
        EditKind.DEPENDENCY,
        "composer.json",
        "3.4.*",
        "3.30.*",
    )
    # La correction de CVE-2022-39261 seule est dans le joker : le lockfile seul.
    patch = twig.option("v3.4.3")
    assert patch is not None and patch.edits == () and UpdateReason.LATEST_PATCH in patch.reasons
    # monolog : 2.11.* écartées (conflict), la dernière mineure est 2.10.0, par le lockfile seul.
    monolog = updates[MONOLOG]
    assert [o.version for o in monolog.options] == ["2.10.0", "3.12.1"]  # pas de 2.3.x après 2.3.5
    assert monolog.selected == "2.10.0"
    assert monolog.option("2.10.0").edits == ()  # type: ignore[union-attr]
    (major,) = monolog.option("3.12.1").edits  # type: ignore[union-attr]
    assert (major.old, major.new) == ("^2.3", "^3.12.1")
    # guzzle : une version exacte réécrite ; symfony/console : ~5.4 garde sa précision.
    (edit,) = updates[GUZZLE].option(updates[GUZZLE].selected or "").edits  # type: ignore[union-attr]
    assert (edit.old, edit.new) == ("7.4.0", "7.16.1")
    console = updates[CONSOLE]
    assert console.selected == "v5.4.55"
    assert console.option("v5.4.55").edits == ()  # type: ignore[union-attr]
    assert [o.version for o in console.options] == ["v5.4.55", "v6.4.49"]  # pas de v8.1.10
    (edit,) = console.option("v6.4.49").edits  # type: ignore[union-attr]
    assert (edit.old, edit.new) == ("~5.4", "~6.4")
    # psr7, indirecte en faille : par le lockfile seul.
    psr7 = updates[PSR7]
    assert not psr7.direct and psr7.selected == "2.13.2"
    assert psr7.option("2.13.2").edits == ()  # type: ignore[union-attr]
    assert "acme/tools" not in updates and "psr/container" not in updates


# -- en ligne de commande -------------------------------------------------------------------


def test_scan_of_the_composer_mini_project(recorded: Routes) -> None:
    result = runner.invoke(app, ["scan", str(PROJECT), "--no-cache"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    rows = [line.split() for line in result.stdout.splitlines()]
    assert [TWIG, "3.4.*", "v3.4.1", "v3.4.3", "v3.30.0", "faille,", "mineure"] in rows
    assert [GUZZLE, "7.4.0", "7.4.0", "7.4.0", "8.3.1", "faille,", "majeure"] in rows
    assert [MONOLOG, "^2.3", "2.3.5", "2.10.0", "3.12.1", "majeure"] in rows
    assert [FACTORY, "^1.0", "v1.0.2", "1.1.0", "1.1.0", "déprécié,", "mineure"] in rows
    assert ["acme/tools", "^1.0", "1.0.0", "non", "vérifiable"] in rows


class FakeComposer:
    """``composer update x:V…`` comme le vrai : chaque paquet nommé passe à sa version dans
    ``composer.lock``, s'il est figé et si la contrainte de ``composer.json`` l'accepte ; le
    ``content-hash`` est refait. Il refuse sans ``--no-scripts`` ni ``--no-plugins``, et une
    version à faille (``vulnerable``) si le blocage n'est pas levé."""

    def __init__(self, vulnerable: Iterable[str] = ()) -> None:
        self.vulnerable = set(vulnerable)

    def __call__(self, call: ToolCall) -> tuple[int, str, str] | None:
        if call.arguments == ["--version"]:
            return 0, "Composer version 2.11.0 2026-10-01 12:00:00\n", ""
        if call.arguments[:1] != ["update"]:
            return 2, "", f"commande inattendue : {call.arguments}"
        flags = {a for a in call.arguments if a.startswith("-")}
        if not {"--no-install", "--no-scripts", "--no-plugins", "--with-all-dependencies"} <= flags:
            return 2, "", "le projet aurait lancé ses scripts ou ses plugins"
        specs = [a for a in call.arguments[1:] if not a.startswith("-")]
        root = call.cwd
        constraints = {
            d.name: d.constraint
            for d in parse_composer_json(
                "composer.json", (root / "composer.json").read_text(encoding="utf-8")
            )
        }
        lock = json.loads((root / "composer.lock").read_text(encoding="utf-8"))
        entries = {p["name"]: p for p in lock["packages"] + lock["packages-dev"]}
        for spec in specs:
            name, _, version = spec.partition(":")
            if name not in entries:
                return 2, "", f"Package {name} not found"
            if name in constraints and not COMPOSER.satisfies(constraints[name], version):
                return 2, "", f"Root composer.json requires {name} {constraints[name]}"
            blocked = call.env.get("COMPOSER_POLICY_ADVISORIES_BLOCK") != "0"
            if blocked and spec in self.vulnerable:
                return 2, "", f"{name}[{version}] affected by security advisories"
            entries[name]["version"] = version
        lock["content-hash"] = "nouveau"
        (root / "composer.lock").write_text(json.dumps(lock, indent=4) + "\n", encoding="utf-8")
        return None


def fake_composer(fake_tools: Callable[..., FakeTools], **options: set[str]) -> FakeTools:
    tools = fake_tools("composer")
    tools.handlers["composer"] = FakeComposer(**options)
    return tools


def test_update_of_the_composer_mini_project(
    recorded: Routes, tmp_path: Path, fake_tools: Callable[..., FakeTools]
) -> None:
    root = tmp_path / "composer"
    shutil.copytree(PROJECT, root)
    tools = fake_composer(fake_tools, vulnerable={f"{TWIG}:v3.4.3"})
    result = runner.invoke(
        app,
        ["update", str(root), "--yes", *("--include", TWIG, "--include", MONOLOG), "--no-cache"],
        env={"COLUMNS": "200"},
    )
    assert result.exit_code == 0, result.output
    lines = [line.split() for line in result.stdout.splitlines()]
    start = lines.index(["Fichiers", "réécrits", ":", "composer.json."])
    assert lines[start + 1 : start + 4] == [
        ["composer.lock", ":", "régénéré", "(Composer)."],
        [TWIG, "v3.30.0"],
        [MONOLOG, "2.10.0"],
    ]
    (version, call) = tools.calls
    assert version.arguments == ["--version"]
    assert call.cwd == root
    assert call.arguments[:3] == ["update", f"{TWIG}:v3.30.0", f"{MONOLOG}:2.10.0"]
    assert {"--ignore-platform-req=ext-*", "--no-interaction"} <= set(call.arguments)
    assert (call.env["COMPOSER_MINIMAL_CHANGES"], call.env["COMPOSER_NO_AUDIT"]) == ("1", "1")
    assert call.env["COMPOSER_POLICY_ADVISORIES_BLOCK"] == "0"
    manifest = (root / "composer.json").read_text(encoding="utf-8")
    assert '"twig/twig": "3.30.*"' in manifest and '"monolog/monolog": "^2.3"' in manifest
    lock = json.loads((root / "composer.lock").read_text(encoding="utf-8"))
    versions = {p["name"]: p["version"] for p in lock["packages"]}
    assert (versions[TWIG], versions[MONOLOG]) == ("v3.30.0", "2.10.0")
    assert not (root / "script-ran.txt").exists()


@pytest.mark.parametrize(
    "config",
    [
        {"policy": {"advisories": {"block": True}}},
        {"policy": False},
        {"audit": {"block-insecure": True}},
    ],
)
def test_the_blocking_set_by_the_project_is_kept(
    recorded: Routes, tmp_path: Path, fake_tools: Callable[..., FakeTools], config: dict
) -> None:
    root = tmp_path / "composer"
    shutil.copytree(PROJECT, root)
    data = json.loads((root / "composer.json").read_text(encoding="utf-8"))
    data["config"].update(config)
    (root / "composer.json").write_text(json.dumps(data, indent=4), encoding="utf-8")
    tools = fake_composer(fake_tools, vulnerable={f"{TWIG}:v3.4.3"})
    result = runner.invoke(
        app,
        ["update", str(root), "--yes", "--include", TWIG, "--level", "patch", "--no-cache"],
        env={"COLUMNS": "200"},
    )
    assert result.exit_code == 2, result.output
    (version, call) = tools.calls
    assert version.arguments == ["--version"]
    assert "COMPOSER_POLICY_ADVISORIES_BLOCK" not in call.env
    output = " ".join(result.stdout.split())
    assert "Composer ne refuse pas" not in output  # le plan ne dit pas le blocage levé
    assert "composer.lock : échec de Composer." in output
    assert "twig/twig[v3.4.3] affected by security advisories" in output
    assert json.loads((root / "composer.lock").read_text("utf-8")) == json.loads(
        (PROJECT / "composer.lock").read_text("utf-8")
    )


def test_minimum_stability_gives_the_allowed_version(make_tree: MakeTree, recorded: Routes) -> None:
    """E34 : la version permise suit minimum-stability et prefer-stable, comme composer update
    (twig/twig enregistré : v4.0.0-alpha1 au-dessus de v3.30.0)."""
    lock = {"packages": [{"name": "twig/twig", "version": "v3.4.1"}], "packages-dev": []}
    for settings, wanted in (
        ({"minimum-stability": "alpha"}, "v4.0.0-alpha1"),
        ({"minimum-stability": "alpha", "prefer-stable": True}, "v3.30.0"),
        ({}, "v3.30.0"),
    ):
        composer = {"require": {"twig/twig": ">=3.0"}, **settings}
        root = make_tree(
            {"composer.json": json.dumps(composer), "composer.lock": json.dumps(lock)},
            root=make_tree({}) / str(len(settings)),
        )
        (project,) = analyze(root).projects
        (finding,) = [f for f in project.findings if f.kind is FindingKind.OUTDATED]
        assert finding.wanted_version == wanted
        assert finding.target_version == "v3.30.0"  # forceupdate ne propose que des stables
