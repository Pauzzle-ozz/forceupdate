"""Les mini-projets Go de ``tests/projects/`` : ``go`` (un module) et ``go-workspace``.

Leurs ``go.sum`` (et ``go.work.sum``) ont été faits par Go 1.27.3 (voir
``tests/projects/README.md``). On y vérifie l'inventaire, puis l'analyse (réponses enregistrées :
fixture ``recorded``), le plan, et ``forceupdate scan`` et ``update`` en ligne de commande (``go``
simulé)."""

import asyncio
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
import respx
from conftest import FakeTools, ToolCall
from typer.testing import CliRunner

from forceupdate import engine
from forceupdate.cli import app
from forceupdate.models import (
    Ecosystem,
    EditKind,
    FindingKind,
    Gap,
    Project,
    Report,
    UpdateReason,
)
from forceupdate.net import Cache, HttpClient
from forceupdate.parsers.base import REASON_LOCAL
from forceupdate.parsers.go import parse_go_mod
from forceupdate.sources.local import LocalSource
from forceupdate.update import planner

PROJECTS = Path(__file__).parent / "projects"
GO, WORKSPACE = PROJECTS / "go", PROJECTS / "go-workspace"
JWT, CHI, TEXT = "github.com/golang-jwt/jwt/v4", "github.com/go-chi/chi", "golang.org/x/text"
TOML, UUID, YAML = "github.com/BurntSushi/toml", "github.com/google/uuid", "gopkg.in/yaml.v3"
YAML_PSEUDO = "v3.0.0-20200313102051-9f266ea9e77c"
Routes = dict[str, respx.Route]
runner = CliRunner()


def scan(root: Path) -> dict[str, Project]:
    return {project.path: project for project in engine.inventory(LocalSource(root)).projects}


def analyze(root: Path) -> Report:
    async def main() -> Report:
        async with HttpClient() as http:
            return await engine.analyze(LocalSource(root), http=http, cache=Cache.disabled())

    return asyncio.run(main())


@pytest.mark.parametrize("root", [GO, WORKSPACE], ids=["go", "go-workspace"])
def test_every_location_points_at_its_constraint(root: Path) -> None:
    source = LocalSource(root)
    located = 0
    for project in engine.inventory(source).projects:
        for dependency in project.dependencies:
            if dependency.location is not None:
                text = source.read_text(dependency.file)
                assert text is not None
                assert dependency.location.extract(text) == dependency.constraint, dependency
                located += 1
    assert located > 0


def test_the_go_mini_project() -> None:
    (project,) = scan(GO).values()  # third_party/localmod est écarté (dossier vendorisé)
    assert (project.manifests, project.lockfiles) == (["go.mod"], ["go.sum"])
    assert [(d.name, d.constraint, d.installed, d.direct) for d in project.dependencies] == [
        ("example.com/forceupdate/localmod", "v0.0.0", None, True),
        (TOML, "v1.2.0", "v1.2.0", True),
        (CHI, "v1.5.4", "v1.5.4", True),
        (JWT, "v4.4.0", "v4.4.0", True),
        (UUID, "v1.4.0", "v1.4.0", True),  # replace github.com/google/uuid => … v1.4.0
        ("github.com/stretchr/testify", "v1.7.0", "v1.7.0", True),
        (TEXT, "v0.3.7", "v0.3.7", True),
        ("github.com/davecgh/go-spew", "v1.1.0", "v1.1.0", False),
        ("github.com/pmezard/go-difflib", "v1.0.0", "v1.0.0", False),
        (YAML, YAML_PSEUDO, YAML_PSEUDO, False),
    ]
    found = {d.name: d for d in project.dependencies}
    assert found["example.com/forceupdate/localmod"].unverifiable_reason == REASON_LOCAL
    assert found[TOML].excluded == ("v1.6.0",)
    assert {d.lockfile for d in project.dependencies if d.verifiable} == {"go.sum"}
    assert all(d.file == "go.mod" for d in project.dependencies)
    assert project.notices == []
    # go.sum n'est pas une source de versions : il garde aussi gopkg.in/check.v1, qu'aucun paquet
    # du module n'utilise, et objx.
    go_sum = (GO / "go.sum").read_text(encoding="utf-8")
    assert "gopkg.in/check.v1" in go_sum and "gopkg.in/check.v1" not in found


