"""Les tâches de fond du serveur : les analyses, et l'application des plans de mise à jour.

Rien de cela ne tourne dans la boucle ``asyncio`` qui répond aux requêtes : lire un gros
document npm (``next`` : 31 Mo) prend une seconde sans rendre la main, une régénération de
lockfile plusieurs minutes.

- **Les analyses** tournent dans une boucle à elles, dans son propre thread (``Worker``), avec
  un ``HttpClient`` et un ``Cache`` partagés par toutes : un paquet demandé par une analyse est
  en cache pour la suivante, et les limites par hôte valent pour toutes. Une analyse est une
  tâche de cette boucle : l'annuler l'interrompt à sa prochaine attente (une requête).
- **Les mises à jour** (``update.local.apply`` : écriture, puis outils de lockfile) tournent
  dans un thread à part, une à la fois : deux outils ne réécrivent jamais les mêmes fichiers en
  même temps. Une mise à jour ne s'annule pas : interrompre un outil à mi-chemin laisserait des
  fichiers à moitié faits (si l'outil échoue, ``lockfiles.regenerate`` remet tout comme avant).
- **L'état** de chaque tâche (``Scan``, ``Plan`` : statut, événements de progression, résultat)
  n'est modifié que dans la boucle du serveur : les threads lui envoient leurs événements et
  leur résultat par ``call_soon_threadsafe``. Les routes le lisent donc sans verrou.

Les analyses et les plans restent en mémoire, le temps de la session (les ``MAX_SCANS`` plus
récentes) ; seuls les derniers chemins analysés sont gardés sur le disque (``Recent``).
"""

import asyncio
import concurrent.futures
import contextlib
import json
import logging
import secrets
import shutil
import threading
from collections.abc import AsyncIterator, Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from forceupdate import engine
from forceupdate.models import Event, Report, ScanOptions, to_dict
from forceupdate.net import Cache, HttpClient
from forceupdate.report import json as json_report
from forceupdate.sources.local import LocalSource
from forceupdate.update import local, writers
from forceupdate.update.local import Prepared
from forceupdate.update.lockfiles import Regenerated
from forceupdate.web import schemas
from forceupdate.web.schemas import SourceKind, TaskStatus

logger = logging.getLogger(__name__)

MAX_SCANS = 20
"""Analyses gardées en mémoire ; au-delà, les plus anciennes finies sont oubliées, avec leurs
plans."""
MAX_RECENT = 10
"""Chemins récents gardés."""
PING_EVERY = 15.0
"""Secondes sans événement après lesquelles un flux SSE envoie un commentaire : un navigateur
parti est ainsi remarqué, et son flux fermé."""

T = TypeVar("T")


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return secrets.token_hex(6)


class Progress:
    """Les événements d'une tâche, gardés tous : un navigateur qui se branche en retard, ou se
    rebranche, les reçoit depuis le début (ou depuis le dernier reçu)."""

    def __init__(self) -> None:
        self.events: list[Event] = []
        self.finished = False
        self._wake = asyncio.Event()

    @property
    def last(self) -> Event | None:
        return self.events[-1] if self.events else None

    def add(self, event: Event) -> None:
        self.events.append(event)
        self._notify()

    def finish(self) -> None:
        self.finished = True
        self._notify()

    def _notify(self) -> None:
        self._wake.set()
        self._wake = asyncio.Event()

    async def follow(self, start: int = 0) -> AsyncIterator[tuple[int, Event] | None]:
        """Les événements à partir du n° ``start`` (``(n°, événement)``), puis ceux qui
        arrivent, jusqu'à la fin de la tâche. ``None`` après ``PING_EVERY`` secondes sans
        rien."""
        index = start
        while True:
            while index < len(self.events):
                yield index, self.events[index]
                index += 1
            if self.finished:
                return
            wake = self._wake
            try:
                await asyncio.wait_for(wake.wait(), PING_EVERY)
            except TimeoutError:
                yield None


