"""Les runtimes d'un projet et leur version, lus sans rien exécuter (E27) : ``Project.runtimes``.

**Dans les manifestes** (une contrainte donne sa borne basse, « approximative », décision n°2 ;
le reste est une version choisie) :

- Python : ``requires-python`` (``[project]``), ``python`` de ``[tool.poetry.dependencies]``,
  ``python_requires`` de ``setup.cfg`` ; ``python_version`` et ``python_full_version`` de
  ``[requires]`` du ``Pipfile`` ;
- Node.js : ``engines.node`` ; ``volta.node`` ;
- Go : la directive ``go`` de ``go.mod`` ou ``go.work`` ; ``toolchain`` ;
- Ruby : ``ruby "…"`` du ``Gemfile`` (``"3.2.2"`` ou ``"~> 3.2"``) ; ``RUBY VERSION`` du
  ``Gemfile.lock`` ; ``required_ruby_version`` d'un ``.gemspec`` (E34) ;
- PHP : ``require.php`` de ``composer.json`` ; ``config.platform.php`` ;
- Java : ``maven.compiler.release``, ``…target``, ``…source``, ``java.version`` (``pom.xml``,
  parents du dépôt compris) ; Gradle : ``targetCompatibility``, ``sourceCompatibility`` ;
  ``JavaLanguageVersion.of(17)``, ``jvmToolchain(17)`` ;
- .NET : ``TargetFramework(s)`` (``net8.0`` : .NET 8 ; ``netcoreapp3.1`` ; ``net48`` : .NET
  Framework 4.8), ``TargetFrameworkVersion`` (``v4.7.2``) ; ``netstandard2.0`` n'est pas un
  runtime ; défini sous condition (E34), chacune des valeurs écrites ;
- Rust (E34) : ``rust-version`` de ``[package]`` (la plus ancienne version de Rust que le projet
  promet de faire tourner ; ``rust-version.workspace = true`` : celle de ``[workspace.package]``).

**Dans les fichiers de runtime** (``Project.runtime_files``, des versions choisies) :
``.python-version`` (pyenv, uv), ``runtime.txt`` (``python-3.8.10``), ``.nvmrc`` et
``.node-version`` (``lts/gallium`` compris), ``.ruby-version``, ``.tool-versions`` (asdf, mise),
``global.json`` (``sdk.version`` : le SDK .NET), ``mise.toml`` et ``.mise.toml`` (``[tools]``,
E34), ``rust-toolchain.toml`` et ``rust-toolchain``
(``channel = "1.80.0"`` de rustup ; pas ``stable`` ni ``nightly``), et le ``FROM`` des
``Dockerfile`` : images officielles ``python``, ``node``, ``ruby``, ``php``, ``golang``,
``eclipse-temurin``, ``amazoncorretto``, ``mcr.microsoft.com/dotnet/{sdk,aspnet,runtime}`` et
``mcr.microsoft.com/dotnet/framework/…``, et depuis E34 ``openjdk`` (dépréciée : lue comme
Eclipse Temurin), leurs copies (``public.ecr.aws/docker/library/…``, ``mirror.gcr.io/…``) et des
images non officielles qui suivent les mêmes versions : ``bitnami/…``, ``cimg/…`` et
``circleci/…`` de CircleCI, ``mcr.microsoft.com/devcontainers/…`` (``1-3.11-bookworm`` : le ``1-``
est la version de l'image). Les ``ARG`` d'avant le premier ``FROM`` y sont remplacés ; une
étiquette sans version (``latest``, ``lts``, ``alpine``) ne dit rien.

**Dans les fichiers de CI** (E32 : le npm qu'attend le projet se lit d'après le Node de sa CI) :
les workflows de GitHub Actions (``.github/workflows/*.yml``) donnent la ``node-version`` de
``actions/setup-node``, et depuis E34 la version de ``actions/setup-python``, ``setup-go``,
``setup-java`` (sa ``distribution`` donne le Java : ``temurin``, ``zulu``, ``corretto``),
``setup-dotnet``, ``ruby/setup-ruby`` et ``shivammathur/setup-php`` (une ``matrix`` donne chacune
de ses valeurs, ``env`` est remplacé), et l'image d'un ``container`` ; ``.gitlab-ci.yml`` et
``bitbucket-pipelines.yml``, leurs ``image`` (les ``variables`` de GitLab remplacées). ``lts/*``,
``latest``, ``3.x`` ou une plage ne disent rien. Un fichier de CI vaut pour tous les projets de son
dépôt (``detect.manifests.ci_base``), et y donne le runtime de leur écosystème (lu pour tous les
projets depuis E34 : une requête de plus par workflow à la source d'une forge).

Un fichier de runtime d'un autre dossier (un ``.nvmrc`` à la racine du dépôt) ne vaut que pour un
projet de l'écosystème du runtime : la racine d'un monorepo ne donne pas Node.js au ``backend/``
Python. Rien n'est jamais exécuté : ni le ``Gemfile``, ni un script Gradle, ni MSBuild.
"""

import itertools
import json
import posixpath
import re
import tomllib
from collections.abc import Callable, Iterator
from typing import Any

import yaml

from forceupdate.detect.manifests import ci_base
from forceupdate.models import Ecosystem, Project, Runtime
from forceupdate.parsers import go, maven, nuget, python, ruby, rust
from forceupdate.parsers.base import ParseError, ReadText
from forceupdate.parsers.lockfiles import dirname
from forceupdate.parsers.ruby_spans import statements
from forceupdate.versions import InvalidConstraint, VersionScheme
from forceupdate.versions.composer import COMPOSER
from forceupdate.versions.npm import NPM
from forceupdate.versions.pypi import PYPI
from forceupdate.versions.rubygems import RUBYGEMS