def test_the_go_workspace_mini_project() -> None:
    projects = scan(WORKSPACE)
    assert sorted(projects) == [".", "app", "lib", "tools"]
    root = projects["."]
    assert (root.manifests, root.lockfiles, root.dependencies) == (
        ["go.work"],
        ["go.work.sum"],
        [],
    )
    app_, lib, tools = projects["app"], projects["lib"], projects["tools"]
    summary = [(d.name, d.constraint, d.direct, d.file, d.lockfile) for d in app_.dependencies]
    assert summary == [
        ("example.com/ws/lib", "v0.0.0", True, "app/go.mod", None),  # replace … => ../lib
        (UUID, "v1.3.0", True, "app/go.mod", "app/go.sum"),
        (TEXT, "v0.3.8", False, "go.work", None),  # le replace de go.work l'emporte
    ]
    assert [(d.name, d.constraint, d.file) for d in lib.dependencies] == [
        (TEXT, "v0.3.8", "go.work")
    ]
    # tools n'est pas dans « use » : hors du workspace, sa propre version.
    assert [(d.name, d.constraint, d.lockfile) for d in tools.dependencies] == [
        (UUID, "v1.2.0", "tools/go.sum")
    ]
    assert all(not p.notices for p in projects.values())


def findings(project: Project, kind: FindingKind, name: str) -> list[str]:
    return [
        f.message
        for f in project.findings
        if f.kind is kind and f.dependency is not None and f.dependency.name == name
    ]


def vulnerabilities(project: Project, name: str) -> list[tuple[str, str | None]]:
    return [
        (f.identifiers[0], f.target_version)
        for f in project.findings
        if f.kind is FindingKind.VULNERABLE and f.dependency and f.dependency.name == name
    ]


def test_findings_of_the_go_mini_project(recorded: Routes) -> None:
    (project,) = analyze(GO).projects
    assert vulnerabilities(project, JWT) == [
        ("CVE-2025-30204", "v4.5.2"),
        ("CVE-2024-51744", "v4.5.1"),
    ]
    # Les avis Go écrivent 0.3.8 : la version corrigée reprend son « v ».
    assert vulnerabilities(project, TEXT) == [
        ("CVE-2022-32149", "v0.3.8"),
        ("CVE-2026-56851", "v0.41.0"),
        ("CVE-2026-56852", "v0.39.0"),
    ]
    assert vulnerabilities(project, YAML) == [("CVE-2022-28948", "v3.0.1")]
    # chi v1 : corrigée seulement sous chi/v5, un autre module.
    assert vulnerabilities(project, CHI) == [("CVE-2025-69725", None)]
    (chi_vuln,) = findings(project, FindingKind.VULNERABLE, CHI)
    assert chi_vuln.endswith(
        "Aucune version corrigée sous ce nom ; corrigée sous un autre module : "
        "github.com/go-chi/chi/v5 v5.2.4."
    )
    assert findings(project, FindingKind.YANKED, JWT) == [
        "Version v4.4.0 retirée par l'auteur du module (retract) : Contains a backwards "
        "incompatible change to the Claims interface. La plus proche non retirée : v4.4.1."
    ]
    assert findings(project, FindingKind.DEPRECATED, CHI) == [
        "Paquet déprécié : Please upgrade to the latest major version: go get "
        "github.com/go-chi/chi/v5"
    ]
    outdated = {
        f.dependency.name: (f.target_version, f.wanted_version, f.gap)
        for f in project.findings
        if f.kind is FindingKind.OUTDATED and f.dependency
    }
    assert outdated[CHI] == ("v5.5.0", "v1.5.4", Gap.MAJOR)
    assert outdated[JWT] == ("v5.3.1", None, Gap.MAJOR)  # v4.4.0 retirée : pas « permise »
    assert outdated[TOML] == ("v1.5.0", "v1.2.0", Gap.MINOR)  # v1.6.0 est exclue
    assert findings(project, FindingKind.OUTDATED, CHI) == [
        "Version v5.5.0 disponible (majeure) ; utilisée : v1.5.4. Elle est publiée sous un "
        "autre module : github.com/go-chi/chi/v5."
    ]
    # La pseudo-version de yaml.v3 n'est pas « inconnue du registre ».
    assert not findings(project, FindingKind.INCONCLUSIVE, YAML)


