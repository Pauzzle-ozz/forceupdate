"""RÉFÉRENCE — tests des parseurs SCA repris d'Argos (commit 52c714b7).

Copiés à l'identique depuis tests/test_modules/test_sast_dependency.py ; seuls l'en-tête,
l'import (qui pointe sur argos_sca_parsers au lieu de sechunter) et le skip des
tests OSV ont été ajoutés. Ils servent d'exemples de vrais fichiers de
dépendances et de filet quand on reprend un parseur.

Lancer depuis ce dossier :  python -m pytest argos_sca_parsers_tests.py
(nommé sans préfixe test_ pour que pytest ne le ramasse pas depuis la racine)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from argos_sca_parsers import (
    SCAComponent,
    ecosystem_for_manifest,
    parse_cargo_lock,
    parse_composer_json,
    parse_gemfile_lock,
    parse_go_mod,
    parse_go_sum,
    parse_manifest,
    parse_package_json,
    parse_package_lock_json,
    parse_pipfile_lock,
    parse_poetry_lock,
    parse_pom_xml,
    parse_pyproject_toml,
    parse_requirements_txt,
    parse_yarn_lock,
    query_osv_batch,
)


# ============================================================================
# Origine : tests/test_modules/test_sast_dependency.py  L53-L57  (commit 52c714b7)
# ============================================================================

def _write(tmp_path: Path, name: str, content: str) -> Path:
    fp = tmp_path / name
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(content, encoding="utf-8")
    return fp


# ============================================================================
# Origine : tests/test_modules/test_sast_dependency.py  L87-L416  (commit 52c714b7)
# ============================================================================

class TestParseRequirementsTxt:
    def test_pinned(self, tmp_path: Path) -> None:
        fp = _write(tmp_path, "requirements.txt", "flask==2.0.1\nrequests==2.31.0\n")
        comps = parse_requirements_txt(fp, fp.read_text())
        assert len(comps) == 2
        assert all(c.pinned for c in comps)
        assert comps[0].name == "flask"
        assert comps[0].version == "2.0.1"
        assert comps[0].ecosystem == "PyPI"

    def test_unpinned(self, tmp_path: Path) -> None:
        fp = _write(tmp_path, "requirements.txt", "requests>=2.25.0\nnumpy\n")
        comps = parse_requirements_txt(fp, fp.read_text())
        assert all(not c.pinned for c in comps)

    def test_skips_comments_and_flags(self, tmp_path: Path) -> None:
        fp = _write(
            tmp_path,
            "requirements.txt",
            "# Comment\n-e .\n--extra-index-url https://foo\nrequests==2.31.0\n",
        )
        comps = parse_requirements_txt(fp, fp.read_text())
        assert len(comps) == 1
        assert comps[0].name == "requests"

    def test_environment_marker_stripped(self, tmp_path: Path) -> None:
        fp = _write(tmp_path, "requirements.txt", "requests==2.31.0 ; python_version >= '3.8'\n")
        comps = parse_requirements_txt(fp, fp.read_text())
        assert len(comps) == 1
        assert comps[0].version == "2.31.0"

    def test_dev_scope_from_filename(self, tmp_path: Path) -> None:
        fp = _write(tmp_path, "requirements-dev.txt", "pytest==8.0.0\n")
        comps = parse_requirements_txt(fp, fp.read_text())
        assert comps[0].scope == "dev"


class TestParsePipfileLock:
    def test_default_and_develop_sections(self, tmp_path: Path) -> None:
        content = json.dumps(
            {
                "default": {"flask": {"version": "==2.0.1"}},
                "develop": {"pytest": {"version": "==7.0.0"}},
            }
        )
        fp = _write(tmp_path, "Pipfile.lock", content)
        comps = parse_pipfile_lock(fp, content)
        assert {c.name for c in comps} == {"flask", "pytest"}
        scopes = {c.name: c.scope for c in comps}
        assert scopes["flask"] == "runtime"
        assert scopes["pytest"] == "dev"

    def test_invalid_json_returns_empty(self, tmp_path: Path) -> None:
        fp = _write(tmp_path, "Pipfile.lock", "{invalid")
        comps = parse_pipfile_lock(fp, "{invalid")
        assert comps == []


class TestParsePoetryLock:
    def test_package_list(self, tmp_path: Path) -> None:
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
        fp = _write(tmp_path, "poetry.lock", content)
        comps = parse_poetry_lock(fp, content)
        assert len(comps) == 2
        assert {c.name for c in comps} == {"requests", "pytest"}
        assert all(c.pinned for c in comps)


class TestParsePyprojectToml:
    def test_pep621_dependencies(self, tmp_path: Path) -> None:
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
        fp = _write(tmp_path, "pyproject.toml", content)
        comps = parse_pyproject_toml(fp, content)
        names = {c.name for c in comps}
        assert "requests" in names
        assert "flask" in names
        assert "pytest" in names
        scopes = {c.name: c.scope for c in comps}
        assert scopes["pytest"] == "dev"

    def test_poetry_section(self, tmp_path: Path) -> None:
        content = """