@dataclass(eq=False, kw_only=True)
class Scan:
    """Une analyse lancée par l'interface."""

    id: str
    source: LocalSource
    kind: SourceKind
    label: str
    """Ce qu'on montre : le chemin choisi, ou le nom du fichier envoyé."""
    options: ScanOptions
    started_at: datetime = field(default_factory=_now)
    status: TaskStatus = TaskStatus.RUNNING
    finished_at: datetime | None = None
    error: str | None = None
    report: Report | None = None
    progress: Progress = field(default_factory=Progress)
    future: concurrent.futures.Future[Report] | None = None
    upload_dir: Path | None = None
    """Le dossier temporaire d'un fichier envoyé, effacé avec l'analyse."""

    def summary(self) -> schemas.ScanSummary:
        return schemas.ScanSummary(
            id=self.id,
            source=self.label,
            kind=self.kind,
            status=self.status,
            options=self.options,
            started_at=self.started_at,
            finished_at=self.finished_at,
            error=self.error,
            progress=self.progress.last,
        )

    def document(self) -> dict[str, Any]:
        """``ScanSummary``, plus ``report`` (le JSON de ``scan --format json``) une fois fini."""
        report = json_report.build(self.report) if self.report is not None else None
        return {**to_dict(self.summary()), "report": report}


@dataclass(eq=False, kw_only=True)
class Plan:
    """Un plan de mise à jour : la sélection, préparée sur le rapport d'une analyse."""

    id: str
    scan: Scan
    selection: dict[str, str]
    prepared: Prepared
    uncommitted: list[str] | None
    created_at: datetime = field(default_factory=_now)
    status: TaskStatus = TaskStatus.PLANNED
    finished_at: datetime | None = None
    error: str | None = None
    results: tuple[Regenerated, ...] = ()
    progress: Progress = field(default_factory=Progress)

    @property
    def applicable(self) -> bool:
        return (
            self.status is TaskStatus.PLANNED
            and self.scan.kind is not SourceKind.UPLOAD
            and not self.prepared.empty
        )

    def document(self) -> schemas.UpdatePlan:
        changes = self.prepared.changes
        uncommitted = None if self.uncommitted is None else tuple(self.uncommitted)
        return schemas.UpdatePlan(
            id=self.id,
            scan=self.scan.id,
            status=self.status,
            created_at=self.created_at,
            finished_at=self.finished_at,
            selection=self.selection,
            applied=tuple(schemas.chosen(choice) for choice in changes.applied),
            skipped=tuple(schemas.skipped_option(item) for item in changes.skipped),
            files=tuple(schemas.FileDiff(path=c.path, diff=c.diff) for c in changes.files),
            lockfiles=tuple(schemas.lock_job(job) for job in self.prepared.jobs),
            uncommitted=uncommitted,
            applicable=self.applicable,
            error=self.error,
            results=tuple(schemas.lock_result(result) for result in self.results),
            progress=self.progress.last,
        )