LABELS = {
    "python": "Python",
    "nodejs": "Node.js",
    "go": "Go",
    "ruby": "Ruby",
    "php": "PHP",
    "eclipse-temurin": "Java (Eclipse Temurin)",
    "amazon-corretto": "Java (Amazon Corretto)",
    "azul-zulu": "Java (Azul Zulu)",
    "dotnet": ".NET",
    "dotnetfx": ".NET Framework",
    "rust": "Rust",
}
"""Les runtimes lus, par leur nom chez endoflife.date (``Runtime.product``), et leur nom affiché.
Java se lit d'après Eclipse Temurin, la distribution de référence d'OpenJDK, sauf une autre
nommée (``amazoncorretto``, ``java corretto-17`` dans ``.tool-versions``)."""

ECOSYSTEMS = {
    "python": Ecosystem.PYPI,
    "nodejs": Ecosystem.NPM,
    "go": Ecosystem.GO,
    "ruby": Ecosystem.RUBYGEMS,
    "php": Ecosystem.PACKAGIST,
    "eclipse-temurin": Ecosystem.MAVEN,
    "amazon-corretto": Ecosystem.MAVEN,
    "azul-zulu": Ecosystem.MAVEN,
    "dotnet": Ecosystem.NUGET,
    "dotnetfx": Ecosystem.NUGET,
    "rust": Ecosystem.CRATES_IO,
}
"""L'écosystème de paquets de chaque runtime."""

NODE_CODENAMES = {
    "argon": "4",
    "boron": "6",
    "carbon": "8",
    "dubnium": "10",
    "erbium": "12",
    "fermium": "14",
    "gallium": "16",
    "hydrogen": "18",
    "iron": "20",
    "jod": "22",
    "krypton": "24",
    "lithium": "26",
}
"""Les noms des versions LTS de Node.js (``lts/gallium``, l'image ``node:hydrogen``) : la
``codename`` d'endoflife.date est vide (vérifié le 2026-11-01), ceux-ci viennent de
``nodejs.org/dist/index.json`` (« Lithium » pour la 26, vu le 2026-11-02)."""

IMAGES = {
    "python": "python",
    "node": "nodejs",
    "ruby": "ruby",
    "php": "php",
    "golang": "go",
    "eclipse-temurin": "eclipse-temurin",
    "amazoncorretto": "amazon-corretto",
    "mcr.microsoft.com/dotnet/sdk": "dotnet",
    "mcr.microsoft.com/dotnet/aspnet": "dotnet",
    "mcr.microsoft.com/dotnet/runtime": "dotnet",
    "mcr.microsoft.com/dotnet/runtime-deps": "dotnet",
    "mcr.microsoft.com/dotnet/core/sdk": "dotnet",
    "mcr.microsoft.com/dotnet/core/aspnet": "dotnet",
    "mcr.microsoft.com/dotnet/core/runtime": "dotnet",
    "mcr.microsoft.com/dotnet/framework/sdk": "dotnetfx",
    "mcr.microsoft.com/dotnet/framework/aspnet": "dotnetfx",
    "mcr.microsoft.com/dotnet/framework/runtime": "dotnetfx",
    # E34 : l'image openjdk, dépréciée, et des images non officielles aux mêmes versions.
    "openjdk": "eclipse-temurin",
    "bitnami/python": "python",
    "bitnami/node": "nodejs",
    "bitnami/ruby": "ruby",
    "bitnami/php-fpm": "php",
    "bitnami/golang": "go",
    "bitnami/java": "eclipse-temurin",
    "bitnami/dotnet": "dotnet",
    "bitnami/dotnet-sdk": "dotnet",
    "bitnami/aspnet-core": "dotnet",
    "cimg/python": "python",
    "cimg/node": "nodejs",
    "cimg/ruby": "ruby",
    "cimg/php": "php",
    "cimg/go": "go",
    "cimg/openjdk": "eclipse-temurin",
    "circleci/python": "python",
    "circleci/node": "nodejs",
    "circleci/ruby": "ruby",
    "circleci/php": "php",
    "circleci/golang": "go",
    "circleci/openjdk": "eclipse-temurin",
    "mcr.microsoft.com/devcontainers/python": "python",
    "mcr.microsoft.com/devcontainers/javascript-node": "nodejs",
    "mcr.microsoft.com/devcontainers/typescript-node": "nodejs",
    "mcr.microsoft.com/devcontainers/go": "go",
    "mcr.microsoft.com/devcontainers/java": "eclipse-temurin",
    "mcr.microsoft.com/devcontainers/ruby": "ruby",
    "mcr.microsoft.com/devcontainers/php": "php",
    "mcr.microsoft.com/devcontainers/dotnet": "dotnet",
}
"""Les images d'un ``FROM`` dont l'étiquette dit la version d'un runtime, et ce runtime."""

_MIRRORS = ("public.ecr.aws/docker/library/", "mirror.gcr.io/library/", "mirror.gcr.io/")
"""Les copies de la bibliothèque officielle de Docker Hub (E34)."""
_DEVCONTAINER = re.compile(r"(?:\d+-)?(\d+(?:\.\d+)*)(?:-.*)?")
"""L'étiquette d'une image ``devcontainers`` : ``1-3.11-bookworm`` (la version 1 de l'image,
Python 3.11)."""

