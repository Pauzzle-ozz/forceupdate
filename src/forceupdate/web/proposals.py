"""Les PR des dépôts (écran 8 ; des MR sur GitLab) : le récapitulatif, préparé sans rien
pousser, puis l'envoi. Un récapitulatif peut mêler plusieurs comptes (GitHub, gitlab.com, une
instance GitLab) : chaque dépôt garde le sien.

- **Le récapitulatif** (``Proposals.create``) : pour chaque dépôt demandé, sa dernière analyse,
  la sélection (celle donnée, ou celle par défaut du rapport) préparée comme en local sur les
  fichiers téléchargés à l'analyse (``update.local.prepare`` : diffs, lockfiles, outil trouvé ou
  commande), et la PR déjà ouverte (``Forge.find_open_request``). Sautés, avec la raison :
  archivé, lecture seule, vide, pas analysé (ou analyse en cours, échouée), rien à mettre à
  jour. Un dépôt dont l'analyse n'a pas tout vérifié (un registre ou OSV muet, une arborescence
  tronquée) est prêt, mais pas coché par défaut. Rien n'est cloné ni poussé.
- **L'envoi** (``Proposals.send``), une fois validé : les dépôts cochés, un à la fois, dans la
  boucle des analyses, avec une forge par compte créée sur son client ; pour chacun
  ``update.forge.deliver`` (clone, mise à jour, push, PR) dans un dossier de travail effacé
  ensuite, ses outils de lockfile dans le thread des mises à jour (``Jobs.in_updates``). Un
  dépôt qui échoue n'arrête pas les autres, un compte dont le token est refusé non plus.
  L'auteur des commits est le compte du token (``Forge.whoami``). Un envoi ne s'annule pas (un
  outil interrompu laisserait un clone à moitié fait, et une PR peut déjà être ouverte).

L'état n'est modifié que dans la boucle du serveur (``Jobs.post``) ; le token ne quitte pas le
serveur. Les récapitulatifs restent en mémoire le temps de la session (``MAX_PROPOSALS``).
"""

import asyncio
import concurrent.futures
import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from forceupdate.forges import git
from forceupdate.forges.accounts import Account
from forceupdate.forges.base import (
    ChangeRequest,
    Forge,
    ForgeError,
    Identity,
    Repository,
    TokenRefused,
)
from forceupdate.models import Event, FindingKind, Report
from forceupdate.net import NetworkError
from forceupdate.report import summarize
from forceupdate.sources.base import SourceError
from forceupdate.sources.forge import ClonedSource, ForgeSource
from forceupdate.sources.local import LocalSource
from forceupdate.update import forge as forge_update
from forceupdate.update import local, lockfiles, planner
from forceupdate.update.forge import BRANCH, Delivered, Outcome, Step
from forceupdate.update.local import Prepared
from forceupdate.web import schemas
from forceupdate.web.connections import failure
from forceupdate.web.jobs import Jobs, Scan
from forceupdate.web.repositories import (
    EXCLUDED,
    Repositories,
    RepositoryError,
    refused_callback,
)
from forceupdate.web.routes import sentence
from forceupdate.web.schemas import (
    ProposalStatus,
    ProposedSelection,
    ProposedState,
    RepositoryKey,
    TaskStatus,
)

logger = logging.getLogger(__name__)

MAX_PROPOSALS = 10
"""Récapitulatifs gardés en mémoire ; au-delà, les plus anciens finis sont oubliés."""