class Worker:
    """La boucle des analyses, dans son thread, avec le ``HttpClient`` et le ``Cache`` qu'elles
    partagent."""

    def __init__(self, cache: Cache) -> None:
        self.cache = cache
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="forceupdate-analyses", daemon=True)
        self.http: HttpClient | None = None

    def _run(self) -> None:
        # La boucle naît et meurt dans son thread : sous Windows, une boucle créée (ou fermée)
        # dans le thread principal y prendrait (ou y couperait) le réveil sur Ctrl+C
        # (``signal.set_wakeup_fd``), qui revient à la boucle du serveur.
        loop = self._loop = asyncio.new_event_loop()
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            loop.close()

    def start(self) -> None:
        self._thread.start()
        self._ready.wait()
        self.http = self.call(self._open())

    async def _open(self) -> HttpClient:
        return HttpClient()

    def submit(self, coroutine: Coroutine[Any, Any, T]) -> concurrent.futures.Future[T]:
        """Lance ``coroutine`` dans la boucle des analyses ; annuler le ``Future`` l'annule."""
        assert self._loop is not None, "Worker.start d'abord"
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop)

    def call(self, coroutine: Coroutine[Any, Any, T]) -> T:
        """Lance ``coroutine`` dans la boucle des analyses, et attend son résultat."""
        return self.submit(coroutine).result()

    async def analyze(
        self, source: LocalSource, options: ScanOptions, on_event: Callable[[Event], None]
    ) -> Report:
        """``engine.analyze``, avec le client et le cache partagés. Une analyse hors ligne a un
        client à elle (qui n'envoie rien), une analyse sans cache un cache désactivé."""
        http = None if options.offline else self.http
        cache = self.cache if options.cache else None
        return await engine.analyze(source, options, on_event=on_event, http=http, cache=cache)

    def stop(self) -> None:
        """Annule les analyses en cours, ferme le client et le cache, arrête la boucle."""
        if self._loop is not None and self._thread.is_alive():
            with contextlib.suppress(Exception):
                self.call(self._close())
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join()
        self.cache.close()

    async def _close(self) -> None:
        tasks = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.http is not None:
            await self.http.aclose()