def test_plan_of_the_go_mini_project(recorded: Routes) -> None:
    report = analyze(GO)
    (project,) = report.projects
    updates = {u.name: u for u in project.updates}
    # Les failles des versions proposées sont demandées à OSV, pas celles d'une majeure publiée
    # sous un autre chemin : OSV la connaît sous ce nom-là.
    proposed = planner.proposed_versions(report)
    assert (Ecosystem.GO, JWT, "v4.5.2") in proposed
    assert (Ecosystem.GO, JWT, "v5.3.1") not in proposed
    jwt = updates[JWT]
    assert [(o.version, o.gap, o.reasons) for o in jwt.options] == [
        ("v4.4.1", Gap.PATCH, (UpdateReason.REPLACEMENT,)),
        ("v4.4.3", Gap.PATCH, (UpdateReason.LATEST_PATCH,)),
        ("v4.5.2", Gap.MINOR, (UpdateReason.LATEST_MINOR, UpdateReason.SECURITY_FIX)),
        ("v5.3.1", Gap.MAJOR, (UpdateReason.LATEST_MAJOR,)),
    ]
    assert jwt.selected == "v4.5.2"
    option = jwt.option("v4.5.2")
    assert option is not None
    (edit,) = option.edits
    assert (edit.kind, edit.file, edit.old, edit.new, option.lockfile) == (
        EditKind.DEPENDENCY,
        "go.mod",
        "v4.4.0",
        "v4.5.2",
        "go.sum",
    )
    # La v5 est un autre module : proposée, à faire à la main, jamais cochée.
    major = jwt.option("v5.3.1")
    assert major is not None and major.edits == () and major.lockfile is None
    assert major.manual == (
        "Majeure publiée sous un autre module (github.com/golang-jwt/jwt/v5) : les imports de "
        "github.com/golang-jwt/jwt/v4 changent aussi dans le code. go get "
        "github.com/golang-jwt/jwt/v5@v5.3.1, puis remplacer les imports."
    )
    # x/text : le correctif pré-coché ; tout corriger demande une majeure (0.x).
    text = updates[TEXT]
    assert text.selected == "v0.3.8"
    assert [o.version for o in text.options] == ["v0.3.8", "v0.41.0", "v0.43.0"]
    assert text.option("v0.41.0").reasons == (UpdateReason.SECURITY_FIX,)  # type: ignore[union-attr]
    # chi : le correctif ; la faille reste (corrigée sous chi/v5 seulement).
    chi = updates[CHI]
    assert (chi.selected, chi.note) == (
        "v1.5.5",
        "Aucune version corrigée connue pour CVE-2025-69725.",
    )
    assert chi.option("v5.5.0").manual is not None  # type: ignore[union-attr]
    # toml : v1.6.0 est exclue (exclude), la dernière mineure proposée est v1.5.0.
    assert [o.version for o in updates[TOML].options] == ["v1.2.1", "v1.5.0"]
    assert updates[TOML].selected == "v1.5.0"
    # uuid : remplacée par elle-même en v1.4.0 : c'est le replace qui se réécrit.
    (edit,) = updates[UUID].option("v1.6.0").edits  # type: ignore[union-attr]
    assert (edit.file, edit.location.line, edit.old, edit.new) == ("go.mod", 24, "v1.4.0", "v1.6.0")  # type: ignore[union-attr]
    # yaml.v3, indirecte en faille : sa ligne // indirect se réécrit (pas le go.sum seul).
    yaml = updates[YAML]
    (option,) = yaml.options
    assert (option.version, option.gap, option.lockfile) == ("v3.0.1", Gap.MAJOR, "go.sum")
    assert [(e.old, e.new) for e in option.edits] == [(YAML_PSEUDO, "v3.0.1")]
    assert yaml.selected is None  # d'une pseudo-version de v3.0.0 à v3.0.1 : majeure pour semver