_OUTCOMES = {
    Outcome.OPENED: ProposedState.OPENED,
    Outcome.UPDATED: ProposedState.UPDATED,
    Outcome.NOTHING: ProposedState.NOTHING,
    Outcome.FAILED: ProposedState.FAILED,
}


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(eq=False, kw_only=True)
class Proposed:
    """Un dépôt d'un récapitulatif."""

    account: Account
    repo: Repository
    scan: Scan | None
    state: ProposedState = ProposedState.SKIPPED
    reason: str | None = None
    inconclusive: bool = False
    selection: dict[str, str] = field(default_factory=dict)
    prepared: Prepared | None = None
    request: ChangeRequest | None = None
    step: Step | None = None
    progress: Event | None = None
    delivered: Delivered | None = None
    error: str | None = None

    @property
    def checked(self) -> bool:
        return self.state is ProposedState.READY and not self.inconclusive

    def document(self) -> schemas.ProposedRepository:
        delivered = self.delivered
        prepared = (delivered.prepared if delivered is not None else None) or self.prepared
        changes = prepared.changes if prepared is not None else None
        commit = None
        if self.scan is not None:
            reference = self.scan.repository_ref()
            commit = reference.commit if reference is not None else None
        return schemas.ProposedRepository(
            forge=self.repo.forge,
            host=self.repo.host,
            full_name=self.repo.full_name,
            url=self.repo.url,
            default_branch=self.repo.default_branch,
            branch=BRANCH,
            scan=self.scan.id if self.scan is not None else None,
            commit=commit,
            state=self.state,
            reason=self.reason,
            inconclusive=self.inconclusive,
            checked=self.checked,
            request=self.request,
            selection=self.selection,
            applied=tuple(schemas.proposed_update(c) for c in changes.applied) if changes else (),
            skipped=tuple(schemas.proposed_skip(s) for s in changes.skipped) if changes else (),
            files=(
                tuple(schemas.FileDiff(path=c.path, diff=c.diff) for c in changes.files)
                if changes
                else ()
            ),
            lockfiles=tuple(schemas.lock_job(job) for job in prepared.jobs) if prepared else (),
            step=self.step,
            progress=self.progress,
            pushed=delivered.pushed if delivered is not None else False,
            base=delivered.base if delivered is not None else None,
            results=(
                tuple(schemas.lock_result(result) for result in delivered.results)
                if delivered is not None
                else ()
            ),
            committed=delivered.committed if delivered is not None else (),
            error=self.error,
        )


@dataclass(eq=False, kw_only=True)
class Proposal:
    """Un récapitulatif de PR et de MR, puis son envoi."""

    id: str
    items: list[Proposed]
    created_at: datetime = field(default_factory=_now)
    status: ProposalStatus = ProposalStatus.PLANNED
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None

    def item(self, key: RepositoryKey) -> Proposed | None:
        wanted = (key.forge, key.host.lower(), key.full_name.lower())
        return next((item for item in self.items if _key(item.repo) == wanted), None)

    def document(self) -> schemas.Proposal:
        ready = [item for item in self.items if item.state is ProposedState.READY]
        return schemas.Proposal(
            id=self.id,
            status=self.status,
            created_at=self.created_at,
            started_at=self.started_at,
            finished_at=self.finished_at,
            repositories=tuple(item.document() for item in self.items),
            ready=len(ready),
            existing=sum(1 for item in ready if item.request is not None),
            error=self.error,
        )


