"""Parseurs Python : manifestes, lockfiles, lien manifeste ↔ lockfile."""

import json

import pytest

from forceupdate import parsers
from forceupdate.detect.manifests import find_projects
from forceupdate.models import Dependency, Ecosystem, Location, Notice, Project, Scope
from forceupdate.parsers.base import ParseError
from forceupdate.parsers.python import (
    REASON_GIT,
    REASON_LOCAL,
    REASON_URL,
    REASON_WORKSPACE,
    LockedPackage,
    installed_version,
    parse_pdm_lock,
    parse_pipfile,
    parse_pipfile_lock,
    parse_poetry_lock,
    parse_pyproject_toml,
    parse_requirements_txt,
    parse_setup_cfg,
    parse_uv_lock,
)


def summary(dependencies: list[Dependency]) -> list[tuple[str, str, str | None, Scope]]:
    return [(d.name, d.constraint, d.installed, d.scope) for d in dependencies]


def assert_locations(dependencies: list[Dependency], content: str) -> None:
    """Chaque emplacement donné retombe exactement sur la contrainte."""
    for dependency in dependencies:
        if dependency.location is not None:
            assert dependency.location.extract(content) == dependency.constraint, dependency


def parse(files: dict[str, str], path: str = ".") -> Project:
    """Le projet ``path`` de ``files``, avec ses dépendances lues."""
    projects, _ = find_projects(files, include_tests=True)
    project = next(p for p in projects if p.path == path)
    parsers.parse_project(project, files.get)
    return project


def directs(project: Project) -> list[Dependency]:
    return [d for d in project.dependencies if d.direct]


def transitives(project: Project) -> list[Dependency]:
    return [d for d in project.dependencies if not d.direct]


# ---------------------------------------------------------------------------
# Repris de reference/argos_sca_parsers_tests.py, adaptés : plus de « version »
# devinée ni de « pinned », mais la contrainte telle qu'écrite ; un lockfile
# invalide lève ParseError au lieu de rendre une liste vide.
# ---------------------------------------------------------------------------


class TestParseRequirementsTxt:
    def test_pinned(self) -> None:
        deps = parse_requirements_txt("requirements.txt", "flask==2.0.1\nrequests==2.31.0\n")
        assert [(d.name, d.constraint) for d in deps] == [
            ("flask", "==2.0.1"),
            ("requests", "==2.31.0"),
        ]
        assert all(d.ecosystem is Ecosystem.PYPI and d.direct and d.installed is None for d in deps)

    def test_unpinned(self) -> None:
        deps = parse_requirements_txt("requirements.txt", "requests>=2.25.0\nnumpy\n")
        assert [(d.name, d.constraint) for d in deps] == [("requests", ">=2.25.0"), ("numpy", "")]

    def test_skips_comments_and_flags(self) -> None:
        content = "# Comment\n-e .\n--extra-index-url https://foo\nrequests==2.31.0\n"
        deps = parse_requirements_txt("requirements.txt", content)
        assert [d.name for d in deps] == ["requests"]

    def test_environment_marker_stripped(self) -> None:
        content = "requests==2.31.0 ; python_version >= '3.8'\n"
        deps = parse_requirements_txt("requirements.txt", content)
        assert [d.constraint for d in deps] == ["==2.31.0"]

    def test_dev_scope_from_filename(self) -> None:
        deps = parse_requirements_txt("requirements-dev.txt", "pytest==8.0.0\n")
        assert deps[0].scope is Scope.DEV


class TestParsePipfileLock:
    def test_default_and_develop_sections(self) -> None:
        content = json.dumps(
            {
                "default": {"flask": {"version": "==2.0.1"}},
                "develop": {"pytest": {"version": "==7.0.0"}},
            }
        )
        lock = parse_pipfile_lock("Pipfile.lock", content)
        assert [(p.name, p.version, p.scope) for p in lock.packages] == [
            ("flask", "2.0.1", Scope.RUNTIME),
            ("pytest", "7.0.0", Scope.DEV),
        ]

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(ParseError, match="JSON invalide"):
            parse_pipfile_lock("Pipfile.lock", "{invalid")


class TestParsePoetryLock:
    def test_package_list(self) -> None:
        content = """
[[package]]
name = "requests"
version = "2.31.0"
category = "main"

[[package]]
name = "pytest"
version = "8.0.0"
category = "dev"
""".strip()
        lock = parse_poetry_lock("poetry.lock", content)
        assert [(p.name, p.version, p.scope) for p in lock.packages] == [
            ("requests", "2.31.0", Scope.RUNTIME),
            ("pytest", "8.0.0", Scope.DEV),
        ]


