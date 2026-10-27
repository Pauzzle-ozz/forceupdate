"""RÉFÉRENCE — code SCA repris d'Argos (SecHunter), à piocher, pas à importer.

Copié à l'identique depuis le dépôt Argos (commit 52c714b7), seuls ont été
ajoutés les bandeaux « Origine » et les commentaires « ARGOS (n) ». Chaque bloc
indique le fichier et les lignes d'où il vient.

Contenu :
  - limites de collecte + dossiers ignorés (node_modules, .venv, dist...)
  - is_test_path : reconnaît un chemin de tests / fixtures / exemples
  - safe_read_text : lecture UTF-8 tolérante avec plafond de taille
  - DEPENDENCY_MANIFESTS / ecosystem_for_manifest : quels fichiers, quel écosystème
  - SCAComponent : la structure commune (écosystème, nom, version, pinned, scope...)
  - discover_dependency_manifests : trouver les manifestes dans un dossier
  - 19 parseurs + parse_manifest (le dispatcher par nom de fichier)
  - query_osv_batch + _parse_osv_vuln : vulnérabilités connues via OSV.dev
  - calcul du score CVSS 3.1 de base sans dépendance
  - MANIFEST_LOCKFILES : quel lockfile va avec quel manifeste

Ce qui dépend encore d'Argos (cherche « ARGOS ( » dans ce fichier) :
  (1) Severity      — enum d'Argos, non importé : _cvss_to_severity et donc
                      _parse_osv_vuln lèvent NameError tant qu'il n'est pas redéfini.
  (2) session HTTP  — query_osv_batch importe la session tracée d'Argos.
  (3) bug OSV       — querybatch ne donne que les ids, il faut hydrater.

En l'état, le fichier s'importe sans Argos et les parseurs tournent tels quels
(Python 3.11+ pour tomllib, + loguru). Le détail des limites est dans
reference/README.md.
"""

from __future__ import annotations

import json
import math
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

# ARGOS (1) — enum de sévérité d'Argos, utilisé par OSVVulnerability et _cvss_to_severity.
# from sechunter.core.models import Severity


# ============================================================================
# Origine : sechunter/modules/sast/_common.py  L43-L83  (commit 52c714b7)
# ============================================================================

DEFAULT_MAX_FILES = 2000
"""Plafond de fichiers analysés par scan pour éviter l'explosion mémoire
sur des monorepos géants."""

DEFAULT_MAX_FILE_SIZE = 2_000_000
"""Taille max d'un fichier analysé (2 MB). Au-delà, on skip : SAST sur un
bundle minifié ou un gros lock file n'a pas d'intérêt."""

_IGNORE_DIRS_COMMON: frozenset[str] = frozenset(
    {
        ".git",
        ".svn",
        ".hg",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".cache",
        ".parcel-cache",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        ".eggs",
        "egg-info",
        "node_modules",
        "bower_components",
        ".next",
        ".nuxt",
        ".svelte-kit",
        "dist",
        "build",
        "coverage",
        ".coverage",
        "vendor",
        "third_party",
        "third-party",
    }
)
"""Dossiers systématiquement ignorés : caches, environnements virtuels,
dépendances tierces, outputs de build."""


# ============================================================================
# Origine : sechunter/modules/sast/_common.py  L90-L159  (commit 52c714b7)
# ============================================================================

_TEST_PATH_MARKERS: tuple[str, ...] = (
    "/tests/",
    "\\tests\\",
    "/test/",
    "\\test\\",
    "/__tests__/",
    "\\__tests__\\",
    "/spec/",
    "\\spec\\",
    "/specs/",
    "\\specs\\",
    "/fixtures/",
    "\\fixtures\\",
    "/fixture/",
    "\\fixture\\",
    "/examples/",
    "\\examples\\",
    "/example/",
    "\\example\\",
    "/demo/",
    "\\demo\\",
    "/demos/",
    "\\demos\\",
    "/mocks/",
    "\\mocks\\",
    "/mock/",
    "\\mock\\",
    "/stubs/",
    "\\stubs\\",
    "_test.py",
    "_test.js",
    "_test.ts",
    "_test.tsx",
    "_test.go",
    "_test.rb",
    "_test.java",
    "_test.cs",
    "_test.php",
    ".test.js",
    ".test.ts",
    ".test.jsx",
    ".test.tsx",
    ".spec.js",
    ".spec.ts",
    ".spec.jsx",
    ".spec.tsx",
    ".spec.rb",
    "Test.java",
    "Tests.java",
    "Test.cs",
    "Tests.cs",
)

_TEST_FILENAME_PREFIXES: tuple[str, ...] = ("test_", "tests_", "conftest")


def is_test_path(path: Path | str) -> bool:
    """Q5 : détecte un fichier dans un dossier de tests / fixtures / examples.

    Les secrets hardcodés ``password = "admin"`` ou les appels à du code
    dynamique y sont typiquement intentionnels (code de démonstration,
    scénarios de régression de scanner, harness pytest). La sévérité est
    abaissée d'un cran et la confiance baisse.
    """

    norm = str(path).replace("\\", "/").lower()
    if any(marker.replace("\\", "/").lower() in norm for marker in _TEST_PATH_MARKERS):
        return True
    name = Path(path).name.lower()
    return any(name.startswith(prefix) for prefix in _TEST_FILENAME_PREFIXES)


# ============================================================================
# Origine : sechunter/modules/sast/_common.py  L477-L487  (commit 52c714b7)
# ============================================================================

