"""La configuration d'un projet (E29) : ``forceupdate.toml`` ou ``[tool.forceupdate]``, ce qu'elle
change à l'analyse (paquets et versions ignorés, dossiers exclus, dossiers de tests) et au plan
(sélection par défaut). Hors ligne, sur les réponses enregistrées."""

import asyncio
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import respx

from forceupdate import config, engine
from forceupdate.config import IgnoreRule
from forceupdate.models import (
    Configuration,
    Dependency,
    Ecosystem,
    FindingKind,
    Gap,
    Report,
    ScanOptions,
    SelectionRule,
)
from forceupdate.net import Cache, HttpClient
from forceupdate.registries import PackageInfo, PackageVersion
from forceupdate.sources.local import LocalSource
from forceupdate.update import planner
from forceupdate.versions import InvalidVersion, for_ecosystem

MakeTree = Callable[..., Path]
Routes = dict[str, respx.Route]

VULNERABLE = Path(__file__).parent / "projects" / "vulnerable"


def read(files: dict[str, str]) -> Configuration | None:
    return config.read(files.get)


# ---------------------------------------------------------------------------
# Lire
# ---------------------------------------------------------------------------


def test_a_full_configuration() -> None:
    found = read(
        {
            "forceupdate.toml": """
ignore = ["lodash", "@types/*", "django@>=5"]
exclude = ["legacy/", "./packages/*/examples"]
include-tests = true

[selection]
level = "patch"
security-only = false

[selection.npm]
security-only = true

[selection.rust]
level = "major"
"""
        }
    )
    assert found == Configuration(
        file="forceupdate.toml",
        ignore=("lodash", "@types/*", "django@>=5"),
        exclude=("legacy", "packages/*/examples"),
        include_tests=True,
        selection=(
            SelectionRule(level=Gap.PATCH, security_only=False),
            SelectionRule(ecosystem=Ecosystem.NPM, security_only=True),
            SelectionRule(ecosystem=Ecosystem.CRATES_IO, level=Gap.MAJOR),
        ),
    )


def test_no_configuration() -> None:
    assert read({}) is None
    assert read({"pyproject.toml": "[project]\nname = 'x'\n"}) is None
    assert read({"pyproject.toml": "pas du toml ["}) is None  # le parseur Python le dit déjà


def test_the_table_of_pyproject() -> None:
    found = read(
        {
            "pyproject.toml": """
[project]
name = "app"

[tool.forceupdate]
ignore = ["requests@<2.30"]
selection = { level = "major" }
inconnue = 1
"""
        }
    )
    assert found is not None
    assert found.file == "pyproject.toml"
    assert found.ignore == ("requests@<2.30",)
    assert found.selection == (SelectionRule(level=Gap.MAJOR),)
    assert found.problems == (
        "pyproject.toml : tool.forceupdate.inconnue : clé inconnue, ignorée.",
    )


def test_forceupdate_toml_wins_over_pyproject() -> None:
    found = read(
        {
            "forceupdate.toml": 'ignore = ["a"]\n',
            "pyproject.toml": '[tool.forceupdate]\nignore = ["b"]\n',
        }
    )
    assert found is not None
    assert found.ignore == ("a",)
    assert found.problems == (
        "pyproject.toml : [tool.forceupdate] n'est pas lue : forceupdate.toml prime.",
    )


def test_a_bom_is_not_an_error() -> None:
    found = read({"forceupdate.toml": chr(0xFEFF) + 'ignore = ["a"]\n'})
    assert found is not None and found.ignore == ("a",) and not found.problems


def test_problems_are_said_and_the_value_dropped() -> None:
    found = read(
        {
            "forceupdate.toml": """
ignore = ["ok", "deux mots", "x@>=", 3]
exclude = "/absolu"
include-tests = "oui"
cache = false

[selection]
level = "mineur"

[selection.cobol]
level = "patch"

[selection.go]
level = "minor"
autre = 1
"""
        }
    )
    assert found is not None
    assert found.ignore == ("ok",)
    assert found.exclude == ()
    assert found.include_tests is False
    assert found.selection == (SelectionRule(ecosystem=Ecosystem.GO, level=Gap.MINOR),)
    problems = "\n".join(found.problems)
    assert "forceupdate.toml : ignore[1] : « deux mots »" in problems
    assert "ignore[2] : « x@>= » : « >= » n'est pas une comparaison" in problems
    assert "ignore[3] : « 3 » : une chaîne non vide est attendue." in problems
    assert "exclude[0] : « /absolu » : un dossier relatif" in problems
    assert "include-tests : « oui » n'est pas true ou false." in problems
    assert "cache : clé inconnue, ignorée." in problems
    assert "selection.level : « mineur » n'est pas patch, minor, major." in problems
    assert "selection.cobol : « cobol » n'est pas un écosystème" in problems
    assert "selection.go.autre : clé inconnue, ignorée." in problems