class TestParsePyprojectToml:
    def test_pep621_dependencies(self) -> None:
        content = """
[project]
name = "myapp"
dependencies = [
    "requests==2.31.0",
    "flask>=2.0",
]
[project.optional-dependencies]
dev = ["pytest==8.0.0"]
"""
        deps = parse_pyproject_toml("pyproject.toml", content)
        assert summary(deps) == [
            ("requests", "==2.31.0", None, Scope.RUNTIME),
            ("flask", ">=2.0", None, Scope.RUNTIME),
            ("pytest", "==8.0.0", None, Scope.DEV),
        ]
        assert_locations(deps, content)

    def test_poetry_section(self) -> None:
        content = """
[tool.poetry]
name = "myapp"

[tool.poetry.dependencies]
python = "^3.10"
requests = "2.31.0"

[tool.poetry.dev-dependencies]
pytest = "8.0.0"
"""
        deps = parse_pyproject_toml("pyproject.toml", content)
        assert summary(deps) == [
            ("requests", "2.31.0", None, Scope.RUNTIME),
            ("pytest", "8.0.0", None, Scope.DEV),
        ]
        assert_locations(deps, content)


# ---------------------------------------------------------------------------
# requirements.txt
# ---------------------------------------------------------------------------

REQUIREMENTS = """\
flask==2.0.1
  requests >= 2.25, < 3  # client HTTP
numpy ; python_version >= '3.9'
uvicorn[standard] (>=0.20)
Django_REST.framework~=3.14
"""


class TestRequirementsLocations:
    def test_each_constraint_has_its_exact_location(self) -> None:
        deps = parse_requirements_txt("requirements.txt", REQUIREMENTS)
        assert [(d.name, d.constraint, d.location) for d in deps] == [
            ("flask", "==2.0.1", Location(line=1, column=5, end_column=12)),
            ("requests", ">= 2.25, < 3", Location(line=2, column=11, end_column=23)),
            ("numpy", "", Location(line=3, column=6, end_column=6)),
            ("uvicorn", ">=0.20", Location(line=4, column=19, end_column=25)),
            ("django-rest-framework", "~=3.14", Location(line=5, column=21, end_column=27)),
        ]
        assert_locations(deps, REQUIREMENTS)

    def test_crlf_does_not_change_locations(self) -> None:
        content = REQUIREMENTS.replace("\n", "\r\n")
        lf = parse_requirements_txt("requirements.txt", REQUIREMENTS)
        crlf = parse_requirements_txt("requirements.txt", content)
        assert [d.location for d in crlf] == [d.location for d in lf]
        assert_locations(crlf, content)

    def test_continued_lines(self) -> None:
        content = (
            "pytest==8.0.0 \\\n"
            "    --hash=sha256:50fb9cbe836c3f20f0dfa99c565201fb75dc54c8d76373cd1bde06b06657bdb6\n"
            "requests \\\n"
            ">=2.0\n"
        )
        deps = parse_requirements_txt("requirements.txt", content)
        assert [(d.name, d.constraint, d.location) for d in deps] == [
            ("pytest", "==8.0.0", Location(line=1, column=6, end_column=13)),
            # La contrainte est sur la ligne suivante : on ne sait pas la situer.
            ("requests", ">=2.0", None),
        ]


def test_requirements_urls_and_paths() -> None:
    content = """\
mylib @ git+https://github.com/x/mylib.git@v1.0
-e git+https://github.com/x/other.git#egg=Other_Lib
local @ file:///tmp/local
archive @ https://example.org/archive-1.0.tar.gz
https://example.org/unnamed-1.0.tar.gz
./libs/local-lib
-e .
"""
    deps = parse_requirements_txt("requirements.txt", content)
    assert [(d.name, d.constraint, d.location, d.unverifiable_reason) for d in deps] == [
        ("mylib", "", None, REASON_GIT),
        ("other-lib", "", None, REASON_GIT),
        ("local", "", None, REASON_LOCAL),
        ("archive", "", None, REASON_URL),
    ]


# ---------------------------------------------------------------------------
# pyproject.toml
# ---------------------------------------------------------------------------

PYPROJECT = """\
[project]
name = "My_App"
dependencies = [
    "requests>=2.31,<3",
    "httpx[http2] >=0.27 ; python_version >= '3.11'",
    "numpy",
    "mylib @ git+https://github.com/x/mylib.git",
    "my-app[extra]",
]

[project.optional-dependencies]
test = ["pytest>=8"]
server = ["uvicorn[standard]>=0.30"]

[dependency-groups]
dev = ["ruff>=0.6", {include-group = "test"}]
docs = ["mkdocs"]
gpu = ["torch>=2"]

[tool.uv]
dev-dependencies = ["mypy>=1.10"]

[build-system]
requires = ["hatchling>=1.27"]
"""