class Proposals:
    """Les récapitulatifs de PR de la session. À créer dans la boucle du serveur."""

    def __init__(self, *, jobs: Jobs, repositories: Repositories) -> None:
        self.jobs = jobs
        self.repositories = repositories
        self.proposals: dict[str, Proposal] = {}

    # -- le récapitulatif ------------------------------------------------------------

    async def create(self, wanted: list[ProposedSelection]) -> Proposal:
        """Le récapitulatif des PR (MR sur GitLab) de ``wanted``, des dépôts des comptes
        connectés : rien n'est cloné ni poussé. Lève ``RepositoryError``."""
        if not wanted:
            raise RepositoryError(400, "Aucun dépôt pour lequel préparer une PR.")
        chosen = await self.repositories.chosen(list(wanted))
        selections = {
            (entry.forge, entry.host.lower(), entry.full_name.lower()): entry.selection
            for entry in reversed(wanted)  # le premier demandé l'emporte
        }
        items = [
            await self._prepare(account, repo, selections.get(key))
            for key, (account, repo) in chosen.items()
        ]
        ready = [item for item in items if item.state is ProposedState.READY]
        by_account: dict[tuple[object, str], list[Proposed]] = {}
        for item in ready:
            by_account.setdefault((item.account.forge, item.account.host), []).append(item)
        for group in by_account.values():
            await self._find_requests(group)
        proposal = Proposal(id=secrets.token_hex(6), items=items)
        self.proposals[proposal.id] = proposal
        self._forget_old()
        return proposal

    async def _find_requests(self, items: list[Proposed]) -> None:
        """Les PR déjà ouvertes des dépôts ``items`` d'un même compte, en parallèle."""
        account = items[0].account
        connections = self.repositories.connections
        forge = await self.repositories.forge(account, connections.http)
        if forge is None:
            raise RepositoryError(409, "Le token n'est plus dans le trousseau : se reconnecter.")
        try:
            found = await asyncio.gather(*(self._existing(forge, item.repo) for item in items))
        except TokenRefused as err:
            await asyncio.to_thread(connections.accounts.refused, account, str(err))
            raise RepositoryError(400, str(err)) from None
        for item, (checked, request) in zip(items, found, strict=True):
            item.request = request
            if checked:
                self.repositories.remember(item.repo, request)

    async def _prepare(
        self, account: Account, repo: Repository, selection: dict[str, str] | None
    ) -> Proposed:
        """Un dépôt du récapitulatif : sautée avec la raison, ou sa sélection préparée."""
        scan = self.repositories.jobs.latest(repo)
        item = Proposed(account=account, repo=repo, scan=scan)
        item.reason = _skipped(repo, scan)
        if item.reason is None and self.repositories.hidden_reason(repo) == EXCLUDED:
            item.reason = f"{EXCLUDED} : pas de PR"
        if item.reason is not None:
            return item
        assert scan is not None and scan.report is not None
        report = scan.report
        source = scan.source
        if not isinstance(source, ForgeSource | ClonedSource):
            item.reason = "pas de fichiers d'analyse : relancer l'analyse"
            return item
        item.selection = dict(planner.select(report) if selection is None else selection)
        try:
            prepared = await asyncio.to_thread(
                _prepare, source, report, item.selection, self._tools()
            )
        except ValueError as err:
            raise RepositoryError(400, f"{repo.full_name} : {sentence(str(err))}") from None
        except SourceError:
            item.reason = "les fichiers de l'analyse ne sont plus là : relancer l'analyse"
            return item
        item.prepared = prepared
        if prepared.empty:
            item.reason = (
                "aucune mise à jour cochée" if not item.selection else "rien à mettre à jour"
            )
            return item
        item.state = ProposedState.READY
        # Des paquets restés sans réponse (ou une analyse partielle) : la PR peut en manquer.
        partial = isinstance(source, ForgeSource) and source.truncated
        unanswered = summarize(report).findings.get(FindingKind.INCONCLUSIVE, 0)
        item.inconclusive = partial or unanswered > 0
        return item

    async def _existing(self, forge: Forge, repo: Repository) -> tuple[bool, ChangeRequest | None]:
        """La PR de forceupdate déjà ouverte sur ``repo`` ; ``(False, None)`` si la forge ne
        répond pas (l'envoi la retrouvera)."""
        try:
            return True, await forge.find_open_request(repo, BRANCH)
        except TokenRefused:
            raise
        except (ForgeError, NetworkError) as err:
            logger.info("%s : PR ouverte non cherchée (%s)", repo.full_name, err)
            return False, None

    # -- l'envoi -----------------------------------------------------------------------

    async def send(self, proposal: Proposal, keys: list[RepositoryKey]) -> None:
        """Envoie les dépôts ``keys`` du récapitulatif, en tâche de fond. Lève
        ``RepositoryError``."""
        if proposal.status is not ProposalStatus.PLANNED:
            raise RepositoryError(409, "Ce récapitulatif est déjà envoyé, ou en cours d'envoi.")
        chosen: list[Proposed] = []
        for key in keys:
            item = proposal.item(key)
            if item is None or item.state is not ProposedState.READY:
                raise RepositoryError(
                    400, f"{key.full_name} : pas prêt à envoyer dans ce récapitulatif."
                )
            if item not in chosen:
                chosen.append(item)
        if not chosen:
            raise RepositoryError(400, "Aucun dépôt à envoyer.")
        if not git.available():
            raise RepositoryError(409, "git n'est pas installé : il faut git pour cloner.")
        groups: list[tuple[Forge, Account, list[Proposed]]] = []
        by_account: dict[tuple[object, str], list[Proposed]] = {}
        for item in chosen:
            by_account.setdefault((item.account.forge, item.account.host), []).append(item)
        for items in by_account.values():
            first = items[0].account
            account = await self.repositories.connected(first.forge, first.host)
            groups.append((await self.repositories.worker_forge_of(account), account, items))
        for item in proposal.items:
            if item in chosen:
                item.state = ProposedState.WAITING
            elif item.state is ProposedState.READY:
                item.state, item.reason = ProposedState.SKIPPED, "pas coché à l'envoi"
        proposal.status, proposal.started_at = ProposalStatus.RUNNING, _now()
        future = self.jobs.worker.submit(self._send(groups))
        future.add_done_callback(lambda done: self.jobs.post(self._sent, proposal, done))

    async def _send(self, groups: list[tuple[Forge, Account, list[Proposed]]]) -> None:
        """Dans la boucle des analyses : compte par compte, chaque dépôt à son tour."""
        for forge, account, items in groups:
            refused = refused_callback(self.repositories.connections, account)
            try:
                author = await forge.whoami()
            except (ForgeError, NetworkError) as err:
                message = str(err) if isinstance(err, ForgeError) else failure(err, account.forge)
                if isinstance(err, TokenRefused):
                    await asyncio.to_thread(refused, message)
                self.jobs.post(_abandon, items, sentence(message))
                continue
            for item in items:
                await self._send_one(item, forge, author, refused)

    async def _send_one(
        self, item: Proposed, forge: Forge, author: Identity, refused: Callable[[str], None]
    ) -> None:
        post = self.jobs.post
        post(setattr, item, "state", ProposedState.SENDING)
        scan = item.scan
        assert scan is not None and scan.report is not None
        workspace = await asyncio.to_thread(git.Workspace)
        try:
            delivered = await forge_update.deliver(
                forge,
                item.repo,
                scan.report,
                item.selection,
                author=author,
                workdir=workspace.path,
                run=self.jobs.in_updates,
                on_step=lambda step: post(setattr, item, "step", step),
                on_event=lambda event: post(setattr, item, "progress", event),
                tools=self._tools(),
            )
        except Exception as err:  # jamais un dépôt n'arrête les autres
            logger.error("envoi de %s en échec", item.repo.full_name, exc_info=err)
            delivered = Delivered(outcome=Outcome.FAILED, error=f"Erreur inattendue : {err!r}.")
        finally:
            await asyncio.to_thread(workspace.cleanup)
        if delivered.refused:
            await asyncio.to_thread(refused, delivered.error or "")
        post(self._delivered, item, delivered)

    def _delivered(self, item: Proposed, delivered: Delivered) -> None:
        item.delivered = delivered
        item.state = _OUTCOMES[delivered.outcome]
        item.error = delivered.error
        item.step = None
        if delivered.request is not None:
            item.request = delivered.request
            self.repositories.remember(item.repo, delivered.request)

    def _sent(self, proposal: Proposal, future: concurrent.futures.Future[None]) -> None:
        error = future.exception() if not future.cancelled() else None
        if future.cancelled():
            proposal.error = "Envoi interrompu : le serveur s'est arrêté."
        elif error is not None:
            logger.error("envoi des PR en échec", exc_info=error)
            proposal.error = f"Erreur inattendue : {error!r}."
        if proposal.error is not None:
            for item in proposal.items:
                if item.state in (ProposedState.WAITING, ProposedState.SENDING):
                    item.state, item.error = ProposedState.FAILED, proposal.error
        proposal.status, proposal.finished_at = ProposalStatus.DONE, _now()

    def _tools(self) -> lockfiles.Tools:
        store = self.repositories.preferences
        return store.tools if store is not None else lockfiles.DEFAULT_TOOLS

    def _forget_old(self) -> None:
        finished = sorted(
            (p for p in self.proposals.values() if p.status is not ProposalStatus.RUNNING),
            key=lambda p: p.created_at,
        )
        for proposal in finished[: max(len(self.proposals) - MAX_PROPOSALS, 0)]:
            del self.proposals[proposal.id]


