"""Un dépôt d'une forge, analysé par son API, sans le cloner (décision n°15 du brief).

``fetch`` prépare la source :

1. l'arborescence du dernier commit de la branche par défaut (``Forge.tree``), en un appel ;
   sans les dossiers jamais parcourus (``detect.manifests.is_ignored_path``) ;
2. les projets qu'on y trouve (``detect.manifests.find_projects``), comme pour un dossier ;
3. le téléchargement des seuls fichiers que les parseurs lisent, dans un dossier temporaire qui
   reproduit les chemins du dépôt. Pour les connaître, les parseurs tournent sur ce qui est
   déjà téléchargé, et on note ce qu'ils demandent : d'abord les manifestes et les lockfiles,
   puis ce que ceux-ci désignent (les ``-r`` et ``-c`` d'un ``requirements.txt``, le
   ``pyproject.toml`` racine d'un workspace uv, le ``pnpm-workspace.yaml`` d'un dossier
   parent). Ce qui est dans l'arborescence est téléchargé à son tour, jusqu'à ce qu'ils ne
   demandent plus rien de nouveau (``MAX_ROUNDS`` tours au plus). Un ``setup.py``, que le
   moteur ne lit pas, n'est pas téléchargé. Les lockfiles ne sont pas lus pendant ces tours :
   ils ne mènent à aucun autre fichier, et peuvent peser 50 Mo.

Le moteur lit ensuite ``ForgeSource`` comme un dossier : les langages viennent des chemins et
des tailles de l'arborescence, les dépendances des fichiers téléchargés. Le pipeline est celui
d'un dossier local, inchangé.

Les fichiers trop gros (``max_read_size`` : 2 Mo, 50 Mo pour un lockfile) ne sont pas
téléchargés : comme en local, ils ne sont pas lus, et le rapport le dit. GitLab ne donne pas
les tailles : ses fichiers sont téléchargés, puis écartés à la lecture s'ils sont trop gros.

Une arborescence que la forge a tronquée (GitHub : au-delà de 100 000 entrées ; GitLab, au-delà
de ``gitlab.MAX_TREE_PAGES`` pages) donnerait une
analyse partielle : ``clone`` fait alors un clone superficiel du même dépôt, analysé comme un
dossier (``ClonedSource``, E18).

Un sous-module (un autre dépôt, à un commit) n'est pas analysé, ni par l'API ni dans un clone
(fait sans eux) : le rapport le dit (``Source.notices``), comme pour un sous-module vide en
local ; sous un dossier jamais parcouru (``vendor/``…), rien.
"""

import asyncio
import logging
import posixpath
from collections.abc import Callable
from pathlib import Path

from forceupdate import config, parsers
from forceupdate.detect.manifests import (
    find_projects,
    is_ignored_path,
    match_dependency_file,
    max_read_size,
    safe_read_text,
)
from forceupdate.forges import git
from forceupdate.forges.base import Forge, Repository, Tree
from forceupdate.models import Event, EventKind, Notice
from forceupdate.sources.base import Source, SourceFile
from forceupdate.sources.local import LocalSource

logger = logging.getLogger(__name__)

MAX_ROUNDS = 8
"""Tours de téléchargement au plus : les manifestes, puis leurs lockfiles, puis un ``-r`` qui
mène à un fichier, qui peut en inclure un autre…"""
MAX_DOWNLOADS = 8
"""Fichiers téléchargés en même temps, pour un dépôt."""

SUBMODULE = "sous-module git : pas analysé (un autre dépôt, à analyser à part)."
"""La remarque d'un sous-module d'un dépôt d'une forge."""


class ForgeSource(Source):
    """Un dépôt, à un commit : l'arborescence donnée par la forge, et les fichiers de
    dépendances téléchargés dans ``root``."""

    def __init__(self, repo: Repository, tree: Tree, root: Path) -> None:
        self.repo = repo
        self.tree = tree
        self.root = root
        self.origin = repo.full_name
        # Une taille inconnue (GitLab ne la donne pas) compte pour 1 : les langages sont
        # alors pesés en fichiers, pas en octets.
        self._files = sorted(
            SourceFile(entry.path, 1 if entry.size is None else entry.size)
            for entry in tree.entries
            if not is_ignored_path(entry.path)
        )
        self._sizes = {entry.path: entry.size for entry in tree.entries}

    @property
    def truncated(self) -> bool:
        """La forge n'a pas rendu toute l'arborescence : l'analyse est partielle."""
        return self.tree.truncated

    @property
    def notices(self) -> list[Notice]:
        """Les sous-modules du dépôt, hors des dossiers jamais parcourus."""
        return [
            Notice(file=path, message=SUBMODULE)
            for path in sorted(self.tree.submodules)
            if not is_ignored_path(path)
        ]

    def files(self) -> list[SourceFile]:
        return list(self._files)

    def small_enough(self, path: str) -> bool:
        """``path`` peut être lu (``max_read_size``) : à télécharger. Une taille inconnue
        aussi ; il sera écarté à la lecture s'il est trop gros."""
        size = self._sizes.get(path)
        return size is None or size <= max_read_size(path)

    def read_text(self, path: str) -> str | None:
        """Le fichier téléchargé ; ``None`` s'il ne l'a pas été (absent du dépôt, trop gros).
        Lève ``ValueError`` si ``path`` sort du dépôt."""
        return safe_read_text(self.root / relative(path), max_size=max_read_size(path))


