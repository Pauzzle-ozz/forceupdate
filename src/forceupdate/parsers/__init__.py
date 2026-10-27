"""Les parseurs : lire les manifestes et lockfiles d'un projet, et en tirer ses dépendances.

Un module par écosystème : Python (E03) et npm (E04) pour l'instant, les autres en
phase F. Chacun relie les manifestes (dépendances directes, contraintes et leur
emplacement) aux lockfiles (versions installées, transitives), avec ce qui est
commun dans ``lockfiles.py``.
"""

from collections.abc import Callable, Sequence

from forceupdate.detect.manifests import ecosystem_for_manifest
from forceupdate.models import Ecosystem, Notice, Project
from forceupdate.parsers import npm, python
from forceupdate.parsers.base import ParseError, ReadText

__all__ = ["ParseError", "ReadText", "parse_project"]

_PARSERS: dict[Ecosystem, Callable[[Project, ReadText, Sequence[str]], None]] = {
    Ecosystem.PYPI: lambda project, read_text, _: python.parse_project(project, read_text),
    Ecosystem.NPM: npm.parse_project,
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
