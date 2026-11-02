"""Les mini-projets Java de ``tests/projects/`` : ``maven`` (un build à trois ``pom.xml``) et
``gradle`` (un catalogue, un script Kotlin, un sous-projet Groovy, ``gradle.properties``).

Ni Maven ni Gradle n'ont de lockfile en V1 : rien n'est produit par un outil. On y vérifie
l'inventaire, puis l'analyse (réponses enregistrées : fixture ``recorded``), le plan, et
``forceupdate scan`` et ``update`` en ligne de commande, qui réécrit les fichiers sans rien
régénérer."""

import asyncio
import shutil
from pathlib import Path

import respx
from typer.testing import CliRunner

from forceupdate import engine
from forceupdate.cli import app
from forceupdate.models import FindingKind, Gap, Project, Report, Scope
from forceupdate.net import Cache, HttpClient
from forceupdate.parsers.maven import REASON_MODULE
from forceupdate.sources.local import LocalSource

PROJECTS = Path(__file__).parent / "projects"
MAVEN = PROJECTS / "maven"
GRADLE = PROJECTS / "gradle"
Routes = dict[str, respx.Route]
runner = CliRunner()


def scan(root: Path) -> dict[str, Project]:
    return {p.path: p for p in engine.inventory(LocalSource(root)).projects}


def analyze(root: Path) -> Report:
    async def main() -> Report:
        async with HttpClient() as http:
            return await engine.analyze(LocalSource(root), http=http, cache=Cache.disabled())

    return asyncio.run(main())


def rows(project: Project) -> list[tuple[str, str, str | None, Scope, str]]:
    return [(d.name, d.constraint, d.installed, d.scope, d.file) for d in project.dependencies]


def test_every_location_points_at_its_version() -> None:
    for root in (MAVEN, GRADLE):
        source = LocalSource(root)
        for project in scan(root).values():
            located = [d for d in project.dependencies if d.location is not None]
            assert located
            for dependency in located:
                text = source.read_text(dependency.file)
                assert text is not None and dependency.location is not None
                assert dependency.location.extract(text) == dependency.constraint


def test_the_maven_mini_project() -> None:
    projects = scan(MAVEN)
    assert sorted(projects) == [".", "app", "lib"]
    root = projects["."]
    assert (root.manifests, root.lockfiles, root.notices) == (["pom.xml"], [], [])
    assert rows(root) == [
        ("org.apache:apache", "23", "23", Scope.RUNTIME, "pom.xml"),
        ("org.apache.logging.log4j:log4j-api", "2.14.1", "2.14.1", Scope.RUNTIME, "pom.xml"),
        ("org.apache.logging.log4j:log4j-core", "2.14.1", "2.14.1", Scope.RUNTIME, "pom.xml"),
        ("com.fasterxml.jackson:jackson-bom", "2.13.0", "2.13.0", Scope.RUNTIME, "pom.xml"),
        ("junit:junit", "4.12", "4.12", Scope.DEV, "pom.xml"),
        ("org.apache.maven.plugins:maven-compiler-plugin", "3.8.1", "3.8.1", Scope.BUILD,
         "pom.xml"),
    ]  # fmt: skip
    # Une seule propriété pour log4j-api et log4j-core : le même emplacement.
    api, core = root.dependencies[1:3]
    assert api.location == core.location and api.location is not None
    lib = projects["lib"]
    assert rows(lib) == [
        ("org.apache.logging.log4j:log4j-api", "2.14.1", "2.14.1", Scope.RUNTIME, "pom.xml"),
        ("com.google.guava:guava", "30.1-jre", "30.1-jre", Scope.RUNTIME, "lib/pom.xml"),
        ("org.apache.commons:commons-text", "[1.9,2.0)", None, Scope.RUNTIME, "lib/pom.xml"),
        ("junit:junit", "4.12", "4.12", Scope.DEV, "pom.xml"),
    ]
    app_project = projects["app"]
    found = {d.name: d for d in app_project.dependencies}
    assert found["com.example.demo:demo-lib"].unverifiable_reason == REASON_MODULE
    assert found["com.fasterxml.jackson.core:jackson-databind"].unverifiable_reason == (
        "version gérée par un BOM importé (com.fasterxml.jackson:jackson-bom)"
    )
    assert found["org.apache.maven.plugins:maven-surefire-plugin"].unverifiable_reason == (
        "version gérée par le parent org.apache:apache (hors du dépôt)"
    )
    assert (found["org.springframework:spring-webmvc"].constraint, found[
        "org.springframework:spring-webmvc"
    ].file) == ("5.3.17", "app/pom.xml")  # fmt: skip
    assert found["javax.servlet:javax.servlet-api"].scope is Scope.RUNTIME  # provided
    assert found["org.yaml:snakeyaml"].scope is Scope.OPTIONAL
    assert found["org.apache.maven.plugins:maven-compiler-plugin"].file == "pom.xml"
    assert all(d.direct and d.lockfile is None for p in projects.values() for d in p.dependencies)