def safe_read_text(path: Path, *, max_size: int = DEFAULT_MAX_FILE_SIZE) -> str | None:
    """Lecture UTF-8 tolérante avec garde-fou sur la taille."""

    try:
        if path.stat().st_size > max_size:
            logger.debug(f"SAST: fichier >{max_size} octets, ignoré: {path}")
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as err:
        logger.debug(f"SAST: lecture impossible {path}: {err}")
        return None


# ============================================================================
# Origine : sechunter/modules/sast/_common.py  L6195-L7377  (commit 52c714b7)
# ============================================================================

# ---------------------------------------------------------------------------
# SAST-03 — SCA (Software Composition Analysis) helpers partagés
# ---------------------------------------------------------------------------
#
# Cette section regroupe la plomberie commune aux 4 modules SAST-03 :
# `sast.dependency`, `sast.supply_chain`, `sast.license_audit`, `sast.sbom`.
#
# Elle couvre :
#   - Découverte et parsing des manifests / lockfiles (15+ formats).
#   - Client OSV.dev batch API (source de vérité Google/OpenSSF pour les CVE).
#   - Classification SPDX des licences (permissive / weak / strong / network /
#     proprietary / unknown).
#   - Factories `build_sca_finding` / `build_supply_chain_finding` /
#     `build_license_finding` / `build_sbom_finding` avec sévérité Q4 calibrée.
#
# Conforme au standard Q1-Q8 de REFONTE_V2_PLAN.md. Les parsers sont
# délibérément conservateurs : en cas d'ambiguïté sur la version, on ignore
# silencieusement le composant plutôt que de générer un faux composant
# SCA-bogus qui polluerait ensuite l'OSV query et le SBOM.

# ARGOS (3) BUG CONNU — /v1/querybatch ne renvoie que {id, modified} par vuln.
# _parse_osv_vuln recoit donc des entrées vides : pas de CVSS (tout sort à 5.5
# = MEDIUM), pas d'alias CVE, pas de version corrigée. Il faut hydrater chaque
# id via GET /v1/vulns/{id}. Voir reference/README.md.
_OSV_BATCH_URL = "https://api.osv.dev/v1/querybatch"
"""Endpoint batch OSV.dev. Le service accepte jusqu'à 1000 queries par
appel ; on reste à 100 pour limiter la taille de la réponse."""

_OSV_DEFAULT_TIMEOUT = 30.0

DEPENDENCY_MANIFESTS: frozenset[str] = frozenset(
    {
        # Python
        "requirements.txt",
        "requirements-dev.txt",
        "requirements-test.txt",
        "requirements-prod.txt",
        "Pipfile",
        "Pipfile.lock",
        "poetry.lock",
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        # Node / npm / yarn / pnpm
        "package.json",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "npm-shrinkwrap.json",
        # Ruby
        "Gemfile",
        "Gemfile.lock",
        # Go
        "go.mod",
        "go.sum",
        # Rust
        "Cargo.toml",
        "Cargo.lock",
        # PHP / Composer
        "composer.json",
        "composer.lock",
        # Java / Maven
        "pom.xml",
        # .NET / NuGet
        "packages.config",
    }
)
"""Fichiers de dépendances reconnus pour SAST-03. La casse est comparée
case-insensitively via `parse_manifest`."""


_ECOSYSTEM_BY_FILENAME: dict[str, str] = {
    "requirements.txt": "PyPI",
    "requirements-dev.txt": "PyPI",
    "requirements-test.txt": "PyPI",
    "requirements-prod.txt": "PyPI",
    "pipfile": "PyPI",
    "pipfile.lock": "PyPI",
    "poetry.lock": "PyPI",
    "pyproject.toml": "PyPI",
    "setup.py": "PyPI",
    "setup.cfg": "PyPI",
    "package.json": "npm",
    "package-lock.json": "npm",
    "yarn.lock": "npm",
    "pnpm-lock.yaml": "npm",
    "npm-shrinkwrap.json": "npm",
    "gemfile": "RubyGems",
    "gemfile.lock": "RubyGems",
    "go.mod": "Go",
    "go.sum": "Go",
    "cargo.toml": "crates.io",
    "cargo.lock": "crates.io",
    "composer.json": "Packagist",
    "composer.lock": "Packagist",
    "pom.xml": "Maven",
    "packages.config": "NuGet",
}


@dataclass(frozen=True)
class SCAComponent:
    """Un composant logiciel extrait d'un manifest / lockfile.

    Un composant pinné (``pinned=True``) a une version exacte utilisable
    pour une query OSV. Un composant non pinné (ex: ``requests>=2.0``) est
    conservé pour le SBOM et la supply chain audit, mais pas envoyé à OSV
    (OSV attend une version exacte).
    """

    ecosystem: str
    name: str
    version: str
    source_file: Path
    scope: str = "runtime"
    line_no: int | None = None
    pinned: bool = True

    @property
    def key(self) -> str:
        return f"{self.ecosystem}::{self.name}@{self.version}"


@dataclass(frozen=True)
class OSVVulnerability:
    """Vulnérabilité retournée par OSV.dev, normalisée."""

    id: str
    aliases: tuple[str, ...]
    summary: str
    details: str
    severity: Severity
    cvss_score: float
    cvss_vector: str
    fixed_versions: tuple[str, ...]
    published: str
    modified: str
    references: tuple[str, ...]
    cve_ids: tuple[str, ...]


# ---------------------------------------------------------------------------
# Manifest discovery
# ---------------------------------------------------------------------------


