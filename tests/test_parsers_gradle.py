"""Le parseur Gradle : le catalogue ``libs.versions.toml``, les scripts ``build.gradle`` et
``build.gradle.kts``, ``gradle.properties``. Gradle n'est jamais lancé."""

import pytest

from forceupdate.models import Dependency, Location, Notice, Scope
from forceupdate.parsers.base import ParseError
from forceupdate.parsers.gradle import (
    REASON_PLATFORM,
    configuration_scope,
    parse_gradle_project,
    read_catalog,
    read_lockfile,
    read_properties,
    read_script,
    script_dependencies,
)
from forceupdate.parsers.gradle_spans import tokens


def rows(found: list[Dependency]) -> list[tuple[str, str, Scope, str | None]]:
    return [(d.name, d.constraint, d.scope, d.unverifiable_reason) for d in found]


def script(text: str, path: str = "build.gradle.kts") -> list[Dependency]:
    parsed = read_script(path, text)
    return script_dependencies(parsed, parsed.variables)


# ---------------------------------------------------------------------------
# Jetons
# ---------------------------------------------------------------------------


def test_tokens() -> None:
    text = "a(\"x:y:1\") // \"pas une chaîne\"\n/* \"non plus\" */ b '''z''' \"q$v\" '\\n'"
    found = [(t.kind, t.value) for t in tokens(text) if t.kind != "newline"]
    assert found == [
        ("ident", "a"),
        ("op", "("),
        ("string", "x:y:1"),
        ("op", ")"),
        ("ident", "b"),
        ("string", "z"),
        ("string", "q$v"),
        ("string", "\\n"),
    ]
    strings = [t for t in tokens(text) if t.kind == "string"]
    assert (strings[0].line, strings[0].column, strings[0].end_column) == (1, 3, 8)
    assert strings[2].interpolates and not strings[1].interpolates
    assert not strings[3].plain  # un échappement


def test_an_interpolation_may_hold_quotes() -> None:
    (string,) = [t for t in tokens('x("g:a:${property("v")}")') if t.kind == "string"]
    assert string.value == 'g:a:${property("v")}'


# ---------------------------------------------------------------------------
# Le catalogue
# ---------------------------------------------------------------------------

CATALOG = """\
[versions]
okhttp = "4.9.0"
strict = { strictly = "[1.0, 2.0[", prefer = "1.5" }

[libraries]
guava = "com.google.guava:guava:31.0.1-jre"
junit = { module = "junit:junit", version = "4.12" }
okhttp = { module = "com.squareup.okhttp3:okhttp", version.ref = "okhttp" }
okhttp-logging = {group="com.squareup.okhttp3", name="logging-interceptor", version.ref="okhttp"}
rich = { module = "a:rich", version = { require = "1.2" } }
strict = { module = "a:strict", version.ref = "strict" }
missing = { module = "a:missing", version.ref = "nope" }
bom-managed = { module = "a:managed" }
short = "a:short"

[bundles]
http = ["okhttp", "okhttp-logging"]

[plugins]
versions = { id = "com.github.ben-manes.versions", version = "0.42.0" }
boot = "org.springframework.boot:2.6.6"
"""