class TestPyproject:
    def test_all_sections_in_order(self) -> None:
        deps = parse_pyproject_toml("pyproject.toml", PYPROJECT)
        assert summary(deps) == [
            ("requests", ">=2.31,<3", None, Scope.RUNTIME),
            ("httpx", ">=0.27", None, Scope.RUNTIME),
            ("numpy", "", None, Scope.RUNTIME),
            ("mylib", "", None, Scope.RUNTIME),
            ("pytest", ">=8", None, Scope.DEV),
            ("uvicorn", ">=0.30", None, Scope.OPTIONAL),
            ("ruff", ">=0.6", None, Scope.DEV),
            ("mkdocs", "", None, Scope.DEV),
            ("torch", ">=2", None, Scope.OPTIONAL),
            ("mypy", ">=1.10", None, Scope.DEV),
            ("hatchling", ">=1.27", None, Scope.BUILD),
        ]
        assert_locations(deps, PYPROJECT)
        assert deps[1].location == Location(line=5, column=18, end_column=24)
        assert deps[2].location == Location(line=6, column=10, end_column=10)
        assert deps[3].location is None
        assert deps[3].unverifiable_reason == REASON_GIT
        assert all(d.file == "pyproject.toml" and d.direct for d in deps)

    def test_poetry(self) -> None:
        content = """\
[tool.poetry]
name = "app"

[tool.poetry.dependencies]
python = "^3.11"
requests = "^2.31"
click = { version = "^8.1", optional = true, extras = ["x"] }
PyYAML = "6.0.2"
foo = [
    { version = "<2", python = "<3.12" },
    { version = "^2", python = ">=3.12" },
]
lib = { git = "https://github.com/x/lib.git", branch = "main" }
local = { path = "../local", develop = true }
private = { version = "^1.0", source = "corp" }

[tool.poetry.dev-dependencies]
black = "^24"

[tool.poetry.group.test.dependencies]
pytest = "^8.0"

[tool.poetry.group.ml]
optional = true

[tool.poetry.group.ml.dependencies]
torch = ">=2"
"""
        deps = parse_pyproject_toml("pyproject.toml", content)
        assert [
            (*row, d.unverifiable_reason) for row, d in zip(summary(deps), deps, strict=True)
        ] == [
            ("requests", "^2.31", None, Scope.RUNTIME, None),
            ("click", "^8.1", None, Scope.OPTIONAL, None),
            ("pyyaml", "6.0.2", None, Scope.RUNTIME, None),
            ("foo", "<2", None, Scope.RUNTIME, None),
            ("foo", "^2", None, Scope.RUNTIME, None),
            ("lib", "", None, Scope.RUNTIME, REASON_GIT),
            ("local", "", None, Scope.RUNTIME, REASON_LOCAL),
            ("private", "^1.0", None, Scope.RUNTIME, "vient de l'index « corp », pas de PyPI"),
            ("black", "^24", None, Scope.DEV, None),
            ("pytest", "^8.0", None, Scope.DEV, None),
            ("torch", ">=2", None, Scope.OPTIONAL, None),
        ]
        assert_locations(deps, content)
        assert [d.location is not None for d in deps] == [True] * 5 + [False] * 2 + [True] * 4

    def test_poetry_2_completes_project_dependencies(self) -> None:
        content = """\
[project]
name = "app"
dependencies = ["requests>=2", "lib"]

[tool.poetry.dependencies]
lib = { git = "https://github.com/x/lib.git" }
"""
        deps = parse_pyproject_toml("pyproject.toml", content)
        assert [(d.name, d.constraint, d.unverifiable_reason) for d in deps] == [
            ("requests", ">=2", None),
            ("lib", "", REASON_GIT),
        ]

    def test_uv_sources_make_dependencies_unverifiable(self) -> None:
        content = """\
[project]
dependencies = ["a", "b>=1", "c", "d", "e", "f"]

[tool.uv.sources]
a = { workspace = true }
b = { git = "https://github.com/x/b.git" }
c = { path = "../c" }
d = { url = "https://example.org/d-1.0-py3-none-any.whl" }
E = [{ index = "pytorch", marker = "sys_platform == 'linux'" }]
"""
        deps = parse_pyproject_toml("pyproject.toml", content)
        assert [(d.name, d.unverifiable_reason) for d in deps] == [
            ("a", REASON_WORKSPACE),
            ("b", REASON_GIT),
            ("c", REASON_LOCAL),
            ("d", REASON_URL),
            ("e", "vient de l'index « pytorch », pas de PyPI"),
            ("f", None),
        ]
        assert deps[1].location is not None  # la contrainte écrite reste réécrivable

    def test_pdm_dev_dependencies(self) -> None:
        content = '[tool.pdm.dev-dependencies]\nlint = ["ruff>=0.6"]\n'
        assert summary(parse_pyproject_toml("pyproject.toml", content)) == [
            ("ruff", ">=0.6", None, Scope.DEV)
        ]

    def test_invalid_toml_raises(self) -> None:
        with pytest.raises(ParseError, match="TOML invalide"):
            parse_pyproject_toml("pyproject.toml", "[project\n")

    def test_tool_config_only(self) -> None:
        assert parse_pyproject_toml("pyproject.toml", "[tool.ruff]\nline-length = 100\n") == []