_TOOLS = {
    "python": "python",
    "nodejs": "nodejs",
    "node": "nodejs",
    "ruby": "ruby",
    "golang": "go",
    "go": "go",
    "php": "php",
    "dotnet": "dotnet",
    "dotnet-core": "dotnet",
    "rust": "rust",
}
"""Les outils de ``.tool-versions`` (asdf, mise) et leur runtime. Java (``java temurin-17…``) est
lu à part."""

_JAVA_VENDORS = {
    "temurin": "eclipse-temurin",
    "adoptopenjdk": "eclipse-temurin",
    "openjdk": "eclipse-temurin",
    "corretto": "amazon-corretto",
    "zulu": "azul-zulu",
}

_VERSION = re.compile(r"v?(\d+(?:\.\d+)*)")
_LEADING = re.compile(r"(\d+(?:\.\d+)*)")
_DOCKER_VARIABLE = re.compile(r"\$(?:\{(\w+)(?::?-([^}]*))?\}|(\w+))")
_GRADLE_TOOLCHAIN = re.compile(
    r"(?:JavaLanguageVersion\s*\.\s*of|jvmToolchain)\s*\(\s*[\"']?(\d+)[\"']?\s*\)"
)
_GRADLE_COMPATIBILITY = re.compile(
    r"\b(targetCompatibility|sourceCompatibility)\b\s*=?\s*"
    r"(?:JavaVersion\s*\.\s*VERSION_(\d+(?:_\d+)?)|[\"']?(\d+(?:\.\d+)?)[\"']?)"
)
_REQUIRED_RUBY = re.compile(
    r"\.required_ruby_version\s*=\s*(?:Gem::Requirement\.new\s*\(?)?\s*\[?"
    r"((?:\s*['\"][^'\"\n]*['\"]\s*,?)+)"
)
"""``spec.required_ruby_version = ">= 3.0"``, ``Gem::Requirement.new(">= 2.7", "< 4")``, une
liste."""
_TFM_CORE = re.compile(r"net(?:coreapp)?(\d+\.\d+)(?:-.*)?$", re.IGNORECASE)
_TFM_FRAMEWORK = re.compile(r"net(\d)(\d)(\d)?$", re.IGNORECASE)
_TFV = re.compile(r"v?(\d+\.\d+(?:\.\d+)?)$", re.IGNORECASE)


def detect(project: Project, read_text: ReadText) -> list[Runtime]:
    """Les runtimes de ``project`` : ceux de ses manifestes, puis ceux de ses fichiers de
    runtime ; un fichier d'un autre dossier seulement pour un projet de l'écosystème du runtime
    (voir la docstring du module). Sans doublon."""
    found: list[Runtime] = []
    for ecosystem in project.ecosystems:
        reader = _MANIFESTS.get(ecosystem)
        if reader is not None:
            found.extend(reader(project, read_text))
    for path in project.runtime_files:
        for runtime in _runtime_file(path, read_text):
            outside = dirname(path) != project.path
            if outside and ECOSYSTEMS.get(runtime.product) not in project.ecosystems:
                continue
            found.append(runtime)
    return list(dict.fromkeys(found))


# ---------------------------------------------------------------------------
# Les manifestes
# ---------------------------------------------------------------------------


def _read(read_text: ReadText, path: str) -> str | None:
    try:
        return read_text(path)
    except ValueError:
        return None


def _named(project: Project, *names: str) -> Iterator[str]:
    """Les manifestes de ``project`` qui portent un de ces noms (sans la casse)."""
    wanted = {name.lower() for name in names}
    for path in project.manifests:
        if posixpath.basename(path).lower() in wanted:
            yield path


def _bound(
    scheme: VersionScheme[Any], constraint: str, *, product: str, file: str, source: str
) -> Runtime | None:
    """Le runtime d'une contrainte : sa version exacte, sinon sa borne basse (approximative) ;
    ``None`` si elle n'en a pas, ou est illisible."""
    try:
        parsed = scheme.parse_constraint(constraint)
    except InvalidConstraint:
        return None
    exact = parsed.exact()
    version = exact or parsed.lower_bound()
    if version is None:
        return None
    return Runtime(
        product=product,
        version=_trimmed(version) if exact is None else version,
        approximate=exact is None,
        file=file,
        source=source,
    )


def _trimmed(version: str) -> str:
    """Une borne basse sans ses zéros de fin : ``16.0.0`` → ``16``, ``8.1.0`` → ``8.1``."""
    parts = version.split(".")
    while len(parts) > 1 and parts[-1] == "0":
        parts.pop()
    return ".".join(parts)