class Recent:
    """Les derniers chemins analysés, gardés d'une session à l'autre dans un fichier JSON. Le
    fichier est jetable : illisible, il est ignoré ; impossible à écrire, tant pis."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[str]:
        try:
            paths = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(paths, list):
            return []
        return [path for path in paths if isinstance(path, str)][:MAX_RECENT]

    def add(self, path: str) -> None:
        paths = [path, *(other for other in self.load() if other != path)][:MAX_RECENT]
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(paths, ensure_ascii=False), encoding="utf-8")
        except OSError as err:
            logger.warning("chemins récents non enregistrés (%s) : %s", self.path, err)


class Jobs:
    """Les analyses et les plans de la session. À créer et à fermer dans la boucle du serveur
    (``app.create_app`` : au démarrage et à l'arrêt)."""

    def __init__(self, *, recent: Recent, cache: Cache | None = None) -> None:
        self.recent = recent
        self.scans: dict[str, Scan] = {}
        self.plans: dict[str, Plan] = {}
        self._loop = asyncio.get_running_loop()
        self._worker = Worker(cache or Cache.default())
        self._updates = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="forceupdate-updates"
        )

    def start(self) -> None:
        self._worker.start()

    async def close(self) -> None:
        """Annule les analyses en cours, attend la fin d'une mise à jour en cours (ses outils
        ne sont pas interrompus), puis arrête les threads et efface les fichiers envoyés."""
        for scan in self.scans.values():
            self.cancel(scan)
        if any(plan.status is TaskStatus.RUNNING for plan in self.plans.values()):
            logger.warning("mise à jour en cours : attente de sa fin avant de s'arrêter")
        await asyncio.to_thread(self._updates.shutdown)
        await asyncio.to_thread(self._worker.stop)
        for scan in self.scans.values():
            _remove(scan.upload_dir)

    # -- analyses -----------------------------------------------------------------

    def start_scan(
        self,
        source: LocalSource,
        options: ScanOptions,
        *,
        kind: SourceKind,
        label: str,
        upload_dir: Path | None = None,
    ) -> Scan:
        """Lance l'analyse de ``source``."""
        scan = Scan(
            id=_new_id(),
            source=source,
            kind=kind,
            label=label,
            options=options,
            upload_dir=upload_dir,
        )
        self.scans[scan.id] = scan
        self._forget_old_scans()

        def on_event(event: Event) -> None:
            self._post(scan.progress.add, event)

        scan.future = self._worker.submit(self._worker.analyze(source, options, on_event))
        scan.future.add_done_callback(lambda future: self._post(self._scanned, scan, future))
        return scan

    def cancel(self, scan: Scan) -> bool:
        """Annule ``scan`` si elle tourne encore ; faux si elle était déjà finie."""
        if scan.status is not TaskStatus.RUNNING:
            return scan.status is TaskStatus.CANCELLED
        if scan.future is not None:
            scan.future.cancel()
        self._end_scan(scan, TaskStatus.CANCELLED)
        return True

    def _scanned(self, scan: Scan, future: concurrent.futures.Future[Report]) -> None:
        if scan.status is not TaskStatus.RUNNING:
            return  # annulée entre-temps
        if future.cancelled():
            self._end_scan(scan, TaskStatus.CANCELLED)
            return
        error = future.exception()
        if error is not None:
            logger.error("analyse de %s en échec", scan.label, exc_info=error)
            self._end_scan(scan, TaskStatus.FAILED, f"erreur inattendue : {error!r}")
            return
        report = future.result()
        if scan.kind is SourceKind.UPLOAD:
            report.source = scan.label  # pas le dossier temporaire
        scan.report = report
        self._end_scan(scan, TaskStatus.DONE)

    def _end_scan(self, scan: Scan, status: TaskStatus, error: str | None = None) -> None:
        scan.status = status
        scan.error = error
        scan.finished_at = _now()
        scan.progress.finish()

    def _forget_old_scans(self) -> None:
        finished = [s for s in self.scans.values() if s.status is not TaskStatus.RUNNING]
        excess = len(self.scans) - MAX_SCANS
        for scan in sorted(finished, key=lambda s: s.started_at)[: max(excess, 0)]:
            if any(p.scan is scan and p.status is TaskStatus.RUNNING for p in self.plans.values()):
                continue
            del self.scans[scan.id]
            for plan in [p for p in self.plans.values() if p.scan is scan]:
                del self.plans[plan.id]
            _remove(scan.upload_dir)

    # -- plans --------------------------------------------------------------------

    def add_plan(
        self,
        scan: Scan,
        selection: dict[str, str],
        prepared: Prepared,
        uncommitted: list[str] | None,
    ) -> Plan:
        plan = Plan(
            id=_new_id(),
            scan=scan,
            selection=selection,
            prepared=prepared,
            uncommitted=uncommitted,
        )
        self.plans[plan.id] = plan
        return plan

    def start_apply(self, plan: Plan) -> None:
        """Applique ``plan`` dans le thread des mises à jour (après celles qui attendent)."""
        plan.status = TaskStatus.RUNNING
        scan = plan.scan
        assert scan.report is not None

        def on_event(event: Event) -> None:
            self._post(plan.progress.add, event)

        future = self._updates.submit(
            local.apply, scan.source, scan.report, plan.prepared, on_event=on_event
        )
        future.add_done_callback(lambda done: self._post(self._applied, plan, done))

    def _applied(
        self, plan: Plan, future: concurrent.futures.Future[tuple[Regenerated, ...]]
    ) -> None:
        error = future.exception()
        if isinstance(error, writers.WriteError):
            plan.status, plan.error = TaskStatus.FAILED, str(error)
        elif error is not None:
            logger.error("mise à jour de %s en échec", plan.scan.label, exc_info=error)
            plan.status, plan.error = TaskStatus.FAILED, f"erreur inattendue : {error!r}"
        else:
            plan.status, plan.results = TaskStatus.DONE, future.result()
        plan.finished_at = _now()
        plan.progress.finish()

    # -- outils -------------------------------------------------------------------

    def _post(self, callback: Callable[..., object], *args: object) -> None:
        """Fait exécuter ``callback(*args)`` dans la boucle du serveur, depuis un autre
        thread."""
        with contextlib.suppress(RuntimeError):  # boucle du serveur déjà fermée
            self._loop.call_soon_threadsafe(callback, *args)


def _remove(directory: Path | None) -> None:
    if directory is not None:
        shutil.rmtree(directory, ignore_errors=True)