# ---------------------------------------------------------------------------
# Pipfile, setup.cfg
# ---------------------------------------------------------------------------


def test_pipfile() -> None:
    content = """\
[[source]]
name = "pypi"
url = "https://pypi.org/simple"

[packages]
requests = "*"
Flask = {version = ">=2.0", extras = ["dotenv"]}
lib = {git = "https://github.com/x/lib.git", ref = "main"}
local = {path = ".", editable = true}
corp = {version = "==1.0", index = "corp"}

[dev-packages]
pytest = "==8.3.3"

[docs]
mkdocs = "*"

[requires]
python_version = "3.12"
"""
    deps = parse_pipfile("Pipfile", content)
    assert [(*row, d.unverifiable_reason) for row, d in zip(summary(deps), deps, strict=True)] == [
        ("requests", "*", None, Scope.RUNTIME, None),
        ("flask", ">=2.0", None, Scope.RUNTIME, None),
        ("lib", "", None, Scope.RUNTIME, REASON_GIT),
        ("local", "", None, Scope.RUNTIME, REASON_LOCAL),
        ("corp", "==1.0", None, Scope.RUNTIME, "vient de l'index « corp », pas de PyPI"),
        ("pytest", "==8.3.3", None, Scope.DEV, None),
        ("mkdocs", "*", None, Scope.DEV, None),
    ]
    assert_locations(deps, content)
    assert deps[0].location == Location(line=6, column=12, end_column=13)


def test_setup_cfg() -> None:
    content = """\
[metadata]
name = app

[options]
packages = find:
install_requires =
    requests>=2.25
    # commentaire
    click ; python_version >= "3.8"
setup_requires = setuptools_scm
tests_require = pytest>=8; coverage

[options.extras_require]
yaml = PyYAML>=6
Dev =
    ruff
"""
    deps = parse_setup_cfg("setup.cfg", content)
    assert [
        (*row, d.location.line if d.location else None)
        for row, d in zip(summary(deps), deps, strict=True)
    ] == [
        ("requests", ">=2.25", None, Scope.RUNTIME, 7),
        ("click", "", None, Scope.RUNTIME, 9),
        ("setuptools-scm", "", None, Scope.BUILD, 10),
        ("pytest", ">=8", None, Scope.DEV, 11),
        ("coverage", "", None, Scope.DEV, 11),
        ("pyyaml", ">=6", None, Scope.OPTIONAL, 14),
        ("ruff", "", None, Scope.DEV, 16),
    ]
    assert_locations(deps, content)


# ---------------------------------------------------------------------------
# Lockfiles
# ---------------------------------------------------------------------------


def test_uv_lock() -> None:
    content = """\
version = 1
requires-python = ">=3.11"

[[package]]
name = "app"
version = "0.1.0"
source = { editable = "." }
dependencies = [{ name = "HTTPX", extra = ["HTTP2"] }]

[[package]]
name = "httpx"
version = "0.28.1"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "anyio" }]

[package.optional-dependencies]
http2 = [{ name = "h2" }]

[[package]]
name = "lib"
version = "1.0.0"
source = { git = "https://github.com/x/lib.git?rev=main#abc" }
"""
    lock = parse_uv_lock("uv.lock", content)
    assert lock.graph and lock.shared
    assert lock.packages == (
        LockedPackage(
            name="app",
            version="0.1.0",
            dependencies=(("httpx", frozenset({"http2"})),),
            local=True,
            unverifiable_reason=REASON_LOCAL,
        ),
        LockedPackage(
            name="httpx",
            version="0.28.1",
            dependencies=(("anyio", frozenset()),),
            extras={"http2": (("h2", frozenset()),)},
        ),
        LockedPackage(name="lib", version="1.0.0", unverifiable_reason=REASON_GIT),
    )
    assert installed_version(lock, "httpx") == "0.28.1"
    assert installed_version(lock, "absent") is None


def test_uv_lock_keeps_the_highest_of_forked_versions() -> None:
    content = """\
[[package]]
name = "numpy"
version = "1.26.4"
source = { registry = "https://pypi.org/simple" }
resolution-markers = ["python_full_version < '3.10'"]

[[package]]
name = "numpy"
version = "2.1.0"
source = { registry = "https://pypi.org/simple" }
"""
    assert installed_version(parse_uv_lock("uv.lock", content), "numpy") == "2.1.0"


def test_installed_version_compares_versions_not_strings() -> None:
    content = """\
[[package]]
name = "numpy"
version = "1.10.0"

[[package]]
name = "numpy"
version = "1.9.0"
"""
    assert installed_version(parse_uv_lock("uv.lock", content), "numpy") == "1.10.0"
    # Aucune version lisible : la première.
    unreadable = '[[package]]\nname = "lib"\nversion = "main-branch"\n'
    assert installed_version(parse_uv_lock("uv.lock", unreadable), "lib") == "main-branch"