def _python(project: Project, read_text: ReadText) -> list[Runtime]:
    found = []
    for path in _named(project, "pyproject.toml"):
        data = _toml(read_text, path)
        requires = _get(data, "project", "requires-python")
        if isinstance(requires, str):
            source = f'requires-python = "{requires}"'
            found.append(_bound(PYPI, requires, product="python", file=path, source=source))
        poetry = _get(data, "tool", "poetry", "dependencies", "python")
        if isinstance(poetry, str):
            source = f'[tool.poetry.dependencies] python = "{poetry}"'
            found.append(_bound(PYPI, poetry, product="python", file=path, source=source))
    for path in _named(project, "Pipfile"):
        data = _toml(read_text, path)
        for key in ("python_full_version", "python_version"):
            value = _get(data, "requires", key)
            if isinstance(value, str) and _VERSION.fullmatch(value.strip()):
                source = f'[requires] {key} = "{value}"'
                found.append(_choice("python", value, path, source))
                break
    for path in _named(project, "setup.cfg"):
        content = _read(read_text, path)
        match = re.search(r"^\s*python_requires\s*=\s*(.+?)\s*$", content or "", re.M)
        if match is not None:
            source = f"python_requires = {match[1]}"
            found.append(_bound(PYPI, match[1], product="python", file=path, source=source))
    for path in project.manifests:
        # Le bloc PEP 723 d'un script (E28) : « # requires-python = ">=3.11" ».
        if python.is_script(path):
            requires = python.script_requires_python(_read(read_text, path) or "")
            if requires is not None:
                source = f'requires-python = "{requires}"'
                found.append(_bound(PYPI, requires, product="python", file=path, source=source))
    return [runtime for runtime in found if runtime is not None]


def _node(project: Project, read_text: ReadText) -> list[Runtime]:
    found = []
    for path in _named(project, "package.json"):
        data = _json(read_text, path)
        engines = _get(data, "engines", "node")
        if isinstance(engines, str):
            source = f'engines.node = "{engines}"'
            found.append(_bound(NPM, engines, product="nodejs", file=path, source=source))
        volta = _get(data, "volta", "node")
        if isinstance(volta, str) and _VERSION.fullmatch(volta.strip()):
            found.append(_choice("nodejs", volta, path, f'volta.node = "{volta}"'))
    return [runtime for runtime in found if runtime is not None]


def _go(project: Project, read_text: ReadText) -> list[Runtime]:
    found = []
    for path in _named(project, "go.mod", "go.work"):
        content = _read(read_text, path)
        if content is None:
            continue
        try:
            parsed = go.parse_go_mod_file(path, content)
        except ParseError:
            continue
        toolchain = _LEADING.match((parsed.toolchain or "").removeprefix("go"))
        if parsed.toolchain and parsed.toolchain.startswith("go") and toolchain is not None:
            source = f"toolchain {parsed.toolchain}"
            found.append(_choice("go", toolchain[1], path, source))
        if parsed.go and _VERSION.fullmatch(parsed.go):
            found.append(
                Runtime(
                    product="go",
                    version=parsed.go,
                    approximate=True,
                    file=path,
                    source=f"go {parsed.go}",
                )
            )
    return found


def _php(project: Project, read_text: ReadText) -> list[Runtime]:
    found = []
    for path in _named(project, "composer.json"):
        data = _json(read_text, path)
        platform = _get(data, "config", "platform", "php")
        if isinstance(platform, str) and _VERSION.fullmatch(platform.strip()):
            source = f'config.platform.php = "{platform}"'
            found.append(_choice("php", platform, path, source))
        require = _get(data, "require", "php")
        if isinstance(require, str):
            source = f'require.php = "{require}"'
            found.append(_bound(COMPOSER, require, product="php", file=path, source=source))
    return [runtime for runtime in found if runtime is not None]


def _ruby(project: Project, read_text: ReadText) -> list[Runtime]:
    found = []
    for path in _named(project, "Gemfile", "gems.rb"):
        content = _read(read_text, path)
        if content is None:
            continue
        for statement in statements(content):
            tokens = statement.tokens
            if len(tokens) < 2 or tokens[0].kind != "ident" or tokens[0].value != "ruby":
                continue
            argument = next((t for t in tokens[1:] if t.kind != "op"), None)
            if argument is None or argument.kind != "string":
                continue
            source = f'ruby "{argument.value}"'
            found.append(_bound(RUBYGEMS, argument.value, product="ruby", file=path, source=source))
    for path in project.manifests:
        if not path.endswith(".gemspec"):
            continue
        match = _REQUIRED_RUBY.search(_read(read_text, path) or "")
        if match is not None:
            parts = re.findall(r"['\"]([^'\"]+)['\"]", match[1])
            constraint = ", ".join(part.strip() for part in parts)
            if constraint:
                source = f"required_ruby_version = {match[1].strip()}"
                found.append(_bound(RUBYGEMS, constraint, product="ruby", file=path, source=source))
    for path in project.lockfiles:
        if posixpath.basename(path) not in ("Gemfile.lock", "gems.locked"):
            continue
        content = _read(read_text, path)
        if content is None:
            continue
        try:
            locked = ruby.parse_gemfile_lock(path, content).ruby_version
        except ParseError:
            continue
        match = re.fullmatch(r"ruby\s+(\d+(?:\.\d+)*)\S*", (locked or "").strip())
        if match is not None:
            found.append(_choice("ruby", match[1], path, f"RUBY VERSION {locked}"))
    return [runtime for runtime in found if runtime is not None]


def _java(project: Project, read_text: ReadText) -> list[Runtime]:
    found = []
    for path in _named(project, "pom.xml"):
        version = maven.java_version(path, read_text)
        if version is not None:
            value, definition = version
            number = _java_number(value)
            if number is not None:
                found.append(
                    Runtime(
                        product="eclipse-temurin",
                        version=number,
                        approximate=True,
                        file=definition.file,
                        source=f"<{definition.name}>{definition.value}</{definition.name}>",
                    )
                )
    for path in _named(project, "build.gradle", "build.gradle.kts"):
        content = _read(read_text, path)
        if content is None:
            continue
        content = _without_comments(content)
        toolchain = _GRADLE_TOOLCHAIN.search(content)
        if toolchain is not None:
            source = " ".join(toolchain[0].split())
            found.append(_choice("eclipse-temurin", toolchain[1], path, source))
            continue
        compatibility = {match[1]: match for match in _GRADLE_COMPATIBILITY.finditer(content)}
        match = compatibility.get("targetCompatibility") or compatibility.get("sourceCompatibility")
        if match is not None:
            number = _java_number((match[2] or match[3] or "").replace("_", "."))
            if number is not None:
                found.append(
                    Runtime(
                        product="eclipse-temurin",
                        version=number,
                        approximate=True,
                        file=path,
                        source=" ".join(match[0].split()),
                    )
                )
    return found