def test_catalog_entries() -> None:
    catalog = read_catalog("gradle/libs.versions.toml", CATALOG)
    found = [(e.section, e.alias, e.name, e.version, e.reason) for e in catalog.entries]
    assert found == [
        ("libraries", "guava", "com.google.guava:guava", "31.0.1-jre", None),
        ("libraries", "junit", "junit:junit", "4.12", None),
        ("libraries", "okhttp", "com.squareup.okhttp3:okhttp", "4.9.0", None),
        ("libraries", "okhttp-logging", "com.squareup.okhttp3:logging-interceptor", "4.9.0", None),
        ("libraries", "rich", "a:rich", "1.2", None),
        ("libraries", "strict", "a:strict", "[1.0, 2.0[", None),
        ("libraries", "missing", "a:missing", "", "version.ref « nope » absente de [versions]"),
        ("libraries", "bom-managed", "a:managed", "", REASON_PLATFORM),
        ("libraries", "short", "a:short", "", REASON_PLATFORM),
        ("plugins", "versions", "com.github.ben-manes.versions", "0.42.0", None),
        ("plugins", "boot", "org.springframework.boot", "2.6.6", None),
    ]
    by_alias = {e.alias: e for e in catalog.entries}
    lines = CATALOG.split("\n")
    written = {"guava": "31.0.1-jre", "okhttp": "4.9.0", "rich": "1.2", "strict": "[1.0, 2.0[",
               "boot": "2.6.6", "junit": "4.12"}  # fmt: skip
    for alias, text in written.items():
        location = by_alias[alias].location
        assert location is not None, alias
        assert lines[location.line - 1][location.column : location.end_column] == text
    # Les deux entrées de version.ref « okhttp » ont l'emplacement de [versions].
    assert by_alias["okhttp"].location == by_alias["okhttp-logging"].location
    assert by_alias["okhttp"].location == Location(line=2, column=10, end_column=15)
    assert [e.alias for e in catalog.accessor("bundles", "http")] == ["okhttp", "okhttp-logging"]
    assert [e.alias for e in catalog.accessor("libraries", "okhttp.logging")] == ["okhttp-logging"]


def test_an_invalid_catalog() -> None:
    with pytest.raises(ParseError, match="TOML invalide"):
        read_catalog("gradle/libs.versions.toml", "[libraries\n")


# ---------------------------------------------------------------------------
# Les scripts
# ---------------------------------------------------------------------------


def test_kotlin_forms() -> None:
    text = """\
plugins {
    java
    id("org.springframework.boot") version "2.6.6" apply false
    kotlin("jvm") version "1.6.10"
    id("com.example.dynamic").version("1.0")
}

dependencies {
    implementation("org.apache.commons:commons-text:1.9")
    testImplementation("junit:junit:4.12") { because("tests") }
    implementation(platform("com.fasterxml.jackson:jackson-bom:2.13.0"))
    implementation(enforcedPlatform("a:enforced:1"))
    implementation("com.fasterxml.jackson.core:jackson-databind")
    runtimeOnly(group = "org.x", name = "y", version = "2.0")
    annotationProcessor("org.mapstruct:mapstruct-processor:1.5.0.Final")
    implementation("a:classifier:3:linux@zip")
    implementation(project(":lib"))
    implementation(kotlin("stdlib"))
    implementation(files("libs/a.jar"))
}
"""
    assert rows(script(text)) == [
        ("org.springframework.boot", "2.6.6", Scope.BUILD, None),
        ("org.jetbrains.kotlin.jvm", "1.6.10", Scope.BUILD, None),
        ("com.example.dynamic", "1.0", Scope.BUILD, None),
        ("org.apache.commons:commons-text", "1.9", Scope.RUNTIME, None),
        ("junit:junit", "4.12", Scope.DEV, None),
        ("com.fasterxml.jackson:jackson-bom", "2.13.0", Scope.RUNTIME, None),
        ("a:enforced", "1", Scope.RUNTIME, None),
        ("com.fasterxml.jackson.core:jackson-databind", "", Scope.RUNTIME, REASON_PLATFORM),
        ("org.x:y", "2.0", Scope.RUNTIME, None),
        ("org.mapstruct:mapstruct-processor", "1.5.0.Final", Scope.BUILD, None),
        ("a:classifier", "3", Scope.RUNTIME, None),
    ]
    lines = text.split("\n")
    for dependency in script(text):
        if dependency.location is not None:
            location = dependency.location
            written = lines[location.line - 1][location.column : location.end_column]
            assert written == dependency.constraint