def test_forked_transitives_are_in_version_order() -> None:
    """Les deux versions d'une fourche de uv.lock sont des transitives, 9.0.0 avant 10.0.0
    (en texte, « 10.0.0 » passerait devant)."""
    registry = 'source = { registry = "https://pypi.org/simple" }'
    lock = f"""\
version = 1

[[package]]
name = "app"
version = "0.1.0"
source = {{ virtual = "." }}
dependencies = [{{ name = "pandas" }}]

[[package]]
name = "pandas"
version = "2.0.0"
{registry}
dependencies = [
    {{ name = "numpy", version = "10.0.0", marker = "python_full_version >= '3.10'" }},
    {{ name = "numpy", version = "9.0.0", marker = "python_full_version < '3.10'" }},
]

[[package]]
name = "numpy"
version = "10.0.0"
{registry}
resolution-markers = ["python_full_version >= '3.10'"]

[[package]]
name = "numpy"
version = "9.0.0"
{registry}
resolution-markers = ["python_full_version < '3.10'"]
"""
    pyproject = '[project]\nname = "app"\nversion = "0.1.0"\ndependencies = ["pandas"]\n'
    project = parse({"pyproject.toml": pyproject, "uv.lock": lock})
    assert [(d.name, d.installed) for d in transitives(project)] == [
        ("numpy", "9.0.0"),
        ("numpy", "10.0.0"),
    ]


def test_poetry_lock_groups_optional_dependencies_and_sources() -> None:
    content = """\
[[package]]
name = "requests"
version = "2.31.0"
groups = ["main"]

[package.dependencies]
certifi = ">=2017.4.17"
PySocks = {version = ">=1.5.6,!=1.5.7", optional = true}
urllib3 = [
    {version = ">=1.21.1,<2", markers = "python_version < \\"3.10\\""},
    {version = ">=1.21.1,<3", markers = "python_version >= \\"3.10\\""},
]

[package.extras]
socks = ["PySocks (>=1.5.6,!=1.5.7)"]

[[package]]
name = "pytest"
version = "8.0.0"
groups = ["dev"]

[[package]]
name = "lib"
version = "1.0"
groups = ["main"]

[package.source]
type = "git"
url = "https://github.com/x/lib.git"
reference = "main"
resolved_reference = "abc"

[metadata]
lock-version = "2.1"
"""
    lock = parse_poetry_lock("poetry.lock", content)
    assert lock.graph and not lock.shared
    requests, pytest_, lib = lock.packages
    assert requests.dependencies == (("certifi", frozenset()), ("urllib3", frozenset()))
    assert requests.extras == {"socks": (("pysocks", frozenset()),)}
    assert (requests.scope, pytest_.scope, lib.scope) == (Scope.RUNTIME, Scope.DEV, Scope.RUNTIME)
    assert lib.unverifiable_reason == REASON_GIT


def test_poetry_lock_without_category_or_groups() -> None:
    content = '[[package]]\nname = "requests"\nversion = "2.31.0"\n'
    assert parse_poetry_lock("poetry.lock", content).packages[0].scope is None


def test_pdm_lock() -> None:
    content = """\
[metadata]
groups = ["default", "dev"]
lock_version = "4.5.0"

[[package]]
name = "requests"
version = "2.32.3"
groups = ["default"]
dependencies = ["certifi>=2017.4.17"]

[[package]]
name = "pytest"
version = "8.3.3"
groups = ["dev"]

[[package]]
name = "mylib"
version = "0.1.0"
groups = ["default"]
git = "https://github.com/x/mylib.git"
revision = "abc"
"""
    lock = parse_pdm_lock("pdm.lock", content)
    assert [(p.name, p.version, p.scope, p.unverifiable_reason) for p in lock.packages] == [
        ("requests", "2.32.3", Scope.RUNTIME, None),
        ("pytest", "8.3.3", Scope.DEV, None),
        ("mylib", "0.1.0", Scope.RUNTIME, REASON_GIT),
    ]


# ---------------------------------------------------------------------------
# Un projet : manifeste ↔ lockfile
# ---------------------------------------------------------------------------

UV_PYPROJECT = """\
[project]
name = "app"
dependencies = ["httpx[http2]>=0.27"]

[dependency-groups]
dev = ["pytest>=8"]

[build-system]
requires = ["idna"]
"""