def discover_dependency_manifests(
    root: Path,
    *,
    max_files: int = DEFAULT_MAX_FILES,
    include_test_paths: bool = True,
) -> list[Path]:
    """Découvre tous les manifestes / lockfiles sous ``root``.

    Respecte la liste d'``_IGNORE_DIRS_COMMON`` (node_modules, .venv, etc.)
    sauf pour ``node_modules`` et ``vendor`` qui sont spécialement exclus
    des scans de manifests (on veut l'arbre du projet, pas les deps déjà
    résolues). Les manifestes situés dans des chemins de tests ne sont pas
    filtrés par défaut (``include_test_paths=True``) — le caller peut les
    skipper via ``is_test_path`` si nécessaire (Q5).
    """

    if root.is_file():
        if root.name.lower() in {m.lower() for m in DEPENDENCY_MANIFESTS}:
            return [root]
        return []

    if not root.is_dir():
        return []

    manifests_lower = {m.lower() for m in DEPENDENCY_MANIFESTS}
    collected: list[Path] = []
    for current, dirs, filenames in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS_COMMON]
        for name in filenames:
            if len(collected) >= max_files:
                logger.warning(f"SCA: limite de {max_files} manifests atteinte sous {root}")
                return sorted(collected)
            if name.lower() not in manifests_lower:
                continue
            fp = Path(current) / name
            if not include_test_paths and is_test_path(fp):
                continue
            collected.append(fp)
    return sorted(collected)


def ecosystem_for_manifest(path: Path) -> str | None:
    """Retourne l'écosystème OSV pour un manifest donné (ou ``None`` inconnu)."""

    return _ECOSYSTEM_BY_FILENAME.get(path.name.lower())


# ---------------------------------------------------------------------------
# Lockfile / manifest parsers
# ---------------------------------------------------------------------------


_UNPINNED_PY_OP = re.compile(r"[><!~*^]|>=|<=")
_UNPINNED_NPM = re.compile(r"^[\^~>*]|>=|latest|x|\*")


def _is_pinned_python(version_spec: str) -> bool:
    """Une version Python est pinnée si elle commence par ``==`` sans autre op."""

    spec = version_spec.strip()
    if not spec:
        return False
    if spec.startswith("=="):
        rest = spec[2:].strip()
        return bool(rest) and "," not in rest and "*" not in rest
    return False


def _is_pinned_npm(version_spec: str) -> bool:
    """Une version npm est pinnée si elle matche ``\\d+\\.\\d+\\.\\d+``."""

    return bool(re.match(r"^\d+\.\d+\.\d+(?:[-+][\w\.\-]+)?$", version_spec.strip()))


def _strip_npm_version(raw: str) -> str:
    """Nettoie un range npm en la version effective (``^1.2.3`` → ``1.2.3``)."""

    cleaned = re.sub(r"^[\^~>=<]+", "", raw.strip()).split(" ", 1)[0]
    match = re.match(r"^(\d+\.\d+\.\d+(?:[-+][\w\.\-]+)?)", cleaned)
    return match.group(1) if match else ""