[tool.poetry]
name = "myapp"

[tool.poetry.dependencies]
python = "^3.10"
requests = "2.31.0"

[tool.poetry.dev-dependencies]
pytest = "8.0.0"
"""
        fp = _write(tmp_path, "pyproject.toml", content)
        comps = parse_pyproject_toml(fp, content)
        names = {c.name for c in comps}
        assert "requests" in names
        assert "pytest" in names
        assert "python" not in names  # ignored


class TestParsePackageJson:
    def test_all_sections(self, tmp_path: Path) -> None:
        content = json.dumps(
            {
                "dependencies": {"express": "4.18.2"},
                "devDependencies": {"jest": "^29.0.0"},
                "peerDependencies": {"react": ">=18.0.0"},
            }
        )
        fp = _write(tmp_path, "package.json", content)
        comps = parse_package_json(fp, content)
        scopes = {c.name: c.scope for c in comps}
        assert scopes["express"] == "runtime"
        assert scopes["jest"] == "dev"
        assert scopes["react"] == "peer"
        pinned = {c.name: c.pinned for c in comps}
        assert pinned["express"] is True
        assert pinned["jest"] is False


class TestParsePackageLockJson:
    def test_v2_packages_section(self, tmp_path: Path) -> None:
        content = json.dumps(
            {
                "lockfileVersion": 2,
                "packages": {
                    "": {},
                    "node_modules/express": {"name": "express", "version": "4.18.2"},
                    "node_modules/lodash": {"name": "lodash", "version": "4.17.21", "dev": True},
                },
            }
        )
        fp = _write(tmp_path, "package-lock.json", content)
        comps = parse_package_lock_json(fp, content)
        assert {c.name for c in comps} == {"express", "lodash"}
        scopes = {c.name: c.scope for c in comps}
        assert scopes["lodash"] == "dev"

    def test_v1_fallback(self, tmp_path: Path) -> None:
        content = json.dumps(
            {
                "lockfileVersion": 1,
                "dependencies": {"express": {"version": "4.18.2"}},
            }
        )
        fp = _write(tmp_path, "package-lock.json", content)
        comps = parse_package_lock_json(fp, content)
        assert len(comps) == 1
        assert comps[0].name == "express"


class TestParseYarnLock:
    def test_basic(self, tmp_path: Path) -> None:
        content = """\
express@^4.18.0:
  version "4.18.2"
  resolved "https://..."

lodash@^4.17.21:
  version "4.17.21"
"""
        fp = _write(tmp_path, "yarn.lock", content)
        comps = parse_yarn_lock(fp, content)
        assert {c.name for c in comps} == {"express", "lodash"}


class TestParseGemfileLock:
    def test_specs_section(self, tmp_path: Path) -> None:
        content = """\
GEM
  remote: https://rubygems.org/
  specs:
    rails (7.1.0)
    nokogiri (1.15.4)