def _java_number(value: str) -> str | None:
    """La version de Java d'une valeur : ``1.8`` → ``8``, ``17`` → ``17`` ; ``None`` sinon."""
    match = re.fullmatch(r"\s*(?:1\.)?(\d+)(?:\.\d+)*\s*", value)
    return None if match is None else match[1]


def _without_comments(script: str) -> str:
    """Un script Gradle sans ses commentaires ``//`` en début de ligne ni ``/* … */``."""
    script = re.sub(r"/\*.*?\*/", " ", script, flags=re.S)
    return re.sub(r"^\s*//.*$", "", script, flags=re.M)


def _dotnet(project: Project, read_text: ReadText) -> list[Runtime]:
    found = []
    for framework in nuget.target_frameworks(project, read_text):
        runtime = target_framework(framework.value, file=framework.file, source=framework.written)
        if runtime is not None:
            found.append(runtime)
    return found


def target_framework(value: str, *, file: str, source: str) -> Runtime | None:
    """Le runtime d'un framework cible : ``net8.0`` → .NET 8.0, ``netcoreapp3.1`` → .NET 3.1,
    ``net48`` → .NET Framework 4.8, ``v4.7.2`` (``TargetFrameworkVersion``) → .NET Framework
    4.7.2 ; ``None`` pour ``netstandard2.0`` et ce qu'on ne reconnaît pas."""
    value = value.strip()
    core = _TFM_CORE.fullmatch(value)
    if core is not None and (value.lower().startswith("netcoreapp") or "." in value):
        return _choice("dotnet", core[1], file, source)
    framework = _TFM_FRAMEWORK.fullmatch(value)
    if framework is not None:
        version = ".".join(part for part in framework.groups() if part)
        return _choice("dotnetfx", version, file, source)
    legacy = _TFV.fullmatch(value)
    if legacy is not None and value.lower().startswith("v"):
        return _choice("dotnetfx", legacy[1], file, source)
    return None


def _rust(project: Project, read_text: ReadText) -> list[Runtime]:
    found = []
    for path in _named(project, rust.MANIFEST):
        data = _toml(read_text, path)
        value, where = _get(data, "package", "rust-version"), path
        if isinstance(value, dict) and value.get("workspace") is True:
            root = rust.read_workspace_root(dirname(path), read_text)
            value, where = None, path
            if root is not None:
                where = root[0]
                try:
                    value = _get(tomllib.loads(root[1]), "workspace", "package", "rust-version")
                except tomllib.TOMLDecodeError:
                    value = None
        if isinstance(value, str) and _VERSION.fullmatch(value.strip()):
            found.append(
                Runtime(
                    product="rust",
                    version=value.strip(),
                    approximate=True,
                    file=where,
                    source=f'rust-version = "{value.strip()}"',
                )
            )
    return found


_MANIFESTS: dict[Ecosystem, Callable[[Project, ReadText], list[Runtime]]] = {
    Ecosystem.PYPI: _python,
    Ecosystem.NPM: _node,
    Ecosystem.GO: _go,
    Ecosystem.PACKAGIST: _php,
    Ecosystem.RUBYGEMS: _ruby,
    Ecosystem.MAVEN: _java,
    Ecosystem.NUGET: _dotnet,
    Ecosystem.CRATES_IO: _rust,
}


# ---------------------------------------------------------------------------
# Les fichiers de runtime
# ---------------------------------------------------------------------------


def _runtime_file(path: str, read_text: ReadText) -> list[Runtime]:
    content = _read(read_text, path)
    if content is None:
        return []
    name = posixpath.basename(path).lower()
    reader = _FILES.get(name)
    if reader is not None:
        return [runtime for runtime in reader(path, content) if runtime is not None]
    if ci_base(path) is not None:
        return ci(path, content)
    return dockerfile(path, content)


def _first_line(content: str) -> str | None:
    """La première ligne qui n'est ni vide ni un commentaire, sans ce qui suit un ``#``."""
    for line in content.splitlines():
        line = line.partition("#")[0].strip()
        if line:
            return line
    return None


def _choice(product: str, version: str, file: str, source: str) -> Runtime:
    """Une version choisie (pas une borne basse), sans le ``v`` de tête."""
    return Runtime(product=product, version=version.strip().lstrip("vV"), file=file, source=source)


def _python_version(path: str, content: str) -> list[Runtime | None]:
    # pyenv et uv : « 3.8.10 », « 3.12 », « 3.13t » ; pas « pypy3.9 », « system », « miniconda3 ».
    line = _first_line(content)
    if line is None:
        return []
    first = line.split()[0]
    match = re.fullmatch(r"(?:cpython-?)?(\d+\.\d+(?:\.\d+)?)t?(?:[-+].*)?", first)
    return [None if match is None else _choice("python", match[1], path, first)]