def test_the_gradle_mini_project() -> None:
    projects = scan(GRADLE)
    assert sorted(projects) == [".", "app"]
    root = projects["."]
    assert (root.manifests, root.lockfiles, root.notices) == (
        ["build.gradle.kts", "gradle/libs.versions.toml", "settings.gradle.kts"],
        [],
        [],
    )
    catalog = "gradle/libs.versions.toml"
    assert rows(root) == [
        ("com.google.guava:guava", "31.0.1-jre", "31.0.1-jre", Scope.RUNTIME, catalog),
        ("junit:junit", "4.12", "4.12", Scope.DEV, catalog),
        ("com.squareup.okhttp3:okhttp", "4.9.0", "4.9.0", Scope.RUNTIME, catalog),
        ("com.squareup.okhttp3:logging-interceptor", "4.9.0", "4.9.0", Scope.RUNTIME, catalog),
        ("com.github.ben-manes.versions", "0.42.0", "0.42.0", Scope.BUILD, catalog),
        ("org.springframework.boot", "2.6.6", "2.6.6", Scope.BUILD, "build.gradle.kts"),
        ("org.apache.commons:commons-text", "1.9", "1.9", Scope.RUNTIME, "build.gradle.kts"),
        ("com.fasterxml.jackson:jackson-bom", "2.13.0", "2.13.0", Scope.RUNTIME,
         "build.gradle.kts"),
        ("com.fasterxml.jackson.core:jackson-databind", "", None, Scope.RUNTIME,
         "build.gradle.kts"),
    ]  # fmt: skip
    okhttp, logging = root.dependencies[2:4]
    assert okhttp.location == logging.location  # [versions] okhttp
    assert rows(projects["app"]) == [
        ("org.yaml:snakeyaml", "1.30", "1.30", Scope.RUNTIME, "gradle.properties"),
        ("androidx.annotation:annotation", "1.3.0", "1.3.0", Scope.RUNTIME, "app/build.gradle"),
        ("org.mockito:mockito-core", "4.0.0", "4.0.0", Scope.DEV, "app/build.gradle"),
    ]


def vulnerabilities(project: Project, name: str) -> list[tuple[str, str | None]]:
    return [
        (f.identifiers[0], f.target_version)
        for f in project.findings
        if f.kind is FindingKind.VULNERABLE and f.dependency and f.dependency.name == name
    ]


