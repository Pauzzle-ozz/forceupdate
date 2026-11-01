"""Les parseurs : lire les manifestes et lockfiles d'un projet, et en tirer ses dépendances.

Un module par écosystème : Python (E03), npm (E04), Rust (E21), Go (E22), PHP (E23) et Ruby (E24)
pour l'instant, les autres en phase F. Chacun relie les manifestes (dépendances directes,
contraintes et leur emplacement) aux lockfiles (versions installées, transitives), avec ce qui est
commun dans ``lockfiles.py``.
"""

import posixpath
from collections.abc import Callable, Sequence

from forceupdate.detect.manifests import ecosystem_for_manifest
from forceupdate.models import Ecosystem, Notice, Project
from forceupdate.parsers import go, npm, php, python, ruby, rust
from forceupdate.parsers.base import ParseError, ReadText
from forceupdate.parsers.lockfiles import Lockfile

__all__ = ["ParseError", "ReadText", "parse_lockfile", "parse_project"]

_PARSERS: dict[Ecosystem, Callable[[Project, ReadText, Sequence[str]], None]] = {
    Ecosystem.PYPI: lambda project, read_text, _: python.parse_project(project, read_text),
    Ecosystem.NPM: npm.parse_project,
    Ecosystem.CRATES_IO: lambda project, read_text, _: rust.parse_project(project, read_text),
    Ecosystem.GO: lambda project, read_text, _: go.parse_project(project, read_text),
    Ecosystem.PACKAGIST: lambda project, read_text, _: php.parse_project(project, read_text),
    Ecosystem.RUBYGEMS: lambda project, read_text, _: ruby.parse_project(project, read_text),
}

_LOCKFILE_PARSERS: dict[str, Callable[[str, str], Lockfile]] = {
    "package-lock.json": lambda path, text: npm.parse_package_lock_json(path, text).lockfile,
    "npm-shrinkwrap.json": lambda path, text: npm.parse_package_lock_json(path, text).lockfile,
    "yarn.lock": lambda path, text: npm.parse_yarn_lock(path, text).lockfile,
    "pnpm-lock.yaml": lambda path, text: npm.parse_pnpm_lock_yaml(path, text).lockfile,
    "uv.lock": python.parse_uv_lock,
    "poetry.lock": python.parse_poetry_lock,
    "pdm.lock": python.parse_pdm_lock,
    "Pipfile.lock": python.parse_pipfile_lock,
    "Cargo.lock": lambda path, text: rust.parse_cargo_lock(path, text).lockfile,
    "go.mod": go.locked_versions,
    "composer.lock": lambda path, text: php.parse_composer_lock(path, text).lockfile,
    "Gemfile.lock": lambda path, text: ruby.parse_gemfile_lock(path, text).lockfile,
    "gems.locked": lambda path, text: ruby.parse_gemfile_lock(path, text).lockfile,
}


def parse_project(project: Project, read_text: ReadText, project_dirs: Sequence[str] = ()) -> None:
    """Remplit ``project.dependencies`` en lisant ses fichiers avec ``read_text``.

    Ajoute à ``project.notices`` ce qui n'a pas pu être lu, et retire de
    ``project.lockfiles`` un lockfile de workspace dont le projet n'est pas membre.
    Un écosystème que forceupdate ne lit pas encore donne une remarque, pour que le
    rapport ne laisse pas croire que le projet n'a pas de dépendances.

    ``project_dirs`` sont les dossiers de tous les projets de la source : un
    workspace Yarn 1 ne liste pas ses membres dans son lockfile.
    """
    for ecosystem in project.ecosystems:
        parser = _PARSERS.get(ecosystem)
        if parser is not None:
            parser(project, read_text, project_dirs)
            continue
        files = project.manifests + project.lockfiles
        first = next(path for path in files if ecosystem_for_manifest(path) is ecosystem)
        message = f"dépendances {ecosystem} pas encore lues par forceupdate."
        project.notices.append(Notice(file=first, message=message))


def parse_lockfile(path: str, content: str) -> Lockfile:
    """Un lockfile seul, d'après son nom : ses paquets, et leur graphe s'il en a un. Un
    ``requirements*.txt`` est lu comme le ``.txt`` compilé de pip-tools ; un ``go.mod`` comme la
    liste des versions choisies (``go.sum`` n'en est pas une). Lève ``ParseError`` pour un
    fichier invalide, ``ValueError`` pour un nom qui n'est pas celui d'un lockfile."""
    parser = _LOCKFILE_PARSERS.get(posixpath.basename(path))
    if parser is not None:
        return parser(path, content)
    if path.endswith(".txt") and ecosystem_for_manifest(path) is Ecosystem.PYPI:
        return python.parse_pinned_requirements(path, content)
    raise ValueError(f"pas un lockfile connu : {path}")