def _prepare(
    source: ForgeSource | ClonedSource,
    report: Report,
    selection: dict[str, str],
    tools: lockfiles.Tools,
) -> Prepared:
    """La sélection préparée sur les fichiers de l'analyse (dans un thread)."""
    return local.prepare(LocalSource(source.root), report, selection, tools=tools)


def _skipped(repo: Repository, scan: Scan | None) -> str | None:
    """Pourquoi un dépôt n'aura pas de PR, avant même de préparer sa sélection."""
    if repo.archived:
        return "archivé : lecture seule"
    if not repo.can_push:
        return "lecture seule : pas de droit de push"
    if repo.empty or repo.default_branch is None:
        return "vide"
    if scan is None or scan.status is TaskStatus.CANCELLED:
        return "pas encore analysé"
    if scan.status is TaskStatus.RUNNING:
        return "analyse en cours"
    if scan.status is TaskStatus.FAILED or scan.report is None:
        return f"analyse échouée{f' : {scan.error}' if scan.error else ''}"
    return None


def _key(repo: Repository) -> tuple[object, str, str]:
    return repo.forge, repo.host, repo.full_name.lower()


def _abandon(items: list[Proposed], message: str) -> None:
    """Les dépôts d'un compte dont l'envoi n'a pas pu commencer (token refusé…)."""
    for item in items:
        item.state, item.error = ProposedState.FAILED, message