"""
        fp = _write(tmp_path, "Gemfile.lock", content)
        comps = parse_gemfile_lock(fp, content)
        assert {c.name for c in comps} == {"rails", "nokogiri"}
        assert all(c.pinned for c in comps)


class TestParseGoSum:
    def test_deduplicates_gomod_entries(self, tmp_path: Path) -> None:
        content = (
            "github.com/foo/bar v1.2.3 h1:abc=\n"
            "github.com/foo/bar v1.2.3/go.mod h1:def=\n"
            "github.com/baz/qux v4.5.6 h1:xyz=\n"
        )
        fp = _write(tmp_path, "go.sum", content)
        comps = parse_go_sum(fp, content)
        assert len(comps) == 2
        assert {c.name for c in comps} == {"github.com/foo/bar", "github.com/baz/qux"}


class TestParseGoMod:
    def test_require_block(self, tmp_path: Path) -> None:
        content = """\
module example.com/app

go 1.21

require (
    github.com/gin-gonic/gin v1.9.1
    github.com/gorilla/mux v1.8.1 // indirect
)

require github.com/stretchr/testify v1.8.4
"""
        fp = _write(tmp_path, "go.mod", content)
        comps = parse_go_mod(fp, content)
        names = {c.name for c in comps}
        assert "github.com/gin-gonic/gin" in names
        assert "github.com/gorilla/mux" in names
        assert "github.com/stretchr/testify" in names


class TestParseCargoLock:
    def test_package_list(self, tmp_path: Path) -> None:
        content = """\
[[package]]
name = "serde"
version = "1.0.189"

[[package]]
name = "tokio"
version = "1.35.0"
"""
        fp = _write(tmp_path, "Cargo.lock", content)
        comps = parse_cargo_lock(fp, content)
        assert {c.name for c in comps} == {"serde", "tokio"}


class TestParseComposerJson:
    def test_skips_php_and_ext(self, tmp_path: Path) -> None:
        content = json.dumps(
            {
                "require": {
                    "php": ">=8.1",
                    "ext-json": "*",
                    "symfony/http-kernel": "6.4.0",
                },
                "require-dev": {"phpunit/phpunit": "10.5.0"},
            }
        )
        fp = _write(tmp_path, "composer.json", content)
        comps = parse_composer_json(fp, content)
        names = {c.name for c in comps}
        assert "symfony/http-kernel" in names
        assert "phpunit/phpunit" in names
        assert "php" not in names
        assert "ext-json" not in names


class TestParsePomXml:
    def test_dependency_block(self, tmp_path: Path) -> None:
        content = """\
<project>
  <dependencies>
    <dependency>
      <groupId>org.springframework</groupId>
      <artifactId>spring-core</artifactId>
      <version>6.1.0</version>
    </dependency>
    <dependency>
      <groupId>junit</groupId>
      <artifactId>junit</artifactId>
      <version>${junit.version}</version>
    </dependency>
  </dependencies>