def parse_requirements_txt(path: Path, content: str) -> list[SCAComponent]:
    """Parse un ``requirements.txt`` / ``requirements-*.txt``.

    Les lignes ``-r other.txt``, ``-e .``, ``--index-url …`` et les commentaires
    sont ignorées. Les composants sans version sont remontés comme
    ``pinned=False`` (utilisés par supply_chain + sbom, mais pas par OSV).
    """

    results: list[SCAComponent] = []
    for idx, raw in enumerate(content.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        # Strip environment markers (``; python_version >= '3.8'``)
        line = line.split(";", 1)[0].strip()
        match = re.match(
            r"""^([A-Za-z0-9][A-Za-z0-9._\-]*)(\[[^\]]*\])?\s*(.*)$""",
            line,
        )
        if not match:
            continue
        name = match.group(1).lower()
        rest = (match.group(3) or "").strip()
        pinned = _is_pinned_python(rest)
        version = ""
        if pinned:
            version = rest[2:].strip()
        elif rest.startswith("=="):
            # ``==1.0.*`` = range, non pinné
            version = rest[2:].strip()
        else:
            # Essayer d'extraire une version approximative pour le SBOM
            vmatch = re.search(r"(\d+(?:\.\d+){0,3}(?:[-+][\w\.\-]+)?)", rest)
            if vmatch:
                version = vmatch.group(1)
        results.append(
            SCAComponent(
                ecosystem="PyPI",
                name=name,
                version=version,
                source_file=path,
                scope=_python_scope_from_filename(path.name),
                line_no=idx,
                pinned=pinned,
            )
        )
    return results


def _python_scope_from_filename(name: str) -> str:
    lowered = name.lower()
    if "dev" in lowered or "test" in lowered:
        return "dev"
    return "runtime"


def parse_pipfile_lock(path: Path, content: str) -> list[SCAComponent]:
    results: list[SCAComponent] = []
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    for section, scope in (("default", "runtime"), ("develop", "dev")):
        bucket = data.get(section)
        if not isinstance(bucket, dict):
            continue
        for name, info in bucket.items():
            if not isinstance(info, dict):
                continue
            version = str(info.get("version", "")).lstrip("=")
            pinned = bool(version) and re.match(r"^\d", version) is not None
            results.append(
                SCAComponent(
                    ecosystem="PyPI",
                    name=name.lower(),
                    version=version,
                    source_file=path,
                    scope=scope,
                    pinned=pinned,
                )
            )
    return results


def parse_poetry_lock(path: Path, content: str) -> list[SCAComponent]:
    """Parse un ``poetry.lock`` (format TOML v2)."""

    try:
        data = tomllib.loads(content)
    except (tomllib.TOMLDecodeError, ValueError):
        return []
    packages = data.get("package")
    if not isinstance(packages, list):
        return []
    results: list[SCAComponent] = []
    for pkg in packages:
        if not isinstance(pkg, dict):
            continue
        name = str(pkg.get("name", "")).lower()
        version = str(pkg.get("version", ""))
        category = str(pkg.get("category", "main"))
        if not name or not version:
            continue
        scope = "dev" if category in {"dev", "test"} else "runtime"
        results.append(
            SCAComponent(
                ecosystem="PyPI",
                name=name,
                version=version,
                source_file=path,
                scope=scope,
                pinned=True,
            )
        )
    return results


def parse_pyproject_toml(path: Path, content: str) -> list[SCAComponent]:
    """Parse ``pyproject.toml`` — sections ``[project]`` + ``[tool.poetry]``."""

    try:
        data = tomllib.loads(content)
    except (tomllib.TOMLDecodeError, ValueError):
        return []
    results: list[SCAComponent] = []

    # PEP 621 : [project] dependencies
    project = data.get("project", {}) if isinstance(data.get("project"), dict) else {}
    deps = project.get("dependencies")
    if isinstance(deps, list):
        for dep in deps:
            if isinstance(dep, str):
                component = _parse_pep508(path, dep, scope="runtime")
                if component is not None:
                    results.append(component)
    optional = project.get("optional-dependencies")
    if isinstance(optional, dict):
        for group, deps_list in optional.items():
            group_lower = str(group).lower()
            scope = "dev" if "dev" in group_lower or "test" in group_lower else "optional"
            if isinstance(deps_list, list):
                for dep in deps_list:
                    if isinstance(dep, str):
                        component = _parse_pep508(path, dep, scope=scope)
                        if component is not None:
                            results.append(component)

    # Poetry : [tool.poetry.dependencies] + [tool.poetry.dev-dependencies]
    tool = data.get("tool", {}) if isinstance(data.get("tool"), dict) else {}
    poetry = tool.get("poetry", {}) if isinstance(tool.get("poetry"), dict) else {}
    for section_name, scope in (
        ("dependencies", "runtime"),
        ("dev-dependencies", "dev"),
    ):
        section = poetry.get(section_name)
        if not isinstance(section, dict):
            continue
        for name, spec in section.items():
            if name == "python":
                continue
            version = ""
            pinned = False
            if isinstance(spec, str):
                version = _strip_npm_version(spec)
                pinned = bool(re.match(r"^\d+\.\d+(\.\d+)?$", spec))
            elif isinstance(spec, dict):
                v = spec.get("version")
                if isinstance(v, str):
                    version = _strip_npm_version(v)
                    pinned = bool(re.match(r"^\d+\.\d+(\.\d+)?$", v))
            results.append(
                SCAComponent(
                    ecosystem="PyPI",
                    name=str(name).lower(),
                    version=version,
                    source_file=path,
                    scope=scope,
                    pinned=pinned,
                )
            )

    # uv / PDM : [tool.uv.sources] ou [dependency-groups]
    groups = data.get("dependency-groups")
    if isinstance(groups, dict):
        for group_name, deps_list in groups.items():
            name_lower = str(group_name).lower()
            scope = "dev" if "dev" in name_lower or "test" in name_lower else "optional"
            if isinstance(deps_list, list):
                for dep in deps_list:
                    if isinstance(dep, str):
                        component = _parse_pep508(path, dep, scope=scope)
                        if component is not None:
                            results.append(component)

    return results


def _parse_pep508(path: Path, spec: str, *, scope: str) -> SCAComponent | None:
    """Parse un requirement PEP 508 (``package[extra]>=1.0 ; marker``)."""

    line = spec.split(";", 1)[0].strip()
    match = re.match(
        r"""^([A-Za-z0-9][A-Za-z0-9._\-]*)(\[[^\]]*\])?\s*(.*)$""",
        line,
    )
    if not match:
        return None
    name = match.group(1).lower()
    rest = (match.group(3) or "").strip()
    pinned = _is_pinned_python(rest)
    version = ""
    if pinned:
        version = rest[2:].strip()
    else:
        vmatch = re.search(r"(\d+(?:\.\d+){0,3}(?:[-+][\w\.\-]+)?)", rest)
        if vmatch:
            version = vmatch.group(1)
    return SCAComponent(
        ecosystem="PyPI",
        name=name,
        version=version,
        source_file=path,
        scope=scope,
        pinned=pinned,
    )


def parse_package_json(path: Path, content: str) -> list[SCAComponent]:
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    results: list[SCAComponent] = []
    for section, scope in (
        ("dependencies", "runtime"),
        ("devDependencies", "dev"),
        ("peerDependencies", "peer"),
        ("optionalDependencies", "optional"),
    ):
        deps = data.get(section)
        if not isinstance(deps, dict):
            continue
        for name, raw_version in deps.items():
            if not isinstance(raw_version, str):
                continue
            version = _strip_npm_version(raw_version)
            pinned = _is_pinned_npm(raw_version.strip())
            results.append(
                SCAComponent(
                    ecosystem="npm",
                    name=str(name),
                    version=version,
                    source_file=path,
                    scope=scope,
                    pinned=pinned,
                )
            )
    return results


def parse_package_lock_json(path: Path, content: str) -> list[SCAComponent]:
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    results: list[SCAComponent] = []
    packages = data.get("packages")
    if isinstance(packages, dict):
        for pkg_path, info in packages.items():
            if not isinstance(info, dict) or pkg_path == "":
                continue
            name = info.get("name")
            if not isinstance(name, str) or not name:
                # Fallback : derive name from the path after last "node_modules/".
                if "node_modules/" in pkg_path:
                    name = pkg_path.rsplit("node_modules/", 1)[-1]
                else:
                    continue
            version = str(info.get("version", ""))
            scope = "dev" if bool(info.get("dev")) else "runtime"
            results.append(
                SCAComponent(
                    ecosystem="npm",
                    name=str(name),
                    version=version,
                    source_file=path,
                    scope=scope,
                    pinned=_is_pinned_npm(version),
                )
            )
    # v1 fallback : top-level "dependencies" tree
    if not results:
        deps = data.get("dependencies")
        if isinstance(deps, dict):
            for name, info in deps.items():
                if not isinstance(info, dict):
                    continue
                version = str(info.get("version", ""))
                if not version:
                    continue
                scope = "dev" if bool(info.get("dev")) else "runtime"
                results.append(
                    SCAComponent(
                        ecosystem="npm",
                        name=str(name),
                        version=version,
                        source_file=path,
                        scope=scope,
                        pinned=_is_pinned_npm(version),
                    )
                )
    return results


def parse_yarn_lock(path: Path, content: str) -> list[SCAComponent]:
    """Parse ``yarn.lock`` v1. Les blocs sont séparés par une ligne vide."""

    results: list[SCAComponent] = []
    current_name = ""
    for raw in content.splitlines():
        line = raw.rstrip()
        if not line.startswith(" ") and line.endswith(":"):
            pkg_line = line.rstrip(":").strip().strip('"')
            # Garder le premier package name avant @version (ex: "@scope/name@^1.0.0,
            # @scope/name@^2.0.0" -> @scope/name).
            first = pkg_line.split(",", 1)[0].strip().strip('"')
            if first.startswith("@"):
                at_idx = first.find("@", 1)
            else:
                at_idx = first.find("@")
            current_name = first[:at_idx] if at_idx > 0 else first
        elif current_name and line.strip().startswith('version "'):
            version = line.strip().split('"', 2)[1]
            results.append(
                SCAComponent(
                    ecosystem="npm",
                    name=current_name,
                    version=version,
                    source_file=path,
                    scope="runtime",
                    pinned=_is_pinned_npm(version),
                )
            )
            current_name = ""
    return results


def parse_pnpm_lock_yaml(path: Path, content: str) -> list[SCAComponent]:
    """Parse ``pnpm-lock.yaml`` par pattern regex (pas de dép YAML lourde).

    Format : le bloc ``packages:`` contient des clés ``/<name>/<version>:``.
    On extrait ces clés avec une regex conservatrice.
    """

    results: list[SCAComponent] = []
    # Ex: "/express/4.18.2:", "/@scope/pkg/1.0.0:"
    pattern = re.compile(r"^\s{2}/(@[^/]+/[^/]+|[^/@][^/]*)/([0-9][^:\s]*):\s*$")
    for line in content.splitlines():
        match = pattern.match(line)
        if match:
            name = match.group(1)
            version = match.group(2).split("(", 1)[0]  # strip "(...)" peer suffixes
            results.append(
                SCAComponent(
                    ecosystem="npm",
                    name=name,
                    version=version,
                    source_file=path,
                    scope="runtime",
                    pinned=_is_pinned_npm(version),
                )
            )
    return results


def parse_gemfile_lock(path: Path, content: str) -> list[SCAComponent]:
    results: list[SCAComponent] = []
    in_specs = False
    for raw in content.splitlines():
        if raw.strip() == "specs:":
            in_specs = True
            continue
        if in_specs:
            if not raw.startswith("    "):
                if raw.strip() == "" or raw.startswith(" "):
                    continue
                in_specs = False
                continue
            match = re.match(r"\s{4}(\S+)\s+\(([^)]+)\)", raw)
            if match:
                results.append(
                    SCAComponent(
                        ecosystem="RubyGems",
                        name=match.group(1),
                        version=match.group(2),
                        source_file=path,
                        scope="runtime",
                        pinned=True,
                    )
                )
    return results


def parse_go_sum(path: Path, content: str) -> list[SCAComponent]:
    """``go.sum`` : chaque module apparaît 1 ou 2 fois (module + go.mod)."""

    results: list[SCAComponent] = []
    seen: set[str] = set()
    for line in content.splitlines():
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        name = parts[0]
        # Le 2e champ est "<version>" ou "<version>/go.mod"
        version = parts[1].split("/", 1)[0]
        key = f"{name}@{version}"
        if key in seen:
            continue
        seen.add(key)
        results.append(
            SCAComponent(
                ecosystem="Go",
                name=name,
                version=version,
                source_file=path,
                scope="runtime",
                pinned=True,
            )
        )
    return results


def parse_go_mod(path: Path, content: str) -> list[SCAComponent]:
    """Extrait les ``require`` d'un ``go.mod``. Résultats partiels (pas de
    résolution transitive — pour ça il faut go.sum)."""

    results: list[SCAComponent] = []
    # Soit "require mod v1.2.3", soit un bloc "require ( mod v1.2.3 ... )"
    in_block = False
    for raw in content.splitlines():
        line = raw.strip()
        if line.startswith("require ("):
            in_block = True
            continue
        if in_block and line == ")":
            in_block = False
            continue
        target = (
            line
            if in_block
            else (line[len("require ") :].strip() if line.startswith("require ") else "")
        )
        if not target:
            continue
        # "module v1.2.3" éventuellement suivi de " // indirect"
        match = re.match(r"^(\S+)\s+(v\S+)", target)
        if match:
            results.append(
                SCAComponent(
                    ecosystem="Go",
                    name=match.group(1),
                    version=match.group(2),
                    source_file=path,
                    scope="runtime",
                    pinned=True,
                )
            )
    return results


def parse_cargo_lock(path: Path, content: str) -> list[SCAComponent]:
    try:
        data = tomllib.loads(content)
    except (tomllib.TOMLDecodeError, ValueError):
        return []
    packages = data.get("package")
    if not isinstance(packages, list):
        return []
    results: list[SCAComponent] = []
    for pkg in packages:
        if not isinstance(pkg, dict):
            continue
        name = str(pkg.get("name", ""))
        version = str(pkg.get("version", ""))
        if not name or not version:
            continue
        results.append(
            SCAComponent(
                ecosystem="crates.io",
                name=name,
                version=version,
                source_file=path,
                scope="runtime",
                pinned=True,
            )
        )
    return results


def parse_cargo_toml(path: Path, content: str) -> list[SCAComponent]:
    try:
        data = tomllib.loads(content)
    except (tomllib.TOMLDecodeError, ValueError):
        return []
    results: list[SCAComponent] = []
    for section, scope in (
        ("dependencies", "runtime"),
        ("dev-dependencies", "dev"),
        ("build-dependencies", "build"),
    ):
        deps = data.get(section)
        if not isinstance(deps, dict):
            continue
        for name, spec in deps.items():
            version = ""
            if isinstance(spec, str):
                version = spec.strip()
            elif isinstance(spec, dict):
                v = spec.get("version")
                if isinstance(v, str):
                    version = v.strip()
            results.append(
                SCAComponent(
                    ecosystem="crates.io",
                    name=str(name),
                    version=version,
                    source_file=path,
                    scope=scope,
                    pinned=bool(re.match(r"^\d+\.\d+", version)),
                )
            )
    return results


def parse_composer_json(path: Path, content: str) -> list[SCAComponent]:
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    results: list[SCAComponent] = []
    for section, scope in (("require", "runtime"), ("require-dev", "dev")):
        deps = data.get(section)
        if not isinstance(deps, dict):
            continue
        for name, raw_version in deps.items():
            if not isinstance(name, str):
                continue
            # Skip PHP itself and extension declarations
            if name == "php" or name.startswith("ext-") or name.startswith("lib-"):
                continue
            version = ""
            pinned = False
            if isinstance(raw_version, str):
                stripped = raw_version.strip()
                pinned = bool(re.match(r"^\d+\.\d+\.\d+", stripped))
                version = _strip_npm_version(stripped)
            results.append(
                SCAComponent(
                    ecosystem="Packagist",
                    name=str(name),
                    version=version,
                    source_file=path,
                    scope=scope,
                    pinned=pinned,
                )
            )
    return results


def parse_composer_lock(path: Path, content: str) -> list[SCAComponent]:
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    results: list[SCAComponent] = []
    for section, scope in (("packages", "runtime"), ("packages-dev", "dev")):
        bucket = data.get(section)
        if not isinstance(bucket, list):
            continue
        for pkg in bucket:
            if not isinstance(pkg, dict):
                continue
            name = str(pkg.get("name", ""))
            version = str(pkg.get("version", "")).lstrip("vV")
            if not name or not version:
                continue
            results.append(
                SCAComponent(
                    ecosystem="Packagist",
                    name=name,
                    version=version,
                    source_file=path,
                    scope=scope,
                    pinned=True,
                )
            )
    return results


def parse_pom_xml(path: Path, content: str) -> list[SCAComponent]:
    """Parse un ``pom.xml`` Maven via regex (évite une dép XML externe).

    Détecte les blocs ``<dependency>…</dependency>`` et extrait
    groupId/artifactId/version. Les versions ``${…}`` (interpolation de
    properties) ne sont pas résolues — on les marque non-pinnées.
    """

    results: list[SCAComponent] = []
    dep_pattern = re.compile(
        r"<dependency>\s*<groupId>([^<]+)</groupId>\s*<artifactId>([^<]+)</artifactId>"
        r"(?:\s*<version>([^<]*)</version>)?",
        re.DOTALL,
    )
    for match in dep_pattern.finditer(content):
        group_id = match.group(1).strip()
        artifact = match.group(2).strip()
        version_raw = (match.group(3) or "").strip()
        name = f"{group_id}:{artifact}"
        pinned = bool(version_raw) and "${" not in version_raw
        results.append(
            SCAComponent(
                ecosystem="Maven",
                name=name,
                version=version_raw,
                source_file=path,
                scope="runtime",
                pinned=pinned,
            )
        )
    return results


def parse_packages_config(path: Path, content: str) -> list[SCAComponent]:
    """Parse un ``packages.config`` NuGet legacy."""

    results: list[SCAComponent] = []
    pattern = re.compile(
        r'<package\s+id="([^"]+)"\s+version="([^"]+)"',
        re.IGNORECASE,
    )
    for match in pattern.finditer(content):
        results.append(
            SCAComponent(
                ecosystem="NuGet",
                name=match.group(1),
                version=match.group(2),
                source_file=path,
                scope="runtime",
                pinned=True,
            )
        )
    return results


def parse_manifest(path: Path) -> list[SCAComponent]:
    """Dispatcher : parse un manifest en list de ``SCAComponent``.

    Retourne une liste vide si le fichier est illisible, trop gros, ou
    d'un format non supporté.
    """

    content = safe_read_text(path)
    if content is None:
        return []
    name = path.name.lower()
    parsers: dict[str, Any] = {
        "requirements.txt": parse_requirements_txt,
        "requirements-dev.txt": parse_requirements_txt,
        "requirements-test.txt": parse_requirements_txt,
        "requirements-prod.txt": parse_requirements_txt,
        "pipfile.lock": parse_pipfile_lock,
        "poetry.lock": parse_poetry_lock,
        "pyproject.toml": parse_pyproject_toml,
        "package.json": parse_package_json,
        "package-lock.json": parse_package_lock_json,
        "npm-shrinkwrap.json": parse_package_lock_json,
        "yarn.lock": parse_yarn_lock,
        "pnpm-lock.yaml": parse_pnpm_lock_yaml,
        "gemfile.lock": parse_gemfile_lock,
        "go.mod": parse_go_mod,
        "go.sum": parse_go_sum,
        "cargo.lock": parse_cargo_lock,
        "cargo.toml": parse_cargo_toml,
        "composer.json": parse_composer_json,
        "composer.lock": parse_composer_lock,
        "pom.xml": parse_pom_xml,
        "packages.config": parse_packages_config,
    }
    parser = parsers.get(name)
    if parser is None:
        return []
    try:
        result = parser(path, content)
    except Exception as err:  # pragma: no cover — défensif
        logger.debug(f"SCA: parser {name} a échoué sur {path}: {err}")
        return []
    if isinstance(result, list):
        return [c for c in result if isinstance(c, SCAComponent)]
    return []


# ---------------------------------------------------------------------------
# OSV.dev batch API client
# ---------------------------------------------------------------------------


async def query_osv_batch(
    components: list[SCAComponent],
    *,
    timeout: float = _OSV_DEFAULT_TIMEOUT,
    batch_size: int = 100,
) -> dict[str, list[OSVVulnerability]]:
    """Interroge OSV.dev en batch pour les vulns affectant ``components``.

    Retourne un mapping ``component.key → list[OSVVulnerability]``. Les
    composants non pinnés ou sans écosystème reconnu sont ignorés. En cas
    d'erreur réseau ou de timeout, la fonction loggue et retourne les
    résultats partiels déjà obtenus — pas d'exception propagée (Q3 :
    erreur externe = inconclusive, pas de finding fictif).
    """

    import aiohttp

    # ARGOS (2) — session HTTP tracée d'Argos. Hors Argos, remplacer par
    # aiohttp.ClientSession(timeout=client_timeout).
    from sechunter.core.aiohttp_session import create_scan_aiohttp_session

    valid = [c for c in components if c.pinned and c.version]
    if not valid:
        return {}

    results: dict[str, list[OSVVulnerability]] = {}

    client_timeout = aiohttp.ClientTimeout(total=timeout)
    try:
        # Session TRACEE : la reponse d'OSV est ce qui decide « ce paquet porte
        # cette CVE ». Sans trace, le finding SCA affirmait une CVE sans que
        # rien n'atteste d'ou elle venait -- exactement ce que le chantier
        # verdict a supprime partout ailleurs.
        async with create_scan_aiohttp_session(timeout=client_timeout) as session:
            for start in range(0, len(valid), batch_size):
                batch = valid[start : start + batch_size]
                queries = [
                    {
                        "package": {"name": c.name, "ecosystem": c.ecosystem},
                        "version": c.version,
                    }
                    for c in batch
                ]
                try:
                    async with session.post(
                        _OSV_BATCH_URL,
                        json={"queries": queries},
                        headers={"Content-Type": "application/json"},
                    ) as resp:
                        if resp.status != 200:
                            logger.warning(f"OSV: HTTP {resp.status} sur batch {start}")
                            continue
                        payload = await resp.json()
                except (aiohttp.ClientError, TimeoutError) as err:
                    logger.warning(f"OSV: échec requête batch {start}: {err}")
                    continue

                for idx, entry in enumerate(payload.get("results", [])):
                    if idx >= len(batch):
                        break
                    raw_vulns = entry.get("vulns") if isinstance(entry, dict) else None
                    if not raw_vulns:
                        continue
                    component = batch[idx]
                    parsed: list[OSVVulnerability] = []
                    for v in raw_vulns:
                        if not isinstance(v, dict):
                            continue
                        parsed_vuln = _parse_osv_vuln(v)
                        if parsed_vuln is not None:
                            parsed.append(parsed_vuln)
                    if parsed:
                        results.setdefault(component.key, []).extend(parsed)
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        # Défensif : réseau (ssl/dns), timeout, ou corps 200 illisible
        # (resp.json() lève ValueError). Best-effort : on renvoie les résultats
        # partiels déjà collectés plutôt que de propager et casser le scan (Q3
        # = inconclusive, jamais de finding fictif).
        logger.warning(f"OSV: requête batch échouée ({type(err).__name__}): {err}")

    return results


_CVSS_VECTOR_RE = re.compile(
    r"CVSS:3\.[01]/(AV:[NALP])/(AC:[LH])/(PR:[NLH])/(UI:[NR])/"
    r"(S:[UC])/(C:[NLH])/(I:[NLH])/(A:[NLH])"
)
_CVSS_BASE_SCORE_RE = re.compile(r"^(\d+\.\d+)")


def _parse_osv_vuln(raw: dict[str, Any]) -> OSVVulnerability | None:
    vuln_id = str(raw.get("id", ""))
    if not vuln_id:
        return None
    aliases = tuple(str(a) for a in raw.get("aliases", []) if isinstance(a, str))
    cve_ids = tuple(a for a in aliases if a.startswith("CVE-"))
    summary = str(raw.get("summary", ""))[:300]
    details = str(raw.get("details", ""))[:600]
    published = str(raw.get("published", ""))
    modified = str(raw.get("modified", ""))

    # Références
    refs_raw = raw.get("references", [])
    refs: list[str] = []
    if isinstance(refs_raw, list):
        for ref in refs_raw:
            if isinstance(ref, dict):
                url = ref.get("url")
                if isinstance(url, str):
                    refs.append(url)

    # CVSS : peut venir de severity[].score (vector) ou de database_specific
    cvss_score = 0.0
    cvss_vector = ""
    severity_entries = raw.get("severity", [])
    if isinstance(severity_entries, list):
        for sev in severity_entries:
            if not isinstance(sev, dict):
                continue
            if sev.get("type") == "CVSS_V3":
                score_str = str(sev.get("score", ""))
                cvss_vector = score_str
                base = _cvss_base_score_from_vector(score_str)
                if base > 0:
                    cvss_score = base
                    break

    db_specific = raw.get("database_specific")
    if cvss_score == 0.0 and isinstance(db_specific, dict):
        cvss_info = db_specific.get("cvss")
        if isinstance(cvss_info, dict):
            try:
                cvss_score = float(cvss_info.get("score", 0) or 0)
            except (ValueError, TypeError):
                pass
        if cvss_score == 0.0:
            sev_str = db_specific.get("severity")
            if isinstance(sev_str, str):
                mapping = {
                    "CRITICAL": 9.5,
                    "HIGH": 8.0,
                    "MODERATE": 5.5,
                    "MEDIUM": 5.5,
                    "LOW": 3.0,
                }
                cvss_score = mapping.get(sev_str.upper(), 0.0)

    if cvss_score == 0.0:
        cvss_score = 5.5  # Défaut conservateur si OSV ne donne rien

    severity = _cvss_to_severity(cvss_score)

    # Fixed versions (agréger tous les "fixed" events)
    fixed: set[str] = set()
    affected = raw.get("affected")
    if isinstance(affected, list):
        for aff in affected:
            if not isinstance(aff, dict):
                continue
            for rng in aff.get("ranges", []):
                if not isinstance(rng, dict):
                    continue
                for event in rng.get("events", []):
                    if isinstance(event, dict) and isinstance(event.get("fixed"), str):
                        fixed.add(event["fixed"])

    return OSVVulnerability(
        id=vuln_id,
        aliases=aliases,
        summary=summary or details[:200],
        details=details,
        severity=severity,
        cvss_score=cvss_score,
        cvss_vector=cvss_vector,
        fixed_versions=tuple(sorted(fixed)),
        published=published,
        modified=modified,
        references=tuple(refs[:5]),
        cve_ids=cve_ids,
    )


def _cvss_base_score_from_vector(vector: str) -> float:
    """Extrait le score de base CVSS 3.1 d'un vecteur.

    OSV.dev fournit le vector complet (``CVSS:3.1/AV:N/…``). On implémente
    le calcul officiel FIRST CVSS 3.1 base score sans dépendance externe.
    """

    match = _CVSS_VECTOR_RE.search(vector)
    if not match:
        # Parfois OSV stocke le score en tête ("9.8/CVSS:3.1/AV:N/…")
        lead = _CVSS_BASE_SCORE_RE.match(vector)
        if lead:
            try:
                return float(lead.group(1))
            except ValueError:
                return 0.0
        return 0.0

    av, ac, pr, ui, scope, conf, integ, avail = match.groups()
    # Valeurs normatives CVSS 3.1
    av_val = {"AV:N": 0.85, "AV:A": 0.62, "AV:L": 0.55, "AV:P": 0.2}[av]
    ac_val = {"AC:L": 0.77, "AC:H": 0.44}[ac]
    scope_changed = scope == "S:C"
    pr_map_unchanged = {"PR:N": 0.85, "PR:L": 0.62, "PR:H": 0.27}
    pr_map_changed = {"PR:N": 0.85, "PR:L": 0.68, "PR:H": 0.5}
    pr_val = pr_map_changed[pr] if scope_changed else pr_map_unchanged[pr]
    ui_val = {"UI:N": 0.85, "UI:R": 0.62}[ui]
    cia_map = {
        "C:N": 0,
        "C:L": 0.22,
        "C:H": 0.56,
        "I:N": 0,
        "I:L": 0.22,
        "I:H": 0.56,
        "A:N": 0,
        "A:L": 0.22,
        "A:H": 0.56,
    }
    c_val = cia_map[conf]
    i_val = cia_map[integ]
    a_val = cia_map[avail]

    iss = 1 - (1 - c_val) * (1 - i_val) * (1 - a_val)
    impact = (7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15) if scope_changed else 6.42 * iss
    exploitability = 8.22 * av_val * ac_val * pr_val * ui_val
    if impact <= 0:
        return 0.0
    factor = 1.08 if scope_changed else 1.0
    score = min(factor * (impact + exploitability), 10.0)
    # Round up to 1 decimal per CVSS 3.1 specification
    return math.ceil(score * 10) / 10


# ARGOS (1) — `Severity` est l'enum d'Argos (CRITICAL/HIGH/MEDIUM/LOW/INFO),
# volontairement non importé ici : à redéfinir dans le nouvel outil.
def _cvss_to_severity(score: float) -> Severity:
    if score >= 9.0:
        return Severity.CRITICAL
    if score >= 7.0:
        return Severity.HIGH
    if score >= 4.0:
        return Severity.MEDIUM
    if score > 0.0:
        return Severity.LOW
    return Severity.INFO


# ============================================================================
# Origine : sechunter/modules/sast/supply_chain.py  L1199-L1209  (commit 52c714b7)
# ============================================================================

MANIFEST_LOCKFILES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "package.json",
        ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "npm-shrinkwrap.json"),
    ),
    ("Pipfile", ("Pipfile.lock",)),
    ("pyproject.toml", ("poetry.lock", "uv.lock", "pdm.lock")),
    ("Gemfile", ("Gemfile.lock",)),
    ("composer.json", ("composer.lock",)),
    ("Cargo.toml", ("Cargo.lock",)),
)
"""Couples manifest -> lockfiles possibles. Extrait du corps de
``SupplyChainModule._check_lockfiles`` (variable locale ``checks``), sorti en
constante pour être réutilisable."""