def test_groovy_forms() -> None:
    text = """\
buildscript {
    dependencies {
        classpath 'com.android.tools.build:gradle:7.0.0'
    }
}
plugins {
    id 'java'
    id 'org.springframework.boot' version '2.6.6'
}
dependencies {
    implementation 'org.apache.httpcomponents:httpclient:4.5.13', "commons-io:commons-io:2.7"
    testImplementation group: 'org.mockito', name: 'mockito-core', version: '4.0.0'
    implementation('androidx.annotation:annotation:1.3.0')
    compile 'a:old:1'
    implementation 'a:concat:' + someVersion
}
"""
    assert rows(script(text, "build.gradle")) == [
        ("com.android.tools.build:gradle", "7.0.0", Scope.BUILD, None),
        ("org.springframework.boot", "2.6.6", Scope.BUILD, None),
        ("org.apache.httpcomponents:httpclient", "4.5.13", Scope.RUNTIME, None),
        ("commons-io:commons-io", "2.7", Scope.RUNTIME, None),
        ("org.mockito:mockito-core", "4.0.0", Scope.DEV, None),
        ("androidx.annotation:annotation", "1.3.0", Scope.RUNTIME, None),
        ("a:old", "1", Scope.RUNTIME, None),
        (
            "a:concat",
            "",
            Scope.RUNTIME,
            'version calculée par le script ("a:concat:" + someVersion), pas lue',
        ),
    ]


def test_variables() -> None:
    text = """\
val okioVersion = "3.0.0"
val typed: String = "1.1"
def groovyStyle = '2.2'
ext.extVersion = '3.3'
ext {
    blockVersion = '4.4'
}
extra["extraVersion"] = "5.5"
val byExtra by extra("6.6")
val twice = "1"
val twice = "2"

dependencies {
    implementation("com.squareup.okio:okio:$okioVersion")
    implementation("a:typed:${typed}")
    implementation("a:groovy:$groovyStyle")
    implementation("a:ext:${project.ext.extVersion}")
    implementation("a:block:$blockVersion")
    implementation("a:extra:$extraVersion")
    implementation("a:by-extra:$byExtra")
    implementation("a:twice:$twice")
    implementation("a:unknown:$nowhere")
    implementation("a:expression:${libs.versions.x.get()}")
    implementation("a:composite:1.$typed")
    implementation('a:single-quotes:$okioVersion')
}
"""
    found = script(text)
    assert rows(found) == [
        ("com.squareup.okio:okio", "3.0.0", Scope.RUNTIME, None),
        ("a:typed", "1.1", Scope.RUNTIME, None),
        ("a:groovy", "2.2", Scope.RUNTIME, None),
        ("a:ext", "3.3", Scope.RUNTIME, None),
        ("a:block", "4.4", Scope.RUNTIME, None),
        ("a:extra", "5.5", Scope.RUNTIME, None),
        ("a:by-extra", "6.6", Scope.RUNTIME, None),
        ("a:twice", "$twice", Scope.RUNTIME, "version dans une variable (twice) non résolue"),
        ("a:unknown", "$nowhere", Scope.RUNTIME, "version dans une variable (nowhere) non résolue"),
        (
            "a:expression",
            "${libs.versions.x.get()}",
            Scope.RUNTIME,
            "version calculée par le script (${libs.versions.x.get()}), pas lue",
        ),
        ("a:composite", "1.1.1", Scope.RUNTIME, None),
        ("a:single-quotes", "$okioVersion", Scope.RUNTIME, None),  # pas d'interpolation en '…'
    ]
    okio = found[0]
    assert okio.location == Location(line=1, column=19, end_column=24)  # la valeur de la variable
    assert found[10].location is None  # une version composée : à la main
    shared = read_script("build.gradle.kts", text).variables
    assert [name for name, v in shared.items() if v.shared] == [
        "extVersion",
        "blockVersion",
        "extraVersion",
        "byExtra",
    ]


def test_properties() -> None:
    found = read_properties("gradle.properties", "# x\nsnakeyaml=1.30\nother: 2\n! y\nesc=a\\b\n")
    assert {k: (v.value, v.location) for k, v in found.items()} == {
        "snakeyaml": ("1.30", Location(line=2, column=10, end_column=14)),
        "other": ("2", Location(line=3, column=7, end_column=8)),
        "esc": (None, None),
    }


@pytest.mark.parametrize(
    ("configuration", "scope"),
    [
        ("implementation", Scope.RUNTIME),
        ("api", Scope.RUNTIME),
        ("compileOnly", Scope.RUNTIME),
        ("testImplementation", Scope.DEV),
        ("androidTestImplementation", Scope.DEV),
        ("testFixturesApi", Scope.DEV),
        ("developmentOnly", Scope.DEV),
        ("classpath", Scope.BUILD),
        ("kapt", Scope.BUILD),
        ("ksp", Scope.BUILD),
        ("annotationProcessor", Scope.BUILD),
        ("debugImplementation", Scope.RUNTIME),
    ],
)
def test_configuration_scope(configuration: str, scope: Scope) -> None:
    assert configuration_scope(configuration) is scope


