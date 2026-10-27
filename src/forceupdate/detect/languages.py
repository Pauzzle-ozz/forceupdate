"""Les langages d'une source, et leur poids en octets, comme GitHub Linguist.

Le détecteur travaille sur une liste de ``(chemin, taille)``, sans lire les
fichiers : il sert tel quel à un dossier local et à l'arborescence d'un dépôt sur
une forge (E17).

Comme Linguist :

- le langage d'un fichier vient de son extension, ou de son nom (``Dockerfile``) ;
- seuls comptent les langages de programmation et de balisage. JSON, YAML, TOML ou
  Markdown sont des données ou de la prose : ils ne comptent pas ;
- les fichiers vendorisés (``vendor/``, ``*.min.js``), générés (``*.pb.go``) et la
  documentation (``docs/``) sont écartés.

Linguist lit aussi le contenu des fichiers et ``.gitattributes`` pour lever les
ambiguïtés. Ici on s'en tient au chemin : un ``.h`` va au C, ou au C++ (à
l'Objective-C) quand la source n'a pas de C.
"""

import re
from collections import Counter
from collections.abc import Iterable

from forceupdate.models import Ecosystem, Language

_EXTENSIONS: dict[str, str | None] = {
    ".py": "Python",
    ".pyw": "Python",
    ".pyi": "Python",
    ".pyx": "Cython",
    ".ipynb": "Jupyter Notebook",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".mts": "TypeScript",
    ".cts": "TypeScript",
    ".tsx": "TypeScript",
    ".coffee": "CoffeeScript",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".astro": "Astro",
    ".html": "HTML",
    ".htm": "HTML",
    ".xhtml": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sass": "Sass",
    ".less": "Less",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".gradle": None,
    ".gradle.kts": None,
    ".scala": "Scala",
    ".sc": "Scala",
    ".groovy": "Groovy",
    ".clj": "Clojure",
    ".cljs": "Clojure",
    ".cljc": "Clojure",
    ".cs": "C#",
    ".csx": "C#",
    ".fs": "F#",
    ".fsx": "F#",
    ".fsi": "F#",
    ".vb": "Visual Basic .NET",
    ".go": "Go",
    ".rs": "Rust",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".c++": "C++",
    ".hpp": "C++",
    ".hh": "C++",
    ".hxx": "C++",
    ".h++": "C++",
    ".ino": "C++",
    ".cu": "Cuda",
    ".cuh": "Cuda",
    ".m": "Objective-C",
    ".mm": "Objective-C++",
    ".swift": "Swift",
    ".rb": "Ruby",
    ".rake": "Ruby",
    ".gemspec": "Ruby",
    ".php": "PHP",
    ".phtml": "PHP",
    ".blade.php": "Blade",
    ".pl": "Perl",
    ".pm": "Perl",
    ".lua": "Lua",
    ".r": "R",
    ".dart": "Dart",
    ".ex": "Elixir",
    ".exs": "Elixir",
    ".erl": "Erlang",
    ".hrl": "Erlang",
    ".hs": "Haskell",
    ".lhs": "Haskell",
    ".ml": "OCaml",
    ".mli": "OCaml",
    ".jl": "Julia",
    ".zig": "Zig",
    ".nim": "Nim",
    ".elm": "Elm",
    ".cr": "Crystal",
    ".sol": "Solidity",
    ".asm": "Assembly",
    ".nasm": "Assembly",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".ksh": "Shell",
    ".ps1": "PowerShell",
    ".psm1": "PowerShell",
    ".psd1": "PowerShell",
    ".bat": "Batchfile",
    ".cmd": "Batchfile",
    ".mk": "Makefile",
    ".mak": "Makefile",
    ".cmake": "CMake",
    ".dockerfile": "Dockerfile",
    ".containerfile": "Dockerfile",
    ".tf": "HCL",
    ".tfvars": "HCL",
    ".hcl": "HCL",
    ".nix": "Nix",
    ".tex": "TeX",
}
"""Extension (en minuscules) → langage. L'extension la plus longue l'emporte :
``.blade.php`` avant ``.php``. ``None`` : un format de données pour Linguist
(``build.gradle``), qui ne compte pas."""

_FILENAMES: dict[str, str] = {
    "dockerfile": "Dockerfile",
    "containerfile": "Dockerfile",
    "makefile": "Makefile",
    "gnumakefile": "Makefile",
    "cmakelists.txt": "CMake",
    "gemfile": "Ruby",
    "rakefile": "Ruby",
    "vagrantfile": "Ruby",
}
"""Nom de fichier (en minuscules) → langage, pour les fichiers sans extension parlante."""