def test_findings_of_the_maven_mini_project(recorded: Routes) -> None:
    projects = {p.path: p for p in analyze(MAVEN).projects}
    root = projects["."]
    log4j = vulnerabilities(root, "org.apache.logging.log4j:log4j-core")
    # Log4Shell, puis les corrections qui ont suivi.
    for found in [
        ("CVE-2021-44228", "2.15.0"),
        ("CVE-2021-45046", "2.16.0"),
        ("CVE-2021-45105", "2.17.0"),
        ("CVE-2021-44832", "2.17.1"),
    ]:
        assert found in log4j
    assert vulnerabilities(root, "junit:junit") == [("CVE-2020-15250", "4.13.1")]
    outdated = {
        f.dependency.name: (f.target_version, f.wanted_version, f.gap)
        for project in projects.values()
        for f in project.findings
        if f.kind is FindingKind.OUTDATED and f.dependency
    }
    assert outdated["org.apache:apache"] == ("40", "23", Gap.MAJOR)
    # <release> de log4j est une pré-version (3.0.0-beta3) : la dernière stable est proposée.
    assert outdated["org.apache.logging.log4j:log4j-core"] == ("2.26.1", "2.14.1", Gap.MINOR)
    # Une plage : Maven prendrait la plus haute publiée, déjà dans la contrainte.
    assert outdated["org.apache.commons:commons-text"] == ("1.15.0", "1.15.0", Gap.MINOR)
    # La variante -jre est gardée.
    assert outdated["com.google.guava:guava"] == ("33.7.2-jre", "30.1-jre", Gap.MAJOR)
    assert ("CVE-2022-42889", "1.10.0") in vulnerabilities(
        projects["lib"], "org.apache.commons:commons-text"
    )
    # OSV écrit « fixed: 32.0.0-android » : à qui a -jre, la plus petite -jre qui n'est plus
    # concernée (E34).
    guava = vulnerabilities(projects["lib"], "com.google.guava:guava")
    assert guava and all(fixed is None or fixed.endswith("-jre") for _, fixed in guava)
    assert ("CVE-2023-2976", "32.0.0-jre") in guava
    unverifiable = [
        f.message for f in projects["app"].findings if f.kind is FindingKind.UNVERIFIABLE
    ]
    assert unverifiable == [f"Non vérifiable : {REASON_MODULE}."]
    # E34 : les versions gérées hors du dépôt, lues dans le pom du BOM et du parent distants.
    app = {d.name: d for d in projects["app"].dependencies}
    databind = app["com.fasterxml.jackson.core:jackson-databind"]
    assert (databind.installed, databind.location) == ("2.13.0", None)
    assert databind.manual == (
        "version gérée par le BOM com.fasterxml.jackson:jackson-bom:2.13.0 : la changer avec lui, "
        "ou écrire la <version> voulue"
    )
    assert vulnerabilities(projects["app"], "com.fasterxml.jackson.core:jackson-databind")
    surefire = app["org.apache.maven.plugins:maven-surefire-plugin"]
    assert surefire.installed == "2.22.0"
    assert surefire.manual is not None and "le parent org.apache:apache:23" in surefire.manual
    # Sa mise à jour est celle du BOM : à la main, jamais cochée d'office.
    update = next(u for u in projects["app"].updates if u.name == databind.name)
    assert update.selected is None
    assert all(option.manual for option in update.options)


def test_plan_of_the_maven_mini_project(recorded: Routes) -> None:
    projects = {p.path: p for p in analyze(MAVEN).projects}
    updates = {u.name: u for u in projects["."].updates}
    core = updates["org.apache.logging.log4j:log4j-core"]
    assert core.selected == "2.26.1"
    option = core.option("2.26.1")
    assert option is not None and option.lockfile is None
    (edit,) = option.edits
    assert (edit.file, edit.old, edit.new) == ("pom.xml", "2.14.1", "2.26.1")
    assert option.warnings == (
        "Version partagée avec org.apache.logging.log4j:log4j-api (pom.xml, ligne 28) : elle "
        "monte aussi.",
    )
    assert updates["org.apache:apache"].selected is None  # une majeure
    lib = {u.name: u for u in projects["lib"].updates}
    (text_edit,) = lib["org.apache.commons:commons-text"].option("1.10.0").edits  # type: ignore[union-attr]
    assert (text_edit.old, text_edit.new) == ("[1.9,2.0)", "[1.10.0,2.0)")
    guava = lib["com.google.guava:guava"]
    assert [o.version for o in guava.options] == ["30.1.1-jre", "33.7.2-jre"]
    # Le module prend la version du parent : la réécriture est dans le pom.xml racine.
    (module_edit,) = lib["junit:junit"].option("4.13.2").edits  # type: ignore[union-attr]
    assert (module_edit.file, module_edit.old) == ("pom.xml", "4.12")