UV_LOCK = """\
[[package]]
name = "app"
version = "0.1.0"
source = { editable = "." }
dependencies = [{ name = "httpx", extra = ["http2"] }]

[package.dev-dependencies]
dev = [{ name = "pytest" }]

[[package]]
name = "httpx"
version = "0.28.1"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "anyio" }]

[package.optional-dependencies]
http2 = [{ name = "h2" }]
brotli = [{ name = "brotli" }]

[[package]]
name = "anyio"
version = "4.4.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "idna" }]

[[package]]
name = "idna"
version = "3.7"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "h2"
version = "4.1.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "brotli"
version = "1.1.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "pytest"
version = "8.3.3"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "pluggy" }, { name = "idna" }, { name = "pytest" }]

[[package]]
name = "pluggy"
version = "1.5.0"
source = { registry = "https://pypi.org/simple" }
"""


class TestLink:
    def test_directs_get_the_installed_version_and_the_rest_is_transitive(self) -> None:
        project = parse({"pyproject.toml": UV_PYPROJECT, "uv.lock": UV_LOCK})
        assert summary(directs(project)) == [
            ("httpx", ">=0.27", "0.28.1", Scope.RUNTIME),
            ("pytest", ">=8", "8.3.3", Scope.DEV),
            # Les dépendances de build ne sont pas figées par uv.lock.
            ("idna", "", None, Scope.BUILD),
        ]
        # brotli : extra non demandé, donc pas tiré ; idna : tiré par anyio (runtime)
        # et par pytest (dev), il reste runtime. Le graphe a un cycle (pytest).
        assert summary(transitives(project)) == [
            ("anyio", "", "4.4.0", Scope.RUNTIME),
            ("h2", "", "4.1.0", Scope.RUNTIME),
            ("idna", "", "3.7", Scope.RUNTIME),
            ("pluggy", "", "1.5.0", Scope.DEV),
        ]
        assert all(d.file == "uv.lock" and d.location is None for d in transitives(project))
        assert project.notices == []

    def test_poetry_lock_without_category_takes_scopes_from_the_groups(self) -> None:
        pyproject = """\
[tool.poetry]
name = "app"

[tool.poetry.dependencies]
python = "^3.11"
requests = "^2.31"

[tool.poetry.group.dev.dependencies]
pytest = "^8.0"
"""
        lock = """\
[[package]]
name = "requests"
version = "2.31.0"

[package.dependencies]
certifi = ">=2017.4.17"

[[package]]
name = "certifi"
version = "2024.2.2"

[[package]]
name = "pytest"
version = "8.0.0"

[package.dependencies]
pluggy = ">=1.3"

[[package]]
name = "pluggy"
version = "1.4.0"

[[package]]
name = "orphan"
version = "1.0"
"""
        project = parse({"pyproject.toml": pyproject, "poetry.lock": lock})
        assert summary(directs(project)) == [
            ("requests", "^2.31", "2.31.0", Scope.RUNTIME),
            ("pytest", "^8.0", "8.0.0", Scope.DEV),
        ]
        assert summary(transitives(project)) == [
            ("certifi", "", "2024.2.2", Scope.RUNTIME),
            # Pas dans le graphe : le lockfile est au projet, il reste listé.
            ("orphan", "", "1.0", Scope.RUNTIME),
            ("pluggy", "", "1.4.0", Scope.DEV),
        ]

    def test_pipfile_and_its_lock(self) -> None:
        lock = json.dumps(
            {
                "_meta": {},
                "default": {"requests": {"version": "==2.32.3"}, "idna": {"version": "==3.7"}},
                "develop": {"pytest": {"version": "==8.3.3"}, "idna": {"version": "==3.7"}},
            }
        )
        project = parse(
            {
                "Pipfile": '[packages]\nrequests = "*"\n[dev-packages]\npytest = "*"\n',
                "Pipfile.lock": lock,
            }
        )
        assert summary(project.dependencies) == [
            ("requests", "*", "2.32.3", Scope.RUNTIME),
            ("pytest", "*", "8.3.3", Scope.DEV),
            ("idna", "", "3.7", Scope.RUNTIME),
        ]

    def test_tool_table_chooses_the_lockfile(self) -> None:
        files = {
            "pyproject.toml": (
                '[tool.poetry]\nname = "app"\n[tool.poetry.dependencies]\nrequests = "*"\n'
            ),
            "poetry.lock": '[[package]]\nname = "requests"\nversion = "2.31.0"\n',
            "uv.lock": '[[package]]\nname = "requests"\nversion = "1.0"\n',
        }
        project = parse(files)
        assert summary(project.dependencies) == [("requests", "*", "2.31.0", Scope.RUNTIME)]
        assert project.notices == [
            Notice(
                file="uv.lock",
                message="pas lu : poetry.lock est le lockfile pris pour pyproject.toml.",
            )
        ]

    def test_a_lockfile_alone_gives_transitives(self) -> None:
        project = parse({"poetry.lock": '[[package]]\nname = "requests"\nversion = "2.31.0"\n'})
        assert summary(project.dependencies) == [("requests", "", "2.31.0", Scope.RUNTIME)]
        assert not project.dependencies[0].direct

    def test_invalid_files_give_notices(self) -> None:
        files = {
            "pyproject.toml": "[project\n",
            "Pipfile": '[packages]\nflask = "*"\n',
            "Pipfile.lock": "{",
        }
        project = parse(files)
        assert summary(project.dependencies) == [("flask", "*", None, Scope.RUNTIME)]
        assert [notice.file for notice in project.notices] == ["pyproject.toml", "Pipfile.lock"]
        assert project.notices[0].message.startswith("TOML invalide")

    def test_invalid_requirement_gives_a_notice(self) -> None:
        project = parse({"pyproject.toml": '[project]\ndependencies = ["flask >= = 2"]\n'})
        assert project.dependencies == []
        assert project.notices == [
            Notice(
                file="pyproject.toml", message="« flask >= = 2 » n'est pas une dépendance valide."
            )
        ]

    def test_unreadable_file_gives_a_notice(self) -> None:
        projects, _ = find_projects(["requirements.txt"])
        parsers.parse_project(projects[0], lambda path: None)
        assert projects[0].notices == [
            Notice(file="requirements.txt", message="introuvable, illisible ou trop gros : pas lu.")
        ]

    def test_setup_py_is_not_read(self) -> None:
        project = parse({"setup.py": "from setuptools import setup\nsetup()\n"})
        assert project.dependencies == []
        assert project.notices == [
            Notice(
                file="setup.py",
                message="pas lu : il faudrait l'exécuter pour connaître ses dépendances.",
            )
        ]

    def test_ecosystems_not_read_yet_give_a_notice(self) -> None:
        project = parse({"Cargo.toml": "", "requirements.txt": "flask\n"})
        assert [d.name for d in project.dependencies] == ["flask"]
        assert project.notices == [
            Notice(
                file="Cargo.toml", message="dépendances crates.io pas encore lues par forceupdate."
            )
        ]