_ECOSYSTEMS: dict[str, Ecosystem] = {
    "Python": Ecosystem.PYPI,
    "Cython": Ecosystem.PYPI,
    "Jupyter Notebook": Ecosystem.PYPI,
    "JavaScript": Ecosystem.NPM,
    "TypeScript": Ecosystem.NPM,
    "CoffeeScript": Ecosystem.NPM,
    "Vue": Ecosystem.NPM,
    "Svelte": Ecosystem.NPM,
    "Astro": Ecosystem.NPM,
    "Rust": Ecosystem.CRATES_IO,
    "Go": Ecosystem.GO,
    "PHP": Ecosystem.PACKAGIST,
    "Blade": Ecosystem.PACKAGIST,
    "Ruby": Ecosystem.RUBYGEMS,
    "Java": Ecosystem.MAVEN,
    "Kotlin": Ecosystem.MAVEN,
    "Scala": Ecosystem.MAVEN,
    "Groovy": Ecosystem.MAVEN,
    "Clojure": Ecosystem.MAVEN,
    "C#": Ecosystem.NUGET,
    "F#": Ecosystem.NUGET,
    "Visual Basic .NET": Ecosystem.NUGET,
}
"""Langage → écosystème de paquets. Un langage absent n'a pas de gestionnaire de
paquets que forceupdate sait lire (C, C++, Swift, Shell, HTML…)."""

_VENDORED = re.compile(
    r"""
      (^|/)(node_modules|bower_components|jspm_packages|vendors?|extern(als?)?
            |third[-_]?party|3rd[-_]?party|Pods|Carthage|Godeps/_workspace|\.yarn)/
    | (^|/)(dist|cache|\.github|gradle/wrapper|\.mvn/wrapper)/
    | ^(deps|dependencies|debian)/
    | (^|/)(gradlew|gradlew\.bat|mvnw|mvnw\.cmd|configure|config\.guess|config\.sub)$
    | [.-]min\.(js|css)$
    | (^|/)jquery[^/]*\.js$
    | (^|/)bootstrap[^/]*\.(js|css)$
    """,
    re.VERBOSE | re.IGNORECASE,
)
"""Code de tiers recopié dans la source : les règles de ``vendor.yml`` de Linguist
qui se lisent sur le chemin."""

_GENERATED = re.compile(
    r"""
      (^|/)__generated__/
    | \.pb\.(go|cc|h)$
    | _pb2(_grpc)?\.pyi?$
    | \.designer\.(cs|vb)$
    | \.(g|freezed)\.dart$
    """,
    re.VERBOSE | re.IGNORECASE,
)
"""Code produit par un outil (protobuf, concepteurs .NET, build_runner Dart) : les
règles de ``generated.rb`` de Linguist qui se lisent sur le chemin."""

_DOCUMENTATION = re.compile(
    r"^(docs?|examples|demos?|samples?|man)/|(^|/)(documentation|javadoc|groovydoc)/",
    re.IGNORECASE,
)
"""Documentation et exemples, comme ``documentation.yml`` de Linguist : ``docs/``,
``examples/`` comptent à la racine seulement, ``documentation/`` partout."""


def language_for(path: str) -> str | None:
    """Le langage d'un fichier d'après son chemin POSIX ; ``None`` s'il ne compte pas."""
    name = path.rsplit("/", 1)[-1].lower()
    if name in _FILENAMES:
        return _FILENAMES[name]
    if name.startswith(("dockerfile.", "containerfile.")):
        return "Dockerfile"
    # L'extension la plus longue d'abord : « a.blade.php » essaie « .blade.php », puis « .php ».
    for index, char in enumerate(name):
        if char == "." and index > 0 and name[index:] in _EXTENSIONS:
            return _EXTENSIONS[name[index:]]
    return None


def is_excluded(path: str) -> bool:
    """Vrai si le fichier ne compte pas dans les langages : vendorisé, généré ou documentation."""
    return bool(_VENDORED.search(path) or _GENERATED.search(path) or _DOCUMENTATION.search(path))


def ecosystem_for_language(name: str) -> Ecosystem | None:
    """L'écosystème de paquets d'un langage ; ``None`` s'il n'en a pas de reconnu."""
    return _ECOSYSTEMS.get(name)


def detect_languages(files: Iterable[tuple[str, int]]) -> list[Language]:
    """Les langages de ``files``, une liste de ``(chemin POSIX, taille en octets)``.

    Triés du plus lourd au plus léger. Un langage qui pèse 0 octet n'apparaît pas.
    """
    sizes: Counter[str] = Counter()
    headers = 0
    for path, size in files:
        language = language_for(path)
        if language is None or is_excluded(path):
            continue
        if path.lower().endswith(".h"):
            headers += size
        else:
            sizes[language] += size
    if headers:
        sizes[_header_language(sizes)] += headers
    return [
        Language(name=name, bytes=size, ecosystem=ecosystem_for_language(name))
        for name, size in sorted(sizes.items(), key=lambda item: (-item[1], item[0]))
        if size > 0
    ]


def _header_language(sizes: Counter[str]) -> str:
    """À qui vont les ``.h`` : au C s'il y en a, sinon au C++ ou à l'Objective-C."""
    for language in ("C", "C++", "Objective-C"):
        if sizes[language]:
            return language
    return "C"
