"""Les langages : extension → langage, fichiers écartés, poids en octets, écosystème."""

import pytest

from forceupdate.detect import languages
from forceupdate.detect.languages import (
    detect_languages,
    ecosystem_for_language,
    is_excluded,
    language_for,
)
from forceupdate.models import Ecosystem, Language


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/app.py", "Python"),
        ("MAIN.PY", "Python"),
        ("web/Component.tsx", "TypeScript"),
        ("types/index.d.ts", "TypeScript"),
        ("src/.eslintrc.js", "JavaScript"),
        ("views/home.blade.php", "Blade"),
        ("index.php", "PHP"),
        ("App.vue", "Vue"),
        ("lib.rs", "Rust"),
        ("Program.cs", "C#"),
        ("scripts/run.sh", "Shell"),
        ("build.ps1", "PowerShell"),
        ("Dockerfile", "Dockerfile"),
        ("docker/Dockerfile.prod", "Dockerfile"),
        ("Makefile", "Makefile"),
        ("CMakeLists.txt", "CMake"),
        ("Gemfile", "Ruby"),
        ("plugin.kts", "Kotlin"),
        ("main.tf", "HCL"),
        # Données, prose ou fichiers sans langage : ils ne comptent pas, comme chez Linguist.
        ("build.gradle", None),
        ("build.gradle.kts", None),
        ("package.json", None),
        ("config.yaml", None),
        ("pyproject.toml", None),
        ("README.md", None),
        ("notes.txt", None),
        (".bashrc", None),
        ("LICENSE", None),
    ],
)
def test_language_for(path: str, expected: str | None) -> None:
    assert language_for(path) == expected


def test_about_forty_common_languages() -> None:
    names = {*languages._EXTENSIONS.values(), *languages._FILENAMES.values()} - {None}
    assert len(names) >= 40


@pytest.mark.parametrize(
    "path",
    [
        "node_modules/left-pad/index.js",
        "static/vendor/lib.js",
        "src/vendors/chart.js",
        "third_party/zlib/inflate.c",
        "web/dist/bundle.js",
        "assets/app.min.js",
        "css/site-min.css",
        "js/jquery-3.6.0.js",
        "gradlew",
        ".github/scripts/release.py",
        "api/v1/service.pb.go",
        "proto/user_pb2.py",
        "proto/user_pb2_grpc.py",
        "Forms/Main.Designer.cs",
        "src/__generated__/query.ts",
        "lib/model.g.dart",
        "docs/conf.py",
        "doc/build.js",
        "examples/demo.py",
        "lib/documentation/gen.py",
    ],
)
def test_vendored_generated_and_documentation_are_excluded(path: str) -> None:
    assert is_excluded(path)


@pytest.mark.parametrize(
    "path",
    [
        "src/app.py",
        "src/docs_helper.py",
        "src/examples.py",
        "pkg/examples/server.go",  # comme chez Linguist : examples/ ne compte qu'à la racine
        "distribution/setup.py",
        "lib/minimal.js",
    ],
)
def test_ordinary_code_is_not_excluded(path: str) -> None:
    assert not is_excluded(path)


def test_detect_languages_weighs_bytes_and_sorts_heaviest_first() -> None:
    files = [
        ("a.py", 100),
        ("pkg/b.py", 50),
        ("web/app.ts", 120),
        ("scripts/x.sh", 10),
        ("node_modules/x/index.js", 9999),
        ("README.md", 500),
        ("data.json", 300),
    ]
    assert detect_languages(files) == [
        Language(name="Python", bytes=150, ecosystem=Ecosystem.PYPI),
        Language(name="TypeScript", bytes=120, ecosystem=Ecosystem.NPM),
        Language(name="Shell", bytes=10, ecosystem=None),
    ]


def test_detect_languages_breaks_ties_by_name() -> None:
    result = detect_languages([("b.rb", 10), ("a.go", 10)])
    assert [language.name for language in result] == ["Go", "Ruby"]


def test_empty_languages_are_left_out() -> None:
    assert detect_languages([("pkg/__init__.py", 0)]) == []
    assert detect_languages([]) == []


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        ([("a.c", 10), ("a.h", 5)], "C"),
        ([("a.cpp", 10), ("a.h", 5)], "C++"),
        ([("a.m", 10), ("a.h", 5)], "Objective-C"),
        ([("a.h", 5)], "C"),
    ],
)
def test_headers_go_to_the_c_family_present(files: list[tuple[str, int]], expected: str) -> None:
    total = sum(size for _, size in files)
    assert detect_languages(files) == [Language(name=expected, bytes=total)]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Python", Ecosystem.PYPI),
        ("TypeScript", Ecosystem.NPM),
        ("Rust", Ecosystem.CRATES_IO),
        ("Go", Ecosystem.GO),
        ("PHP", Ecosystem.PACKAGIST),
        ("Ruby", Ecosystem.RUBYGEMS),
        ("Kotlin", Ecosystem.MAVEN),
        ("C#", Ecosystem.NUGET),
        ("C", None),
        ("C++", None),
        ("Swift", None),
        ("Shell", None),
    ],
)
def test_ecosystem_for_language(name: str, expected: Ecosystem | None) -> None:
    assert ecosystem_for_language(name) == expected