# ---------------------------------------------------------------------------
# Un projet
# ---------------------------------------------------------------------------

FILES = {
    "gradle/libs.versions.toml": CATALOG,
    "build.gradle.kts": """\
plugins { alias(libs.plugins.versions) }
val gsonVersion by extra("2.8.8")
dependencies {
    implementation(libs.guava)
    testImplementation(libs.junit)
    implementation(libs.nope)
}
""",
    "gradle.properties": "snakeyamlVersion=1.30\n",
    "app/build.gradle": """\
dependencies {
    implementation libs.bundles.http
    testImplementation libs.guava
    implementation "org.yaml:snakeyaml:$snakeyamlVersion"
    implementation "com.google.code.gson:gson:$gsonVersion"
    testImplementation libs.plugins.missing
}
""",
}


def gradle_project(directory: str, manifests: list[str]) -> tuple[list[Dependency], list[Notice]]:
    notices: list[Notice] = []
    found = parse_gradle_project(directory, manifests, FILES.get, [".", "app"], notices)
    return found, notices


def test_the_catalog_takes_its_scopes_from_the_scripts() -> None:
    found, notices = gradle_project(".", ["build.gradle.kts", "gradle/libs.versions.toml"])
    scopes = {d.name: d.scope for d in found}
    assert scopes["com.google.guava:guava"] is Scope.RUNTIME  # runtime ici, dev dans app
    assert scopes["junit:junit"] is Scope.DEV
    assert scopes["com.squareup.okhttp3:okhttp"] is Scope.RUNTIME
    assert scopes["com.github.ben-manes.versions"] is Scope.BUILD
    assert scopes["a:rich"] is Scope.RUNTIME  # citée nulle part
    assert notices == [
        Notice(
            file="build.gradle.kts",
            message="« libs.nope » absent du catalogue gradle/libs.versions.toml : pas vérifié.",
        )
    ]


def test_a_subproject() -> None:
    files_before = dict(FILES)
    FILES["gradle.lockfile"] = "a:b:1=compileClasspath\n"
    FILES["app/gradle.lockfile"] = "a:b:1=compileClasspath\n"
    try:
        found, notices = gradle_project("app", ["app/build.gradle"])
    finally:
        FILES.clear()
        FILES.update(files_before)
    # Les entrées du catalogue citées ne sont pas redonnées : celui de la racine les vérifie.
    assert [(d.name, d.constraint, d.file) for d in found] == [
        ("org.yaml:snakeyaml", "1.30", "gradle.properties"),
        ("com.google.code.gson:gson", "2.8.8", "build.gradle.kts"),
        ("a:b", "", "app/gradle.lockfile"),  # une indirecte des verrous (E34)
    ]
    assert [n.message.split(" :")[0] for n in notices] == [
        "« libs.plugins.missing » absent du catalogue gradle/libs.versions.toml",
        "verrous de Gradle",
    ]
    assert notices[1].file == "app/gradle.lockfile"


# ---------------------------------------------------------------------------
# E34 : versions riches, settings.gradle(.kts), autres catalogues, gradle.lockfile
# ---------------------------------------------------------------------------


def test_rich_versions_of_a_script() -> None:
    kotlin = """\
dependencies {
    implementation("org.slf4j:slf4j-api") {
        version {
            strictly("1.7.36")
        }
    }
    implementation("com.google.guava:guava") {
        version { require("31.0-jre"); prefer("31.1-jre") }
    }
    implementation("a:b") { exclude(group = "c") }
}
"""
    found = script(kotlin)
    assert rows(found) == [
        ("org.slf4j:slf4j-api", "1.7.36", Scope.RUNTIME, None),
        ("com.google.guava:guava", "31.0-jre", Scope.RUNTIME, None),  # require avant prefer
        ("a:b", "", Scope.RUNTIME, REASON_PLATFORM),
    ]
    assert found[0].location == Location(line=4, column=22, end_column=28)
    groovy = """\
dependencies {
    implementation('org.slf4j:slf4j-api') {
        version { strictly '[1.7, 1.8[' }
    }
}
"""
    assert rows(script(groovy, "build.gradle")) == [
        ("org.slf4j:slf4j-api", "[1.7, 1.8[", Scope.RUNTIME, None)
    ]