def _runtime_txt(path: str, content: str) -> list[Runtime | None]:
    # Heroku : « python-3.8.10 ».
    line = _first_line(content) or ""
    match = re.fullmatch(r"python-(\d+\.\d+(?:\.\d+)?)", line)
    return [None if match is None else _choice("python", match[1], path, line)]


def _node_version(path: str, content: str) -> list[Runtime | None]:
    # nvm : « 16 », « v16.20.2 », « lts/gallium » ; pas « lts/* », « node », « stable ».
    line = _first_line(content)
    if line is None:
        return []
    codename = re.fullmatch(r"lts/(\w+)", line.lower())
    if codename is not None and codename[1] in NODE_CODENAMES:
        return [_choice("nodejs", NODE_CODENAMES[codename[1]], path, line)]
    match = _VERSION.fullmatch(line)
    return [None if match is None else _choice("nodejs", match[1], path, line)]


def _ruby_version(path: str, content: str) -> list[Runtime | None]:
    # rbenv : « 3.2.2 », « ruby-3.2.2 » ; pas « jruby-9.4 ».
    line = _first_line(content)
    if line is None:
        return []
    match = re.fullmatch(r"(?:ruby-)?(\d+\.\d+(?:\.\d+)?)(?:-?p\d+)?", line.split()[0])
    return [None if match is None else _choice("ruby", match[1], path, line)]


def _tool_versions(path: str, content: str) -> list[Runtime | None]:
    # asdf et mise : « nodejs 16.20.2 », « python 3.8.10 3.9.1 » (la première),
    # « java temurin-17.0.2+8 ».
    found: list[Runtime | None] = []
    for line in content.splitlines():
        words = line.partition("#")[0].split()
        if len(words) < 2:
            continue
        tool, version = words[0].lower(), words[1]
        if tool == "java":
            # Comme ``mise.toml`` : « java 17 », sans distribution, est Temurin (E35 : il
            # n'était pas lu).
            vendor, _, number = version.rpartition("-")
            product = _JAVA_VENDORS.get(vendor.lower(), "eclipse-temurin" if not vendor else None)
            java = _java_number(_LEADING.match(number)[1]) if _LEADING.match(number) else None
            if product is not None and java is not None:
                found.append(_choice(product, java, path, f"{words[0]} {version}"))
            continue
        product = _TOOLS.get(tool)
        match = _VERSION.fullmatch(version)
        if product is not None and match is not None:
            found.append(_choice(product, match[1], path, f"{words[0]} {version}"))
    return found


def _mise(path: str, content: str) -> list[Runtime | None]:
    # mise : « [tools] python = "3.11" », une liste (la première), une table (« version = »),
    # « java = "temurin-17" » ; pas « latest », « lts », « prefix:3 ».
    try:
        tools = _get(tomllib.loads(content), "tools")
    except tomllib.TOMLDecodeError:
        return []
    found: list[Runtime | None] = []
    for tool, value in (tools or {}).items() if isinstance(tools, dict) else []:
        if isinstance(value, list):
            value = value[0] if value else None
        if isinstance(value, dict):
            value = value.get("version")
        if not isinstance(value, str):
            continue
        source = f'{tool} = "{value}"'
        if tool.lower() == "java":
            vendor, _, number = value.rpartition("-")
            product = _JAVA_VENDORS.get(vendor.lower(), "eclipse-temurin" if not vendor else None)
            leading = _LEADING.match(number)
            java = _java_number(leading[1]) if leading else None
            if product is not None and java is not None:
                found.append(_choice(product, java, path, source))
            continue
        product = _TOOLS.get(tool.lower())
        match = _VERSION.fullmatch(value.strip())
        if product is not None and match is not None:
            found.append(_choice(product, match[1], path, source))
    return found


def _global_json(path: str, content: str) -> list[Runtime | None]:
    try:
        data = json.loads(content)
    except ValueError:
        return []
    version = _get(data, "sdk", "version")
    if not isinstance(version, str) or _VERSION.fullmatch(version.strip()) is None:
        return []
    return [_choice("dotnet", version, path, f'sdk.version = "{version}"')]


def _rust_toolchain(path: str, content: str) -> list[Runtime | None]:
    # rustup : « [toolchain] channel = "1.80.0" » ; l'ancien « rust-toolchain » peut n'avoir que
    # la ligne « 1.80.0 ». Rien pour « stable » ni « nightly-2026-01-01 » ; « 1.80.0-x86_64-… »
    # donne 1.80.0.
    try:
        channel = _get(tomllib.loads(content), "toolchain", "channel")
    except tomllib.TOMLDecodeError:
        channel = _first_line(content)
    if not isinstance(channel, str):
        return []
    match = re.fullmatch(r"(\d+\.\d+(?:\.\d+)?)(?:-.*)?", channel.strip())
    return [None if match is None else _choice("rust", match[1], path, f'channel = "{channel}"')]


_FILES: dict[str, Callable[[str, str], list[Runtime | None]]] = {
    ".python-version": _python_version,
    "runtime.txt": _runtime_txt,
    ".nvmrc": _node_version,
    ".node-version": _node_version,
    ".ruby-version": _ruby_version,
    ".tool-versions": _tool_versions,
    "global.json": _global_json,
    "rust-toolchain.toml": _rust_toolchain,
    "rust-toolchain": _rust_toolchain,
    "mise.toml": _mise,
    ".mise.toml": _mise,
}


