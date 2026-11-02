"""Reconnaître un fichier de code (E28) : ni un manifeste ni un lockfile, mais du code d'un
langage dont forceupdate connaît l'écosystème (``app.py``, ``index.ts``, ``main.go``…).

Choisi seul, un fichier de code est analysé à travers le projet qui le contient (le premier
manifeste de son écosystème au-dessus de lui, voir ``sources.local``), ou, sans projet, par ses
imports : ceux d'un fichier Python, JavaScript ou TypeScript, ou Go (``READ_ALONE``). Un script
Python à bloc PEP 723 est son propre manifeste (``parsers.python``).

Comme ``detect.manifests``, tout se fait sur des chemins POSIX, sans lire les fichiers.
"""

from pathlib import PurePath

from forceupdate.detect.languages import ecosystem_for_language, language_for
from forceupdate.detect.manifests import match_dependency_file
from forceupdate.models import Ecosystem

READ_ALONE: dict[str, Ecosystem] = {
    ".py": Ecosystem.PYPI,
    ".pyw": Ecosystem.PYPI,
    ".js": Ecosystem.NPM,
    ".mjs": Ecosystem.NPM,
    ".cjs": Ecosystem.NPM,
    ".jsx": Ecosystem.NPM,
    ".ts": Ecosystem.NPM,
    ".mts": Ecosystem.NPM,
    ".cts": Ecosystem.NPM,
    ".tsx": Ecosystem.NPM,
    ".go": Ecosystem.GO,
    ".ipynb": Ecosystem.PYPI,
    ".vue": Ecosystem.NPM,
    ".svelte": Ecosystem.NPM,
}
"""Les extensions des fichiers dont forceupdate lit les imports, sans projet autour, et leur
écosystème. Comparées sans tenir compte de la casse. Pas les ``.pyi`` (des annotations de
types). Un carnet Jupyter (``.ipynb``) par ses cellules de code, un ``.vue`` ou un ``.svelte`` par
ses ``<script>`` (E34)."""


def code_language(path: str | PurePath) -> str | None:
    """Le langage d'un fichier de code (``Python``, ``TypeScript``…) ; ``None`` pour un manifeste,
    un lockfile, ou un fichier qui n'est pas du code d'un langage reconnu."""
    posix = PurePath(path).as_posix()
    if match_dependency_file(posix) is not None:
        return None
    return language_for(posix)


def code_ecosystem(path: str | PurePath) -> Ecosystem | None:
    """L'écosystème d'un fichier de code (``app.py`` → PyPI, ``index.ts`` → npm) ; ``None``
    pour un manifeste, un lockfile, ou un langage sans écosystème que forceupdate lit (C,
    Shell…)."""
    language = code_language(path)
    return ecosystem_for_language(language) if language is not None else None


def is_code_file(path: str | PurePath) -> bool:
    """Vrai pour un fichier de code d'un langage dont forceupdate connaît l'écosystème : on peut
    le choisir (voir la docstring du module)."""
    return code_ecosystem(path) is not None


def read_alone(path: str | PurePath) -> Ecosystem | None:
    """L'écosystème dont forceupdate lit les imports dans ce fichier, sans projet autour
    (``READ_ALONE``) ; ``None`` sinon."""
    if code_ecosystem(path) is None:
        return None
    return READ_ALONE.get(PurePath(path).suffix.lower())