class ClonedSource(LocalSource):
    """Un dépôt cloné (superficiellement) : quand la forge n'en rend pas toute l'arborescence.
    Lu comme un dossier : ce que ``.gitignore`` écarte ne compte pas. Cloné sans ses
    sous-modules : ils sont dits comme ceux d'un dépôt lu par l'API."""

    truncated = False
    SUBMODULE = SUBMODULE

    def __init__(self, repo: Repository, commit: str, root: Path) -> None:
        super().__init__(root)
        self.repo = repo
        self.commit = commit
        self.origin = repo.full_name


async def clone(
    forge: Forge,
    repo: Repository,
    destination: Path,
    *,
    on_event: Callable[[Event], None] | None = None,
) -> ClonedSource:
    """Le dépôt ``repo``, cloné dans ``destination`` (superficiellement, la branche par
    défaut). Émet un ``cloning``. Lève une ``ForgeError`` (git absent ou en échec, token
    refusé…)."""
    (on_event or _ignore)(Event(kind=EventKind.CLONING))
    await forge.clone(repo, destination)
    commit = await asyncio.to_thread(git.head, destination)
    return await asyncio.to_thread(ClonedSource, repo, commit, destination)


def relative(path: str) -> str:
    """``path``, normalisé, depuis la racine du dépôt ; ``ValueError`` s'il en sort."""
    normalized = posixpath.normpath(path.replace("\\", "/"))
    if normalized.startswith(("/", "../")) or normalized == "..":
        raise ValueError(f"chemin hors du dépôt : {path}")
    return normalized


async def fetch(
    forge: Forge,
    repo: Repository,
    destination: Path,
    *,
    include_tests: bool = False,
    on_event: Callable[[Event], None] | None = None,
) -> ForgeSource:
    """La source du dépôt ``repo``, ses fichiers de dépendances téléchargés dans
    ``destination``. Émet un ``downloading`` par fichier téléchargé. Lève une ``ForgeError``
    (dépôt vide, token refusé, limite atteinte…) ou une ``NetworkError``."""
    emit = on_event or _ignore
    tree = await forge.tree(repo)
    source = ForgeSource(repo, tree, destination)
    listed = {file.path for file in source.files()}
    done: set[str] = set()
    # La configuration du projet d'abord (E29) : ses dossiers exclus ne sont pas téléchargés.
    first = {config.CONFIG_FILE, config.PYPROJECT} & listed
    for _ in range(MAX_ROUNDS):
        wanted = first if first and not done else _requested(source, include_tests)
        todo = sorted(
            path for path in wanted - done if path in listed and source.small_enough(path)
        )
        if not todo:
            break
        total = len(done) + len(todo)
        emit(Event(kind=EventKind.DOWNLOADING, done=len(done), total=total))
        await _download_all(forge, repo, tree.commit, todo, destination, done, total, emit)
    return source


async def _download_all(
    forge: Forge,
    repo: Repository,
    commit: str,
    paths: list[str],
    destination: Path,
    done: set[str],
    total: int,
    emit: Callable[[Event], None],
) -> None:
    slots = asyncio.Semaphore(MAX_DOWNLOADS)

    async def download(path: str) -> None:
        async with slots:
            content = await forge.read_file(repo, path, commit)
        if content is not None:
            _write(destination, path, content)
        done.add(path)
        emit(Event(kind=EventKind.DOWNLOADING, done=len(done), total=total))

    await asyncio.gather(*(download(path) for path in paths))


def _write(destination: Path, path: str, content: bytes) -> None:
    """Range ``content`` à ``path`` sous ``destination``. Un chemin que le système refuse (un
    nom réservé sous Windows : ``aux/``, ``con.txt``…) n'est pas écrit : le fichier ne sera pas
    lu, et le rapport le dira."""
    target = destination / path
    try:
        if not target.resolve().is_relative_to(destination.resolve()):
            raise ValueError(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    except (OSError, ValueError) as err:
        logger.warning("%s : fichier non écrit (%s)", path, err)


def _requested(source: ForgeSource, include_tests: bool) -> set[str]:
    """Les fichiers que les parseurs demandent, sur ce qui est déjà téléchargé, et la
    configuration du projet (``forceupdate.toml``, ``pyproject.toml``, E29). Les lockfiles
    ne sont pas lus (rien ne les suit, et ils sont gros)."""
    asked: set[str] = set()

    def read(path: str) -> str | None:
        normalized = relative(path)
        asked.add(normalized)
        match = match_dependency_file(normalized)
        if match is not None and match.lockfile:
            return None
        return source.read_text(normalized)

    # La configuration du projet (E29) : demandée au premier tour, suivie aux suivants.
    configuration = config.read(read)
    paths = [file.path for file in source.files()]
    if configuration is not None:
        include_tests = include_tests or configuration.include_tests
        paths = [path for path in paths if not config.is_excluded_path(path, configuration.exclude)]
    projects, _ = find_projects(paths, include_tests=include_tests)
    directories = [project.path for project in projects]
    for project in projects:
        parsers.parse_project(project, read, directories)
    return asked


def _ignore(_: Event) -> None:
    pass