</project>
"""
        fp = _write(tmp_path, "pom.xml", content)
        comps = parse_pom_xml(fp, content)
        assert len(comps) == 2
        by_name = {c.name: c for c in comps}
        assert "org.springframework:spring-core" in by_name
        assert by_name["org.springframework:spring-core"].pinned is True
        assert by_name["junit:junit"].pinned is False  # ${...}


class TestParseManifestDispatcher:
    def test_unknown_returns_empty(self, tmp_path: Path) -> None:
        fp = _write(tmp_path, "readme.md", "hello")
        assert parse_manifest(fp) == []

    def test_dispatches_on_basename(self, tmp_path: Path) -> None:
        fp = _write(tmp_path, "requirements.txt", "flask==2.0.1\n")
        comps = parse_manifest(fp)
        assert len(comps) == 1
        assert comps[0].name == "flask"


class TestEcosystemMapping:
    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("requirements.txt", "PyPI"),
            ("package.json", "npm"),
            ("Gemfile.lock", "RubyGems"),
            ("go.sum", "Go"),
            ("Cargo.lock", "crates.io"),
            ("composer.json", "Packagist"),
            ("pom.xml", "Maven"),
            ("packages.config", "NuGet"),
            ("readme.md", None),
        ],
    )
    def test_ecosystem(self, tmp_path: Path, filename: str, expected: str | None) -> None:
        fp = tmp_path / filename
        fp.touch()
        assert ecosystem_for_manifest(fp) == expected


# ============================================================================
# Origine : tests/test_modules/test_sast_dependency.py  L785-L897  (commit 52c714b7)
# ============================================================================

class _FakeOSVResponse:
    """Faux ``aiohttp`` response utilisable en ``async with session.post(...)``.

    Si ``raise_exc`` est fourni, l'entrée du contexte (l'équivalent de l'aller
    réseau) lève — simule un timeout / une connexion refusée. Sinon, expose un
    ``status`` et un ``json()`` configurables.
    """

    def __init__(
        self,
        status: int = 200,
        payload: dict | None = None,
        raise_exc: BaseException | None = None,
    ) -> None:
        self.status = status
        self._payload = payload if payload is not None else {"results": []}
        self._raise = raise_exc

    async def __aenter__(self) -> _FakeOSVResponse:
        if self._raise is not None:
            raise self._raise
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def json(self) -> dict:
        return self._payload


def _patch_aiohttp(post_factory):
    """Patche ``aiohttp.ClientSession`` par une session dont ``.post`` délègue
    à ``post_factory()`` (rappelé à chaque batch)."""

    class _FakeSession:
        def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
            pass

        async def __aenter__(self) -> _FakeSession:
            return self

        async def __aexit__(self, *exc: object) -> bool:
            return False

        def post(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            return post_factory()

    return patch("aiohttp.ClientSession", _FakeSession)


def _pinned_flask(tmp_path: Path) -> SCAComponent:
    return SCAComponent(
        ecosystem="PyPI",
        name="flask",
        version="2.0.1",
        source_file=tmp_path / "requirements.txt",
        pinned=True,
    )


@pytest.mark.skip(
    reason="ARGOS (2) : query_osv_batch importe la session HTTP d'Argos ; retirer ce skip une fois la session remplacée"
)
class TestQueryOSVNetworkErrors:
    """Le vrai ``query_osv_batch`` face à des erreurs réseau (aiohttp mocké)."""

    @pytest.mark.asyncio
    async def test_http_500_returns_empty_without_raising(self, tmp_path: Path) -> None:
        comp = _pinned_flask(tmp_path)
        with _patch_aiohttp(lambda: _FakeOSVResponse(status=500)):
            result = await query_osv_batch([comp], timeout=5.0)
        # HTTP 5xx => aucun résultat, aucune exception (Q3).
        assert result == {}

    @pytest.mark.asyncio
    async def test_http_429_returns_empty_without_raising(self, tmp_path: Path) -> None:
        comp = _pinned_flask(tmp_path)
        with _patch_aiohttp(lambda: _FakeOSVResponse(status=429)):
            result = await query_osv_batch([comp], timeout=5.0)
        assert result == {}

    @pytest.mark.asyncio
    async def test_timeout_returns_empty_without_raising(self, tmp_path: Path) -> None:
        comp = _pinned_flask(tmp_path)
        # asyncio.TimeoutError est TimeoutError (py3.11+) — capturé par le
        # except interne de query_osv_batch.
        with _patch_aiohttp(lambda: _FakeOSVResponse(raise_exc=TimeoutError())):
            result = await query_osv_batch([comp], timeout=5.0)
        assert result == {}

    @pytest.mark.asyncio
    async def test_connect_error_returns_empty_without_raising(self, tmp_path: Path) -> None:
        import aiohttp

        comp = _pinned_flask(tmp_path)
        exc = aiohttp.ClientConnectionError("connection refused")
        with _patch_aiohttp(lambda: _FakeOSVResponse(raise_exc=exc)):
            result = await query_osv_batch([comp], timeout=5.0)
        assert result == {}

    @pytest.mark.asyncio
    async def test_malformed_json_body_returns_empty(self, tmp_path: Path) -> None:
        """200 OK mais corps illisible (json() lève) : pas de crash, pas de finding."""

        comp = _pinned_flask(tmp_path)

        class _BadJsonResponse(_FakeOSVResponse):
            async def json(self) -> dict:
                raise ValueError("not json")

        # Lot 4 — le helper partagé (_common.py) attrape désormais la ValueError
        # d'un corps 200 illisible (best-effort) : il renvoie un mapping vide
        # sans propager, donc le scan ne peut pas crasher à cause d'OSV.
        with _patch_aiohttp(lambda: _BadJsonResponse(status=200)):
            result = await query_osv_batch([comp], timeout=5.0)
        assert result == {}