def test_plan_of_the_gradle_mini_project(recorded: Routes) -> None:
    projects = {p.path: p for p in analyze(GRADLE).projects}
    updates = {u.name: u for u in projects["."].updates}
    okhttp = updates["com.squareup.okhttp3:okhttp"]
    assert okhttp.selected == "4.12.1"
    (edit,) = okhttp.option("4.12.1").edits  # type: ignore[union-attr]
    assert (edit.file, edit.old, edit.new) == ("gradle/libs.versions.toml", "4.9.0", "4.12.1")
    assert any("logging-interceptor" in w for w in okhttp.option("4.12.1").warnings)  # type: ignore[union-attr]
    boot = updates["org.springframework.boot"]
    assert [o.version for o in boot.options] == ["2.6.15", "2.7.18", "4.1.2"]
    assert updates["com.google.guava:guava"].selected == "31.1-jre"
    app_updates = {u.name: u for u in projects["app"].updates}
    (snakeyaml,) = app_updates["org.yaml:snakeyaml"].option("1.33").edits  # type: ignore[union-attr]
    assert (snakeyaml.file, snakeyaml.old, snakeyaml.new) == ("gradle.properties", "1.30", "1.33")
    assert app_updates["androidx.annotation:annotation"].selected == "1.11.0"


# -- en ligne de commande -------------------------------------------------------------------


def test_scan_of_the_maven_mini_project(recorded: Routes) -> None:
    result = runner.invoke(app, ["scan", str(MAVEN), "--no-cache"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    rows_ = [line.split() for line in result.stdout.splitlines()]
    assert [
        "org.apache.logging.log4j:log4j-core", "2.14.1", "2.14.1", "2.14.1", "2.26.1", "faille,",
        "mineure",
    ] in rows_  # fmt: skip
    # Une plage, sans lockfile : sa borne basse, approximative ; la faille n'est que possible.
    assert ["org.apache.commons:commons-text", "(lib/pom.xml)", "[1.9,2.0)", "≈", "1.9", "1.15.0",
            "1.15.0", "faille", "possible,", "mineure"] in rows_  # fmt: skip
    assert ["org.apache.logging.log4j:log4j-api", "(pom.xml)", "2.14.1", "2.14.1", "2.14.1",
            "2.26.1", "faille,", "mineure"] in rows_  # fmt: skip
    assert ["lockfiles", ":", "aucun"] in rows_


def test_update_of_the_maven_mini_project(recorded: Routes, tmp_path: Path) -> None:
    root = tmp_path / "maven"
    shutil.copytree(MAVEN, root)
    result = runner.invoke(
        app,
        ["update", str(root), "--yes", "--include", "org.apache.logging.log4j:*", "--no-cache"],
        env={"COLUMNS": "200"},
    )
    assert result.exit_code == 0, result.output
    output = " ".join(result.stdout.split())
    assert "Aucun lockfile à régénérer : les manifestes réécrits suffisent." in output
    assert "Version partagée avec org.apache.logging.log4j:log4j-api" in output
    assert "Fichiers réécrits : pom.xml." in output
    text = (root / "pom.xml").read_text(encoding="utf-8")
    assert "<log4j.version>2.26.1</log4j.version>" in text
    assert text.replace("2.26.1", "2.14.1") == (MAVEN / "pom.xml").read_text(encoding="utf-8")
    # Relue, le build monte log4j-api et log4j-core ensemble, dans les trois projets.
    after = scan(root)
    versions = {
        (path, d.name): d.installed
        for path, project in after.items()
        for d in project.dependencies
        if d.name.startswith("org.apache.logging.log4j:")
    }
    assert set(versions.values()) == {"2.26.1"} and len(versions) == 4


def test_update_of_the_gradle_mini_project(recorded: Routes, tmp_path: Path) -> None:
    root = tmp_path / "gradle"
    shutil.copytree(GRADLE, root)
    result = runner.invoke(
        app,
        ["update", str(root), "--yes", "--include", "com.squareup.okhttp3:*", "--include",
         "org.yaml:snakeyaml", "--include", "org.apache.commons:commons-text", "--no-cache"],
        env={"COLUMNS": "200"},
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    catalog = (root / "gradle" / "libs.versions.toml").read_text(encoding="utf-8")
    assert 'okhttp = "4.12.1"' in catalog
    assert (
        (root / "gradle.properties").read_text(encoding="utf-8").endswith("snakeyamlVersion=1.33\n")
    )
    assert 'val commonsTextVersion = "1.15.0"' in (root / "build.gradle.kts").read_text(
        encoding="utf-8"
    )
    output = " ".join(result.stdout.split())
    assert "Aucun lockfile à régénérer" in output