# ---------------------------------------------------------------------------
# Workspace uv
# ---------------------------------------------------------------------------

WORKSPACE = {
    "pyproject.toml": """\
[project]
name = "root"
dependencies = ["shared"]

[tool.uv.sources]
shared = { workspace = true }

[tool.uv.workspace]
members = ["packages/*", "libs/**"]
exclude = ["packages/old"]
""",
    "uv.lock": """\
[[package]]
name = "root"
version = "0.1.0"
source = { virtual = "." }
dependencies = [{ name = "shared" }]

[[package]]
name = "shared"
version = "0.2.0"
source = { editable = "packages/shared" }
dependencies = [{ name = "idna" }]

[[package]]
name = "a"
version = "0.1.0"
source = { editable = "packages/a" }
dependencies = [{ name = "requests" }, { name = "shared" }]

[[package]]
name = "requests"
version = "2.32.3"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "certifi" }]

[[package]]
name = "certifi"
version = "2024.8.30"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "idna"
version = "3.10"
source = { registry = "https://pypi.org/simple" }
""",
    "packages/shared/pyproject.toml": '[project]\nname = "shared"\ndependencies = ["idna"]\n',
    "packages/a/pyproject.toml": (
        '[project]\nname = "a"\ndependencies = ["shared", "requests>=2"]\n'
    ),
    "packages/old/pyproject.toml": '[project]\nname = "old"\ndependencies = ["requests<2"]\n',
    "libs/deep/x/pyproject.toml": '[project]\nname = "x"\ndependencies = ["idna"]\n',
    "tools/pyproject.toml": '[project]\nname = "tools"\ndependencies = ["click"]\n',
}


class TestUvWorkspace:
    def test_members_use_the_root_lockfile(self) -> None:
        project = parse(WORKSPACE, "packages/a")
        assert project.lockfiles == ["uv.lock"]
        assert [
            (*row, d.unverifiable_reason)
            for row, d in zip(summary(directs(project)), directs(project), strict=True)
        ] == [
            # La source « workspace » vient de la racine.
            ("shared", "", "0.2.0", Scope.RUNTIME, REASON_WORKSPACE),
            ("requests", ">=2", "2.32.3", Scope.RUNTIME, None),
        ]
        # Seuls les paquets que tire ce membre ; idna vient de « shared ».
        assert summary(transitives(project)) == [
            ("certifi", "", "2024.8.30", Scope.RUNTIME),
            ("idna", "", "3.10", Scope.RUNTIME),
        ]

    def test_the_root_only_gets_what_it_pulls(self) -> None:
        project = parse(WORKSPACE)
        assert summary(project.dependencies) == [
            ("shared", "", "0.2.0", Scope.RUNTIME),
            ("idna", "", "3.10", Scope.RUNTIME),
        ]

    @pytest.mark.parametrize("path", ["packages/old", "tools"])
    def test_non_members_lose_the_lockfile(self, path: str) -> None:
        project = parse(WORKSPACE, path)
        assert project.lockfiles == []
        assert all(d.installed is None for d in project.dependencies)
        assert project.notices == []

    def test_double_star_reaches_deep_members(self) -> None:
        project = parse(WORKSPACE, "libs/deep/x")
        assert project.lockfiles == ["uv.lock"]
        assert summary(project.dependencies) == [("idna", "", "3.10", Scope.RUNTIME)]

    def test_no_workspace_table_means_no_member(self) -> None:
        files = {
            "pyproject.toml": '[project]\nname = "root"\n',
            "uv.lock": (
                '[[package]]\nname = "idna"\nversion = "3.10"\nsource = { registry = "x" }\n'
            ),
            "sub/pyproject.toml": '[project]\nname = "sub"\ndependencies = ["idna"]\n',
        }
        project = parse(files, "sub")
        assert project.lockfiles == []
        assert summary(project.dependencies) == [("idna", "", None, Scope.RUNTIME)]