def test_plan_of_the_go_workspace(recorded: Routes) -> None:
    report = analyze(WORKSPACE)
    lib = next(p for p in report.projects if p.path == "lib")
    text = next(u for u in lib.updates if u.name == TEXT)
    option = text.option("v0.41.0")
    assert option is not None
    (edit,) = option.edits
    # Le replace de go.work se réécrit ; rien à régénérer (go mod tidy ignore go.work).
    assert (edit.file, edit.old, edit.new, option.lockfile) == (
        "go.work",
        "v0.3.8",
        "v0.41.0",
        None,
    )


# -- en ligne de commande -------------------------------------------------------------------


def test_scan_of_the_go_mini_project(recorded: Routes) -> None:
    result = runner.invoke(app, ["scan", str(GO), "--no-cache"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    rows = [line.split() for line in result.stdout.splitlines()]
    assert [JWT, "v4.4.0", "v4.4.0", "v5.3.1", "faille,", "retirée,", "majeure"] in rows
    assert [CHI, "v1.5.4", "v1.5.4", "v1.5.4", "v5.5.0", "faille,", "déprécié,", "majeure"] in rows
    assert [TOML, "v1.2.0", "v1.2.0", "v1.2.0", "v1.5.0", "mineure"] in rows
    assert [YAML, YAML_PSEUDO, YAML_PSEUDO, "faille"] in rows


class FakeGo:
    """``go mod tidy`` comme le vrai : il garde les versions de ``go.mod`` et refait ``go.sum``
    pour elles (des empreintes inventées). Il échoue sans ``GOTOOLCHAIN=local``, pour que le test
    voie qu'aucune chaîne d'outils n'est téléchargée."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def __call__(self, call: ToolCall) -> tuple[int, str, str] | None:
        if call.arguments != ["mod", "tidy"]:
            return 2, "", f"go {' '.join(call.arguments)}: commande inattendue"
        if call.env.get("GOTOOLCHAIN") != "local":
            return 1, "", "go: downloading go1.99.0 (windows/amd64)"
        go_mod = call.cwd / "go.mod"
        dependencies = parse_go_mod("go.mod", go_mod.read_text(encoding="utf-8"))
        lines = []
        for dependency in dependencies:
            if dependency.installed is not None:
                lines.append(f"{dependency.name} {dependency.installed} h1:faux=")
                lines.append(f"{dependency.name} {dependency.installed}/go.mod h1:faux=")
        (call.cwd / "go.sum").write_text("\n".join(sorted(lines)) + "\n", encoding="utf-8")
        return None


def fake_go(fake_tools: Callable[..., FakeTools], root: Path) -> FakeTools:
    tools = fake_tools("go")
    tools.handlers["go"] = FakeGo(root)
    return tools


def test_update_of_the_go_mini_project(
    recorded: Routes, tmp_path: Path, fake_tools: Callable[..., FakeTools]
) -> None:
    root = tmp_path / "go"
    shutil.copytree(GO, root)
    tools = fake_go(fake_tools, root)
    result = runner.invoke(
        app,
        [
            "update",
            str(root),
            "--yes",
            "--level",
            "major",
            *("--include", JWT, "--include", UUID, "--include", YAML),
            "--no-cache",
        ],
        env={"COLUMNS": "200"},
    )
    assert result.exit_code == 0, result.output
    lines = [line.split() for line in result.stdout.splitlines()]
    start = lines.index(["Fichiers", "réécrits", ":", "go.mod."])
    assert lines[start + 1 : start + 5] == [
        ["go.sum", ":", "régénéré", "(Go)."],
        [JWT, "v4.5.2"],
        [YAML, "(indirecte)", "v3.0.1"],
        [UUID, "v1.6.0"],
    ]
    assert tools.commands() == ["go mod tidy"]
    (call,) = tools.calls
    assert (call.cwd, call.env["GOFLAGS"], call.env["GOWORK"]) == (root, "-mod=mod", "off")
    manifest = (root / "go.mod").read_text(encoding="utf-8")
    assert "\tgithub.com/golang-jwt/jwt/v4 v4.5.2\n" in manifest
    assert "replace github.com/google/uuid => github.com/google/uuid v1.6.0\n" in manifest
    assert "\tgopkg.in/yaml.v3 v3.0.1 // indirect\n" in manifest
    assert "github.com/golang-jwt/jwt/v4 v4.5.2 h1:faux=" in (root / "go.sum").read_text(
        encoding="utf-8"
    )