SETTINGS = """\
pluginManagement {
    plugins { id("org.jetbrains.kotlin.jvm") version "1.9.0" }
}
plugins {
    id("org.gradle.toolchains.foojay-resolver-convention") version "0.8.0"
}
dependencyResolutionManagement {
    versionCatalogs {
        create("deps") { from(files("gradle/deps.versions.toml")) }
        create("remote") { from("com.example:catalog:1.0") }
    }
}
include("app")
"""


def test_settings_plugins_and_other_catalogs() -> None:
    files = {
        "settings.gradle.kts": SETTINGS,
        "gradle/deps.versions.toml": """[libraries]
okio = "com.squareup.okio:okio:3.4.0"
""",
    }
    notices: list[Notice] = []
    found = parse_gradle_project(".", ["settings.gradle.kts"], files.get, ["."], notices)
    assert [(d.name, d.constraint, d.file) for d in found] == [
        ("com.squareup.okio:okio", "3.4.0", "gradle/deps.versions.toml"),
        ("org.jetbrains.kotlin.jvm", "1.9.0", "settings.gradle.kts"),
        ("org.gradle.toolchains.foojay-resolver-convention", "0.8.0", "settings.gradle.kts"),
    ]
    assert [n.message for n in notices] == [
        "catalogue « remote » publié (com.example:catalog:1.0) : pas lu par forceupdate."
    ]


def test_a_groovy_catalog_block() -> None:
    settings = """\
dependencyResolutionManagement {
  versionCatalogs {
    tools { from(files('../shared/tools.toml')) }
  }
}
"""
    files = {
        "build/settings.gradle": settings,
        "shared/tools.toml": """[libraries]
x = "a:b:1.0"
""",
    }
    found = parse_gradle_project("build", ["build/settings.gradle"], files.get, ["build"], [])
    assert [(d.name, d.file) for d in found] == [("a:b", "shared/tools.toml")]


LOCKS = """\
# This is a Gradle generated file for dependency locking.
# Manual edits can break the build and are not advised.
# This file is expected to be part of source control.
com.google.guava:guava:31.1-jre=compileClasspath,runtimeClasspath
com.google.guava:failureaccess:1.0.1=compileClasspath,runtimeClasspath
junit:junit:4.13.2=testCompileClasspath,testRuntimeClasspath
org.hamcrest:hamcrest-core:1.3=testCompileClasspath,testRuntimeClasspath
empty=annotationProcessor
"""


def test_read_lockfile() -> None:
    locks = read_lockfile(LOCKS)
    assert locks["com.google.guava:guava"] == (
        "31.1-jre",
        ("compileClasspath", "runtimeClasspath"),
    )
    assert "empty" not in locks
    assert len(locks) == 4


def test_the_lockfile_gives_installed_versions_and_indirects() -> None:
    files = {
        "build.gradle.kts": """\
dependencies {
    implementation("com.google.guava:guava:31.0-jre")
    testImplementation("junit:junit:4.13.1")
}
""",
        "gradle.lockfile": LOCKS,
    }
    notices: list[Notice] = []
    found = parse_gradle_project(".", ["build.gradle.kts"], files.get, ["."], notices)
    assert [(d.name, d.constraint, d.installed, d.direct, d.scope, d.lockfile) for d in found] == [
        ("com.google.guava:guava", "31.0-jre", "31.1-jre", True, Scope.RUNTIME, None),
        ("junit:junit", "4.13.1", "4.13.2", True, Scope.DEV, None),
        ("com.google.guava:failureaccess", "", "1.0.1", False, Scope.RUNTIME, None),
        ("org.hamcrest:hamcrest-core", "", "1.3", False, Scope.DEV, None),
    ]
    (notice,) = notices
    assert notice.message.startswith("verrous de Gradle : lus pour les versions installées")