def test_invalid_toml() -> None:
    found = read({"forceupdate.toml": "ignore = [\n"})
    assert found is not None
    assert found.ignore == ()
    assert found.problems[0].startswith("forceupdate.toml : TOML invalide (")


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("..", "dans le projet"),
        ("a/../../b", "dans le projet"),
        ("C:/projets", "relatif"),
        ("  ", "vide"),
    ],
)
def test_a_refused_folder(text: str, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        config.folder_pattern(text)


def test_excluded_paths() -> None:
    patterns = ["legacy", "packages/*/examples"]
    assert config.is_excluded_path("legacy/package.json", patterns)
    assert config.is_excluded_path("Legacy/a/b/requirements.txt", patterns)
    assert config.is_excluded_path("packages/web/examples/demo/package.json", patterns)
    assert not config.is_excluded_path("legacy2/package.json", patterns)
    assert not config.is_excluded_path("src/legacy.py", ["legacy"])
    assert not config.is_excluded_path("package.json", [])


# ---------------------------------------------------------------------------
# Les règles ignore
# ---------------------------------------------------------------------------


def dependency(name: str, ecosystem: Ecosystem = Ecosystem.NPM) -> Dependency:
    return Dependency(ecosystem=ecosystem, name=name, file="package.json")


@pytest.mark.parametrize(
    ("text", "name", "comparisons"),
    [
        ("lodash", "lodash", ()),
        ("@types/*", "@types/*", ()),
        ("@types/node@>=20", "@types/node", ((">=", "20"),)),
        ("django@>=5", "django", ((">=", "5"),)),
        ("requests @ <3, >=2.30", "requests", (("<", "3"), (">=", "2.30"))),
        ("flask@2.0.1", "flask", (("==", "2.0.1"),)),
        ("flask@=2.0.1", "flask", (("==", "2.0.1"),)),
        ("org.apache:log4j@<2.17", "org.apache:log4j", (("<", "2.17"),)),
    ],
)
def test_a_rule(text: str, name: str, comparisons: tuple[tuple[str, str], ...]) -> None:
    rule = IgnoreRule.parse(text, "forceupdate.toml")
    assert (rule.name, rule.comparisons) == (name, comparisons)
    assert rule.whole is (not comparisons)
    assert rule.label == f"{text.strip()} (forceupdate.toml)"


@pytest.mark.parametrize("text", ["", "deux mots", "x@", "x@>=", "x@~1.2", "x@>=1 <2"])
def test_a_refused_rule(text: str) -> None:
    with pytest.raises(ValueError):
        IgnoreRule.parse(text)


def test_a_rule_matches_names() -> None:
    assert IgnoreRule.parse("Lodash").matches(dependency("lodash"))
    assert IgnoreRule.parse("@types/*").matches(dependency("@types/node"))
    assert not IgnoreRule.parse("@types/*").matches(dependency("types"))
    # PyPI : les noms selon PEP 503.
    assert IgnoreRule.parse("Foo_Bar.baz").matches(dependency("foo-bar-baz", Ecosystem.PYPI))
    assert not IgnoreRule.parse("Foo_Bar").matches(dependency("foo-bar", Ecosystem.NPM))


@pytest.mark.parametrize(
    ("ecosystem", "text", "version", "covered"),
    [
        (Ecosystem.NPM, "x@>=5", "5.0.0", True),
        (Ecosystem.NPM, "x@>=5", "4.17.21", False),
        (Ecosystem.NPM, "x@>=5", "6.0.0-beta.1", True),
        (Ecosystem.NPM, "x@>=5", "5.0.0-beta.1", False),
        (Ecosystem.NPM, "x@<4.18,>=4.17.20", "4.17.21", True),
        (Ecosystem.NPM, "x@<4.18,>=4.17.20", "4.18.0", False),
        (Ecosystem.PYPI, "x@>=2", "2.0.1", True),
        (Ecosystem.PYPI, "x@==1.0", "1.0.0", True),
        (Ecosystem.PYPI, "x@>1.0", "1.0", False),
        (Ecosystem.GO, "x@>=2", "v2.1.0", True),
        (Ecosystem.GO, "x@>=v2", "v1.9.9", False),
        (Ecosystem.MAVEN, "x@>=2.17", "2.17.1", True),
        (Ecosystem.NUGET, "x@<13", "12.0.3", True),
        (Ecosystem.RUBYGEMS, "x@>=7", "7.1.3", True),
        (Ecosystem.CRATES_IO, "x@>=1", "0.9.0", False),
        (Ecosystem.PACKAGIST, "x@<3", "2.4.1", True),
    ],
)
def test_a_rule_covers_versions(
    ecosystem: Ecosystem, text: str, version: str, covered: bool
) -> None:
    rule = IgnoreRule.parse(text)
    assert rule.covers(for_ecosystem(ecosystem), version) is covered


def test_an_unreadable_bound() -> None:
    with pytest.raises(InvalidVersion):
        IgnoreRule.parse("x@>=abc").covers(for_ecosystem(Ecosystem.NPM), "1.0.0")


def info(versions: list[str], *, latest: str, tags: dict[str, str] | None = None) -> PackageInfo:
    return PackageInfo(
        ecosystem=Ecosystem.NPM,
        name="lodash",
        versions=tuple(PackageVersion(version=v) for v in versions),
        latest=latest,
        tags=tags or {},
        fetched_at=datetime(2026, 11, 2, tzinfo=UTC),
    )


def test_ignored_versions_are_removed_but_the_used_one() -> None:
    published = info(
        ["4.17.15", "4.17.21", "5.0.0", "5.1.0", "6.0.0-beta.1"],
        latest="5.1.0",
        tags={"latest": "5.1.0", "next": "6.0.0-beta.1", "legacy": "4.17.21"},
    )
    rules = [IgnoreRule.parse("lodash@>=5", "forceupdate.toml")]
    filtered = config.without_ignored(published, dependency("lodash"), rules, used={"5.0.0"})
    assert [v.version for v in filtered.info.versions] == ["4.17.15", "4.17.21", "5.0.0"]
    assert filtered.info.latest == "5.0.0"
    assert filtered.info.tags == {"legacy": "4.17.21", "latest": "5.0.0"}
    assert filtered.removed == {"lodash@>=5 (forceupdate.toml)": 2}
    assert filtered.unreadable == ()


def test_rules_that_do_not_apply() -> None:
    published = info(["1.0.0", "2.0.0"], latest="2.0.0")
    whole = config.without_ignored(
        published, dependency("lodash"), [IgnoreRule.parse("lodash")], ()
    )
    assert whole.info is published  # le paquet entier : pas des versions
    other = config.without_ignored(published, dependency("lodash"), [IgnoreRule.parse("x@>=2")], ())
    assert other.info is published and not other.removed
    bad = config.without_ignored(
        published, dependency("lodash"), [IgnoreRule.parse("lodash@>=abc")], ()
    )
    assert bad.info is published
    assert bad.unreadable == ("lodash@>=abc",)


# ---------------------------------------------------------------------------
# La sélection par défaut
# ---------------------------------------------------------------------------


def test_rules_from_layers() -> None:
    assert planner.rules() == planner.DEFAULT_RULES
    project = [
        SelectionRule(level=Gap.PATCH),
        SelectionRule(ecosystem=Ecosystem.NPM, security_only=True),
    ]
    person = [
        SelectionRule(level=Gap.MAJOR, security_only=False),
        SelectionRule(ecosystem=Ecosystem.PYPI, level=Gap.MAJOR),
        SelectionRule(ecosystem=Ecosystem.NUGET, security_only=True),
    ]
    rules = planner.rules(project, person)
    # La règle générale du projet passe devant toutes celles de la personne.
    assert (rules.level, rules.security_only) == (Gap.PATCH, False)
    assert rules.for_ecosystem(Ecosystem.NPM) == (Gap.PATCH, True)
    assert rules.for_ecosystem(Ecosystem.PYPI) == (Gap.PATCH, False)
    assert rules.for_ecosystem(Ecosystem.NUGET) == (Gap.PATCH, True)
    assert rules.for_ecosystem(Ecosystem.GO) == (Gap.PATCH, False)
    # Sans configuration du projet : celles de la personne.
    alone = planner.rules((), person)
    assert alone.for_ecosystem(Ecosystem.GO) == (Gap.MAJOR, False)
    assert alone.for_ecosystem(Ecosystem.NUGET) == (Gap.MAJOR, True)
    # La ligne de commande passe devant tout ; un champ qu'elle ne dit pas vient d'ailleurs.
    asked = planner.rules([SelectionRule(level=Gap.MINOR)], project, person, include=("a*",))
    assert asked.for_ecosystem(Ecosystem.NPM) == (Gap.MINOR, True)
    assert asked.include == ("a*",)


# ---------------------------------------------------------------------------
# De bout en bout
# ---------------------------------------------------------------------------


async def _no_sleep(_: float) -> None:
    pass


def analyze(root: Path, options: ScanOptions | None = None) -> Report:
    async def main() -> Report:
        async with HttpClient(sleep=_no_sleep) as http:
            return await engine.analyze(
                LocalSource(root), options, http=http, cache=Cache.disabled()
            )

    return asyncio.run(main())


@pytest.fixture
def project(tmp_path: Path) -> Callable[[str], Path]:
    """Une copie de ``vulnerable`` avec ce ``forceupdate.toml``."""

    def make(configuration: str) -> Path:
        root = tmp_path / "vulnerable"
        shutil.copytree(VULNERABLE, root)
        (root / "forceupdate.toml").write_text(configuration, encoding="utf-8")
        return root

    return make


def findings_of(report: Report, name: str) -> list[Any]:
    return [f for f in report.findings if f.dependency is not None and f.dependency.name == name]


def test_an_ignored_package_keeps_its_vulnerabilities(
    recorded: Routes, project: Callable[[str], Path]
) -> None:
    report = analyze(project('ignore = ["lodash"]\n'))
    (found,) = report.projects
    lodash = findings_of(report, "lodash")
    assert lodash and {f.kind for f in lodash} == {FindingKind.VULNERABLE}
    assert "lodash" not in {update.name for update in found.updates}
    (declared,) = [d for d in found.dependencies if d.name == "lodash" and d.direct]
    assert declared.ignored == "lodash (forceupdate.toml)"
    assert recorded["lodash"].call_count == 0  # jamais demandé au registre
    assert any(
        n.file == "package.json"
        and n.message.startswith("Paquet ignoré : lodash (forceupdate.toml).")
        for n in found.notices
    )
    assert "flask" in {update.name for update in found.updates}


def test_ignored_versions_are_never_proposed(
    recorded: Routes, project: Callable[[str], Path]
) -> None:
    report = analyze(project('ignore = ["lodash@>=4.18"]\n'))
    (found,) = report.projects
    (outdated,) = [f for f in findings_of(report, "lodash") if f.kind is FindingKind.OUTDATED]
    assert outdated.target_version == "4.17.23"
    (lodash,) = [u for u in found.updates if u.name == "lodash"]
    assert [o.version for o in lodash.options] == ["4.17.23"]
    assert lodash.selected == "4.17.23"
    notices = [n.message for n in found.notices if n.file == "package.json"]
    assert any(m.startswith("lodash@>=4.18 (forceupdate.toml) : ") for m in notices)


def test_the_rules_of_the_person_add_up(recorded: Routes, project: Callable[[str], Path]) -> None:
    root = project('ignore = ["flask"]\n')
    report = analyze(root, ScanOptions(ignore=("lodash@>=4.18",)))
    (found,) = report.projects
    assert "flask" not in {u.name for u in found.updates}
    (lodash,) = [u for u in found.updates if u.name == "lodash"]
    assert [o.version for o in lodash.options] == ["4.17.23"]
    assert any(m.message.startswith("lodash@>=4.18 (réglages) : ") for m in found.notices)


def test_the_default_selection_of_the_project(
    recorded: Routes, project: Callable[[str], Path]
) -> None:
    report = analyze(
        project('[selection]\nlevel = "patch"\n[selection.pypi]\nlevel = "major"\n'),
        ScanOptions(selection=(SelectionRule(level=Gap.MAJOR, security_only=True),)),
    )
    updates = {u.name: u for u in report.projects[0].updates}
    assert updates["lodash"].selected == "4.17.23"  # correctifs seulement (le projet prime)
    assert updates["flask"].selected == "3.1.3"  # majeures pour PyPI
    assert updates["werkzeug"].selected == "3.1.9"


def test_the_selection_of_the_person(recorded: Routes, tmp_path: Path) -> None:
    root = tmp_path / "vulnerable"
    shutil.copytree(VULNERABLE, root)
    rules = (SelectionRule(ecosystem=Ecosystem.NPM, security_only=True),)
    report = analyze(root, ScanOptions(selection=rules))
    assert report.config is None
    updates = {u.name: u for u in report.projects[0].updates}
    # Failles seulement pour npm : la plus petite version qui corrige le plus.
    assert updates["lodash"].selected == "4.18.1"
    assert updates["flask"].selected == "0.12.5"


def test_excluded_folders_and_test_folders(make_tree: MakeTree, tmp_path: Path) -> None:
    root = make_tree(
        {
            "package.json": '{"name": "app"}',
            "legacy/package.json": '{"name": "old"}',
            "tests/fixture/package.json": '{"name": "fixture"}',
            "legacy/old.py": "print(1)\n",
        }
    )
    plain = engine.inventory(LocalSource(root))
    assert [p.path for p in plain.projects] == [".", "legacy"]
    assert plain.ignored_manifests == ["tests/fixture/package.json"]
    (root / "forceupdate.toml").write_text('exclude = ["legacy"]\ninclude-tests = true\n')
    configured = engine.inventory(LocalSource(root))
    assert [p.path for p in configured.projects] == [".", "tests/fixture"]
    assert configured.ignored_manifests == []
    assert "Python" not in {language.name for language in configured.languages}
    assert configured.config is not None and configured.config.exclude == ("legacy",)


def test_a_manifest_chosen_alone_reads_the_configuration_of_its_folder(make_tree: MakeTree) -> None:
    root = make_tree({"package.json": '{"name": "app"}', "forceupdate.toml": 'ignore = ["a"]\n'})
    report = engine.inventory(LocalSource(root / "package.json"))
    assert report.config is not None and report.config.ignore == ("a",)


def test_the_reports_say_the_configuration(make_tree: MakeTree) -> None:
    from rich.console import Console

    from forceupdate.report import markdown, terminal

    root = make_tree(
        {
            "package.json": '{"name": "app"}',
            "forceupdate.toml": 'ignore = ["a", "b@>=2"]\nexclude = ["x"]\ncache = 1\n',
        }
    )
    report = engine.inventory(LocalSource(root))
    expected = "Configuration du projet : forceupdate.toml (2 règles ignore, 1 dossier exclu)."
    console = Console(record=True, width=200, color_system=None)
    terminal.render(report, console)
    text = console.export_text()
    assert expected in text
    assert "forceupdate.toml : cache : clé inconnue, ignorée." in text
    rendered = markdown.render(report)
    assert markdown.escape(expected) in rendered
    assert f"- {markdown.escape('forceupdate.toml : cache : clé inconnue, ignorée.')}" in rendered


def test_an_ignored_indirect_dependency_is_said_once(make_tree: MakeTree) -> None:
    root = make_tree(
        {
            "requirements.in": "flask==0.12\n",
            "requirements.txt": (
                "flask==0.12\n    # via -r requirements.in\nwerkzeug==0.14.1\n    # via flask\n"
            ),
        }
    )
    report = engine.inventory(LocalSource(root))
    (project,) = report.projects
    config.mark_ignored(
        project, [IgnoreRule.parse("werkzeug", "réglages"), IgnoreRule.parse("flask", "réglages")]
    )
    assert [(n.file, n.message.split(".")[0]) for n in project.notices] == [
        ("requirements.in", "Paquet ignoré : flask (réglages)"),
        ("requirements.txt", "Paquet ignoré : werkzeug (réglages)"),
    ]
    assert {d.name for d in project.dependencies if d.ignored} == {"flask", "werkzeug"}
