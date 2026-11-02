"""Les parseurs Java : un projet Maven (``pom.xml``, ``parsers.maven``) ou Gradle (``build.gradle``,
``build.gradle.kts``, ``gradle/libs.versions.toml``, ``parsers.gradle``), ou les deux.

Ni Maven ni Gradle n'ont de lockfile régénéré par forceupdate : les dépendances sont celles des
manifestes ; la version utilisée est la version exacte écrite (``Dependency.installed``), sinon la
borne basse d'une plage, ou celle des verrous de Gradle (``gradle.lockfile``, lus depuis E34, avec
les indirectes). Une mise à jour réécrit les manifestes, sans rien régénérer.
"""

import posixpath
from collections.abc import Sequence

from forceupdate.models import Notice, Project
from forceupdate.parsers.base import ReadText
from forceupdate.parsers.gradle import CATALOG, SCRIPTS, SETTINGS, parse_gradle_project
from forceupdate.parsers.maven import MANIFEST, parse_pom_project


def parse_project(project: Project, read_text: ReadText, project_dirs: Sequence[str]) -> None:
    """Lit les fichiers Java de ``project`` et remplit ses dépendances (le ``pom.xml``, puis le
    catalogue et les scripts Gradle), et à ``project.notices`` ce qui n'a pas pu être lu."""
    notices: list[Notice] = []
    pom = next((m for m in project.manifests if posixpath.basename(m) == MANIFEST), None)
    if pom is not None:
        project.dependencies.extend(parse_pom_project(pom, read_text, notices))
    gradle = [
        m
        for m in project.manifests
        if posixpath.basename(m) in (*SCRIPTS, *SETTINGS) or m.endswith(CATALOG)
    ]
    if gradle:
        project.dependencies.extend(
            parse_gradle_project(project.path, gradle, read_text, project_dirs, notices)
        )
    project.notices.extend(notices)
