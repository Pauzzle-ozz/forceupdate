"""La mise à jour d'une source locale, de bout en bout : ce qu'enchaînent ``forceupdate update``
et l'API (``web/``), pour que les deux fassent exactement la même chose.

1. ``prepare`` : la sélection validée (``planner.chosen``), les réécritures et leurs diffs
   (``writers.prepare``), puis les lockfiles à régénérer (``lockfiles.plan``). Rien n'est écrit ;
2. ``uncommitted`` : le garde-fou, les fichiers à toucher qui ont des changements que git n'a
   pas en commit (``git.uncommitted``) ;
3. ``apply`` : l'écriture (``writers.write``), puis la régénération des lockfiles
   (``lockfiles.regenerate``).

Entre ``prepare`` et ``apply``, c'est le même ``Prepared`` qui passe : ``writers.write`` refuse
d'écrire un fichier qui a changé depuis le diff.
"""

from collections.abc import Callable
from dataclasses import dataclass

from forceupdate.models import Event, EventKind, Report
from forceupdate.sources.local import LocalSource
from forceupdate.update import git, lockfiles, planner, writers
from forceupdate.update.lockfiles import Job, Regenerated
from forceupdate.update.writers import Changes


@dataclass(frozen=True, kw_only=True)
class Prepared:
    """Ce que fera une mise à jour, calculé sans rien écrire."""

    changes: Changes
    """Les fichiers réécrits et leurs diffs, les options appliquées et celles qui ne le sont pas."""
    jobs: tuple[Job, ...] = ()
    """Les lockfiles à régénérer ensuite, dans l'ordre (``lockfiles.plan``)."""

    @property
    def runnable(self) -> tuple[Job, ...]:
        """Les lockfiles dont l'outil est installé : ceux qui seront régénérés."""
        return tuple(job for job in self.jobs if job.program is not None)

    @property
    def touched(self) -> list[str]:
        """Les fichiers que la mise à jour écrira : les manifestes réécrits, puis les lockfiles
        régénérés."""
        return [change.path for change in self.changes.files] + [
            job.lockfile for job in self.runnable
        ]

    @property
    def empty(self) -> bool:
        """Vrai s'il n'y a rien à écrire ni à lancer."""
        return not self.touched


def prepare(
    source: LocalSource,
    report: Report,
    selection: planner.Selection,
    *,
    regenerate: bool = True,
) -> Prepared:
    """Ce que fera la mise à jour de ``selection``, dans ``source`` analysée par ``report``.

    ``regenerate=False`` : aucun lockfile n'est prévu (un fichier envoyé par l'interface, dont
    on ne rend que la version réécrite). Lève ``ValueError`` pour une sélection qui ne
    correspond pas au rapport (``planner.chosen``), ou un lockfile que forceupdate ne sait pas
    régénérer (``lockfiles.plan``)."""
    changes = writers.prepare(source.root, planner.chosen(report, selection))
    jobs = lockfiles.plan(source, report, changes) if regenerate else ()
    return Prepared(changes=changes, jobs=jobs)


def uncommitted(source: LocalSource, prepared: Prepared) -> list[str] | None:
    """Les fichiers que la mise à jour écrira et qui ont des changements que git n'a pas en
    commit ; ``None`` hors d'un dépôt git (rien ne permettra alors de revenir en arrière)."""
    return git.uncommitted(source.root, prepared.touched)


def apply(
    source: LocalSource,
    report: Report,
    prepared: Prepared,
    *,
    on_event: Callable[[Event], None] | None = None,
) -> tuple[Regenerated, ...]:
    """Écrit les fichiers de ``prepared``, puis régénère ses lockfiles ; rend ce qu'il est
    advenu de chacun. Lève ``writers.WriteError`` sans rien écrire si un fichier a changé depuis
    ``prepare``.

    ``on_event`` reçoit les ``Event`` de la mise à jour : ``WRITTEN``, un ``REGENERATING`` par
    outil lancé, puis ``FINISHED``. Peut durer plusieurs minutes (``lockfiles.LOCK_TIMEOUT`` par
    commande) : l'interface l'appelle hors de la boucle de son serveur."""
    emit = on_event or _ignore
    writers.write(source.root, prepared.changes)
    emit(Event(kind=EventKind.WRITTEN, total=len(prepared.changes.files)))
    results = lockfiles.regenerate(
        source, report, prepared.changes, prepared.jobs, on_event=on_event
    )
    emit(Event(kind=EventKind.FINISHED))
    return results


def _ignore(_: Event) -> None:
    pass