def dockerfile(path: str, content: str) -> list[Runtime]:
    """Les runtimes des ``FROM`` d'un ``Dockerfile`` (voir la docstring du module)."""
    found = []
    arguments: dict[str, str] = {}
    seen_from = False
    for line in _instructions(content):
        keyword, _, rest = line.partition(" ")
        keyword = keyword.upper()
        if keyword == "ARG" and not seen_from:
            name, equals, default = rest.strip().partition("=")
            if equals:
                arguments[name.strip()] = default.strip().strip("\"'")
        elif keyword == "FROM":
            seen_from = True
            words = [w for w in rest.split() if not w.startswith("--")]
            if not words:
                continue
            runtime = _image(path, words[0], arguments)
            if runtime is not None:
                found.append(runtime)
    return found


def _instructions(content: str) -> Iterator[str]:
    """Les instructions d'un ``Dockerfile``, sans les commentaires, les lignes continuées (``\\``)
    réunies."""
    pending = ""
    for raw in content.splitlines():
        line = raw.strip()
        if not pending and (not line or line.startswith("#")):
            continue
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        line, pending = (pending + line).strip(), ""
        if line:
            yield line
    if pending.strip():
        yield pending.strip()


def _workflow_path(path: str) -> bool:
    """Vrai pour un workflow de GitHub Actions (``.github/workflows/*.yml``)."""
    return ci_base(path) is not None and posixpath.basename(path).lower() not in (
        ".gitlab-ci.yml",
        "bitbucket-pipelines.yml",
    )


def ci(path: str, content: str) -> list[Runtime]:
    """Les runtimes d'un fichier de CI (voir la docstring du module) : un workflow de GitHub
    Actions, ``.gitlab-ci.yml`` ou ``bitbucket-pipelines.yml``. Sans doublon."""
    try:
        # Toutes les valeurs en chaînes (« node-version: 20.10 » reste 20.10, pas 20.1), et
        # aucun objet construit : BaseLoader ne fait que des tables, des listes et des chaînes.
        data = yaml.load(content, Loader=yaml.BaseLoader)
    except yaml.YAMLError:
        return []
    if posixpath.basename(path).lower() in (".gitlab-ci.yml", "bitbucket-pipelines.yml"):
        variables = _strings(_get(data, "variables"))
        found = [_image(path, image, variables, "image:") for image in _ci_images(data)]
    else:
        found = _workflow(path, data)
    return list(dict.fromkeys(runtime for runtime in found if runtime is not None))


def _workflow(path: str, data: Any) -> list[Runtime | None]:
    """Les runtimes des actions ``setup-*`` (``_SETUPS``) et l'image des ``container`` d'un
    workflow."""
    jobs = _get(data, "jobs")
    found: list[Runtime | None] = []
    for job in jobs.values() if isinstance(jobs, dict) else []:
        if not isinstance(job, dict):
            continue
        matrix = _get(job, "strategy", "matrix")
        env = {**_strings(_get(data, "env")), **_strings(job.get("env"))}
        container = job.get("container")
        image = container.get("image") if isinstance(container, dict) else container
        for reference in _expanded(image, matrix, env):
            found.append(_image(path, reference, {}, "container:"))
        steps = job.get("steps")
        for step in steps if isinstance(steps, list) else []:
            uses = step.get("uses") if isinstance(step, dict) else None
            if not isinstance(uses, str):
                continue
            action = uses.lower().partition("@")[0]
            setup = _SETUPS.get(action)
            if setup is None:
                continue
            key, product = setup
            wanted = _get(step, "with", key)
            if product == "eclipse-temurin":
                distribution = _get(step, "with", "distribution")
                product = _DISTRIBUTIONS.get(str(distribution or "").lower(), product)
            for version in _expanded(wanted, matrix, {**env, **_strings(step.get("env"))}):
                source = f"{action} : {key} {version}"
                if product == "nodejs":
                    found.append(_node_line(version, path, source))
                else:
                    found.append(_setup_version(product, version, path, source))
    return found


_SETUPS = {
    "actions/setup-node": ("node-version", "nodejs"),
    "actions/setup-python": ("python-version", "python"),
    "actions/setup-go": ("go-version", "go"),
    "actions/setup-java": ("java-version", "eclipse-temurin"),
    "actions/setup-dotnet": ("dotnet-version", "dotnet"),
    "ruby/setup-ruby": ("ruby-version", "ruby"),
    "shivammathur/setup-php": ("php-version", "php"),
}
"""Les actions qui installent un runtime (E34), l'entrée de sa version, et ce runtime."""
_DISTRIBUTIONS = {
    "temurin": "eclipse-temurin",
    "adopt": "eclipse-temurin",
    "adopt-hotspot": "eclipse-temurin",
    "adopt-openj9": "eclipse-temurin",
    "zulu": "azul-zulu",
    "corretto": "amazon-corretto",
}
"""La ``distribution`` d'``actions/setup-java`` ; les autres se lisent comme Eclipse Temurin."""


def _setup_version(product: str, text: str, path: str, source: str) -> Runtime | None:
    """La version d'une action ``setup-*`` : ``3.11``, ``1.21.x``, ``8.0.x`` ; ``None`` pour
    ``3.x``, ``stable``, ``head``, ``pypy3.9`` ou une plage."""
    value = re.sub(r"(?:\.[x*])+$", "", text.strip().strip("\"'").lower())
    match = _VERSION.fullmatch(value)
    if match is None:
        return None
    version = match[1]
    if product in ("eclipse-temurin", "amazon-corretto", "azul-zulu"):
        java = _java_number(version)
        return None if java is None else _choice(product, java, path, source)
    if "." not in version and product in ("python", "go", "ruby", "php", "dotnet"):
        return None  # « 3 » : toute une majeure, pas une version
    return _choice(product, version, path, source)