# ---------------------------------------------------------------------------
# pip et pip-tools
# ---------------------------------------------------------------------------


class TestRequirementsProject:
    def test_pip_tools_compiled_txt_gives_versions_and_transitives(self) -> None:
        files = {
            "requirements.in": "flask>=2\n",
            "requirements.txt": (
                "flask==3.0.0\n    # via -r requirements.in\nwerkzeug==3.0.1\n    # via flask\n"
            ),
        }
        project = parse(files)
        assert project.manifests == ["requirements.in"]
        assert project.lockfiles == ["requirements.txt"]
        assert [
            (d.name, d.constraint, d.installed, d.direct, d.file, d.location)
            for d in project.dependencies
        ] == [
            (
                "flask",
                ">=2",
                "3.0.0",
                True,
                "requirements.in",
                Location(line=1, column=5, end_column=8),
            ),
            (
                "werkzeug",
                "==3.0.1",
                "3.0.1",
                False,
                "requirements.txt",
                Location(line=3, column=8, end_column=15),
            ),
        ]

    def test_includes_are_followed_once_even_in_a_cycle(self) -> None:
        files = {
            "requirements.txt": "-r requirements-dev.txt\n--requirement=base/common.txt\nflask\n",
            "requirements-dev.txt": "-r requirements.txt\npytest\n",
            "base/common.txt": "requests\n",
        }
        project = parse(files)
        # requirements.txt tire requirements-dev.txt : tout est installé avec lui.
        assert [(d.name, d.scope, d.file) for d in project.dependencies] == [
            ("pytest", Scope.RUNTIME, "requirements-dev.txt"),
            ("flask", Scope.RUNTIME, "requirements.txt"),
            ("requests", Scope.RUNTIME, "base/common.txt"),
        ]

    def test_dev_file_including_runtime_file(self) -> None:
        files = {
            "requirements.txt": "flask\n",
            "requirements-dev.txt": "-r requirements.txt\npytest\n",
        }
        project = parse(files)
        assert [(d.name, d.scope, d.file) for d in project.dependencies] == [
            ("pytest", Scope.DEV, "requirements-dev.txt"),
            ("flask", Scope.RUNTIME, "requirements.txt"),
        ]

    def test_constraints_pin_directs_and_add_transitives(self) -> None:
        files = {
            "requirements.txt": "-c constraints.txt\nnumpy\n",
            "requirements-dev.txt": "-r requirements.txt\npytest\n",
            "constraints.txt": "numpy==1.26.4\ncertifi==2024.2.2\npytest>=8\n",
        }
        project = parse(files)
        assert [
            (d.name, d.constraint, d.installed, d.direct, d.scope, d.file)
            for d in project.dependencies
        ] == [
            ("pytest", "", None, True, Scope.DEV, "requirements-dev.txt"),
            ("numpy", "", "1.26.4", True, Scope.RUNTIME, "requirements.txt"),
            ("certifi", "==2024.2.2", "2024.2.2", False, Scope.RUNTIME, "constraints.txt"),
        ]

    def test_missing_and_outside_includes_give_notices(self) -> None:
        files = {
            "requirements.txt": "-r missing.txt\n-r ../other.txt\n-c https://example.org/c.txt\nflask\n"
        }
        project = parse(files)
        assert [d.name for d in project.dependencies] == ["flask"]
        assert project.notices == [
            Notice(
                file="requirements.txt",
                message="« -r ../other.txt » : hors du dossier analysé, pas suivi.",
            ),
            Notice(
                file="requirements.txt",
                message="« -c https://example.org/c.txt » : hors du dossier analysé, pas suivi.",
            ),
            Notice(file="missing.txt", message="introuvable, illisible ou trop gros : pas lu."),
        ]

    def test_invalid_line_gives_a_notice(self) -> None:
        project = parse({"requirements.txt": "flask\nnot a requirement!\n"})
        assert [d.name for d in project.dependencies] == ["flask"]
        assert project.notices == [
            Notice(
                file="requirements.txt",
                message="ligne 2 : « not a requirement! » n'est pas une dépendance valide.",
            )
        ]