_EXPRESSION = re.compile(r"\$\{\{\s*(\w+)\.([\w-]+)\s*\}\}")


def _expanded(value: Any, matrix: Any, env: dict[str, str]) -> list[str]:
    """``value`` avec ses ``${{ matrix.x }}`` (chaque valeur de la ``matrix``, ``include``
    compris) et ses ``${{ env.x }}`` remplacés ; rien pour une autre expression, ou une valeur qui
    n'est pas une chaîne."""
    if not isinstance(value, str) or not value.strip():
        return []
    choices: dict[str, list[str]] = {}
    for scope, name in _EXPRESSION.findall(value):
        if scope == "env" and name in env:
            choices[f"env.{name}"] = [env[name]]
        elif scope == "matrix" and isinstance(matrix, dict):
            values = matrix.get(name)
            listed = [v for v in values if isinstance(v, str)] if isinstance(values, list) else []
            include = matrix.get("include")
            for entry in include if isinstance(include, list) else []:
                if isinstance(entry, dict) and isinstance(entry.get(name), str):
                    listed.append(entry[name])
            choices[f"matrix.{name}"] = listed
        else:
            return []
    if not choices:
        return [] if "${{" in value else [value.strip()]
    found = []
    for combination in itertools.product(*choices.values()):
        replaced = dict(zip(choices, combination, strict=True))
        text = _EXPRESSION.sub(lambda m, r=replaced: r[f"{m[1]}.{m[2]}"], value).strip()
        if "${{" not in text:
            found.append(text)
    return list(dict.fromkeys(found))


def _node_line(text: str, path: str, source: str) -> Runtime | None:
    """La version de Node.js d'un ``node-version`` : ``22``, ``22.x``, ``v20.10.0``,
    ``lts/jod`` ; ``None`` pour ``lts/*``, ``latest``, ``node`` ou une plage."""
    value = text.strip().strip("\"'").lower()
    codename = re.fullmatch(r"lts/(\w+)", value)
    if codename is not None:
        version = NODE_CODENAMES.get(codename[1])
        return None if version is None else _choice("nodejs", version, path, source)
    value = re.sub(r"(?:\.[x*])+$", "", value)
    match = _VERSION.fullmatch(value)
    return None if match is None else _choice("nodejs", match[1], path, source)


def _ci_images(data: Any) -> Iterator[str]:
    """Les ``image`` d'un ``.gitlab-ci.yml`` ou d'un ``bitbucket-pipelines.yml``, où qu'elles
    soient (celle de tout le fichier, de ``default``, d'un job ou d'une étape) : une chaîne, ou le
    ``name`` d'une table."""
    if isinstance(data, dict):
        for key, value in data.items():
            if key == "image":
                image = value.get("name") if isinstance(value, dict) else value
                if isinstance(image, str):
                    yield image
            else:
                yield from _ci_images(value)
    elif isinstance(data, list):
        for item in data:
            yield from _ci_images(item)


def _strings(data: Any) -> dict[str, str]:
    """Les valeurs en chaînes d'une table (``env``, ``variables``) ; vide sinon."""
    if not isinstance(data, dict):
        return {}
    return {key: value for key, value in data.items() if isinstance(value, str)}


def _image(
    path: str, reference: str, arguments: dict[str, str], label: str = "FROM"
) -> Runtime | None:
    def substitute(match: re.Match[str]) -> str:
        name = match[1] or match[3]
        value = arguments.get(name)
        if value is None and match[2] is not None:
            value = match[2]
        return value if value is not None else match[0]

    resolved = _DOCKER_VARIABLE.sub(substitute, reference)
    if "$" in resolved:
        return None
    image = resolved.partition("@")[0]
    name, tag = image, ""
    if ":" in image.rsplit("/", 1)[-1]:
        name, _, tag = image.rpartition(":")
    name = name.lower()
    for prefix in ("docker.io/", "index.docker.io/", "registry-1.docker.io/", *_MIRRORS):
        name = name.removeprefix(prefix)
    name = name.removeprefix("library/")
    product = IMAGES.get(name)
    if product is None or not tag:
        return None
    source = f"{label} {resolved}"
    if product == "nodejs":
        codename = tag.split("-")[0].lower()
        if codename in NODE_CODENAMES:
            return _choice("nodejs", NODE_CODENAMES[codename], path, source)
    if name.startswith("mcr.microsoft.com/devcontainers/"):
        match = _DEVCONTAINER.fullmatch(tag)
    else:
        match = _LEADING.match(tag)
    if match is None:
        return None
    version = match[1]
    if product in ("eclipse-temurin", "amazon-corretto"):
        java = _java_number(version)
        return None if java is None else _choice(product, java, path, source)
    return _choice(product, version, path, source)


# ---------------------------------------------------------------------------
# Outils
# ---------------------------------------------------------------------------


def _toml(read_text: ReadText, path: str) -> Any:
    content = _read(read_text, path)
    if content is None:
        return {}
    try:
        return tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        return {}


def _json(read_text: ReadText, path: str) -> Any:
    content = _read(read_text, path)
    if content is None:
        return {}
    try:
        return json.loads(content)
    except ValueError:
        return {}


def _get(data: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data
