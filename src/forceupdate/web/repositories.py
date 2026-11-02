"""Les dépôts des comptes connectés (écran 7) : leur liste, leurs analyses groupées, et la
synthèse de l'ensemble, calculée ici et pas dans le navigateur.

- **La liste** est demandée à la forge au premier affichage, puis gardée le temps de la session
  (``reload`` la redemande) : les dépôts et leurs drapeaux, les organisations qui restreignent
  l'accès, les requêtes restantes. Elle passe par le client des comptes (``Connections.http``),
  dans la boucle du serveur. Si la forge ne répond pas, la liste d'avant reste, avec l'erreur.
- **Une analyse groupée** (``Batch``) lance une analyse par dépôt dans la boucle des analyses
  (``Jobs.start_repository_scan``), ``CONCURRENCY`` dépôts à la fois ; ses dépôts peuvent
  venir de plusieurs comptes (GitHub, gitlab.com, une instance GitLab) : une forge par compte,
  créée sur le client de cette boucle (ses requêtes en partent, et elle compte celles du lot).
- **Chaque dépôt** a l'état de sa dernière analyse (groupée ou non), et **la synthèse** les
  additionne (``report.synthesis``). Sa PR de forceupdate ouverte est la plus récente qu'on
  connaisse : trouvée par sa dernière analyse, par un récapitulatif ou par un envoi
  (``remember``, E18).

Un compte se désigne par sa forge et son hôte. Le token ne quitte jamais le serveur : il est lu
dans le trousseau (``Accounts.token``, dans un thread) au moment de parler à la forge, et
renouvelé s'il expire (``Connections.renew``, GitLab). Un token refusé est noté sur le compte
(``Accounts.refused``) : l'écran Comptes le montre.
"""

import asyncio
import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from forceupdate import forges
from forceupdate.forges.accounts import Account, AccountsError
from forceupdate.forges.base import (
    ChangeRequest,
    Forge,
    ForgeError,
    ForgeKind,
    NotFound,
    RateLimit,
    RateLimited,
    Repository,
    Restriction,
    TokenRefused,
)
from forceupdate.models import FindingKind, ScanOptions, Severity
from forceupdate.net import HttpClient, NetworkError
from forceupdate.report import Summary, summarize
from forceupdate.report.synthesis import Verdict, combine, verdict
from forceupdate.sources.forge import ForgeSource
from forceupdate.web import schemas
from forceupdate.web.connections import Connections, failure
from forceupdate.web.jobs import Jobs, RepositoryTarget, Scan, same
from forceupdate.web.preferences import UserPreferences
from forceupdate.web.schemas import BatchStatus, RepositoryKey, RepositoryState, TaskStatus

logger = logging.getLogger(__name__)

CONCURRENCY = 4
"""Dépôts lus et analysés en même temps dans une analyse groupée. Les requêtes à un même hôte
sont en plus limitées par le client (8 à la fois)."""
MAX_BATCHES = 10
"""Analyses groupées gardées en mémoire."""
EXCLUDED = "exclu dans les réglages"

_VERDICT_STATE = {
    Verdict.TO_UPDATE: RepositoryState.TO_UPDATE,
    Verdict.UP_TO_DATE: RepositoryState.UP_TO_DATE,
    Verdict.INCONCLUSIVE: RepositoryState.INCONCLUSIVE,
    Verdict.NO_DEPENDENCIES: RepositoryState.NO_DEPENDENCIES,
}


def _now() -> datetime:
    return datetime.now(UTC)


class RepositoryError(Exception):
    """Une demande sur les dépôts qui ne peut pas aboutir ; ``status`` est le code HTTP à
    rendre, le message est à montrer."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(kw_only=True)
class Listing:
    """La liste des dépôts d'un compte, telle que la forge l'a donnée la dernière fois."""

    repos: list[Repository] = field(default_factory=list)
    restrictions: list[Restriction] = field(default_factory=list)
    rate_limit: RateLimit | None = None
    listed_at: datetime | None = None
    error: str | None = None
    refused: str | None = None
    """La forge a refusé le token au dernier chargement."""
    connected_at: datetime | None = None
    """La connexion du compte pour laquelle la liste a été chargée : un compte reconnecté
    recharge sa liste."""


@dataclass(eq=False, kw_only=True)
class Batch:
    """Une analyse groupée."""

    id: str
    forges: dict[tuple[ForgeKind, str], Forge]
    """Une par compte (forge, hôte), créée sur le client de la boucle des analyses ; chacune
    compte les requêtes du lot."""
    scans: list[Scan]
    skipped: list[str]
    started_at: datetime = field(default_factory=_now)
    cancelled: bool = False

    @property
    def running(self) -> bool:
        return any(scan.status is TaskStatus.RUNNING for scan in self.scans)

    def document(self) -> schemas.RepositoryBatch:
        finished = [scan for scan in self.scans if scan.status is not TaskStatus.RUNNING]
        if self.running:
            status = BatchStatus.RUNNING
        else:
            status = BatchStatus.CANCELLED if self.cancelled else BatchStatus.DONE
        ends = [scan.finished_at for scan in finished if scan.finished_at is not None]
        return schemas.RepositoryBatch(
            id=self.id,
            status=status,
            started_at=self.started_at,
            finished_at=None if self.running else max(ends, default=self.started_at),
            concurrency=CONCURRENCY,
            scans=tuple(scan.id for scan in self.scans),
            total=len(self.scans),
            finished=len(finished),
            failed=sum(1 for scan in finished if scan.status is TaskStatus.FAILED),
            skipped=tuple(self.skipped),
            requests=sum(forge.requests for forge in self.forges.values()),
        )


class Repositories:
    """Les dépôts des comptes connectés, et leurs analyses groupées. À créer dans la boucle du
    serveur."""

    def __init__(
        self, *, jobs: Jobs, connections: Connections, preferences: UserPreferences | None = None
    ) -> None:
        self.jobs = jobs
        self.connections = connections
        self.preferences = preferences
        """Les réglages de la personne : ses dépôts exclus (E29)."""
        self.batches: dict[str, Batch] = {}
        self._listings: dict[tuple[ForgeKind, str], Listing] = {}
        self._loading: dict[tuple[ForgeKind, str], asyncio.Lock] = {}
        self._summaries: dict[str, Summary] = {}
        self._requests: list[tuple[Repository, ChangeRequest | None, datetime]] = []
        """Les PR ouvertes apprises par un récapitulatif ou un envoi (``remember``)."""

    # -- la liste ------------------------------------------------------------------

    async def document(self, *, reload: bool = False) -> schemas.RepositoryList:
        """Les dépôts des comptes connectés, l'état de chacun, et la synthèse. La liste n'est
        demandée aux forges que la première fois, ou avec ``reload``."""
        accounts = await self._accounts()
        listed: list[tuple[Account, Listing]] = []
        for account in accounts:
            key = (account.forge, account.host)
            listing = self._listings.get(key)
            if listing is None or reload or listing.connected_at != account.connected_at:
                listing = await self._list(account, reload=True)
            listed.append((account, listing))
        rows = [self._row(repo) for _, listing in listed for repo in listing.repos]
        batch = max(self.batches.values(), key=lambda b: b.started_at, default=None)
        return schemas.RepositoryList(
            accounts=tuple(self._account(account, listing, batch) for account, listing in listed),
            repositories=tuple(rows),
            synthesis=self._synthesis(rows),
            batch=batch.document() if batch is not None else None,
        )

    def remember(self, repo: Repository, request: ChangeRequest | None) -> None:
        """Note la PR de forceupdate ouverte sur ``repo`` (``None`` : aucune), apprise à
        l'instant."""
        self._requests = [entry for entry in self._requests if not same(entry[0], repo)]
        self._requests.append((repo, request, _now()))

    def request(self, repo: Repository, scan: Scan | None) -> ChangeRequest | None:
        """La PR de forceupdate ouverte sur ``repo``, d'après ce qu'on en sait de plus récent :
        sa dernière analyse (``scan``), un récapitulatif, un envoi."""
        known: list[tuple[datetime, ChangeRequest | None]] = [
            (when, request) for found, request, when in self._requests if same(found, repo)
        ]
        if scan is not None and scan.request_checked:
            known.append((scan.finished_at or scan.started_at, scan.request))
        return max(known, key=lambda entry: entry[0])[1] if known else None

    def listed(self, forge: ForgeKind, host: str, full_name: str) -> Repository | None:
        """Le dépôt ``full_name`` de la dernière liste du compte de ``forge`` sur ``host``."""
        listing = self._listings.get((forge, host.lower()))
        wanted = full_name.lower()
        if listing is not None:
            for repo in listing.repos:
                if repo.full_name.lower() == wanted:
                    return repo
        return None

    async def _accounts(self) -> list[Account]:
        store = self.connections.accounts
        if await asyncio.to_thread(store.unavailable) is not None:
            return []
        try:
            connected = await asyncio.to_thread(store.connected)
        except AccountsError:
            return []
        return [account for account in connected if forges.info(account.forge).available]

    async def _list(self, account: Account, *, reload: bool) -> Listing:
        key = (account.forge, account.host)
        lock = self._loading.setdefault(key, asyncio.Lock())
        async with lock:
            current = self._listings.get(key)
            if current is not None and not reload:
                return current  # chargée par une autre requête pendant l'attente
            listing = Listing(
                repos=current.repos if current else [],
                restrictions=current.restrictions if current else [],
                rate_limit=current.rate_limit if current else None,
                listed_at=current.listed_at if current else None,
                connected_at=account.connected_at,
            )
            forge = await self.forge(account, self.connections.http)
            if forge is None:
                listing.error = "Le token n'est plus dans le trousseau : se reconnecter."
            else:
                try:
                    repos = await forge.list_repos()
                    restrictions = await forge.restrictions()
                except TokenRefused as err:
                    await asyncio.to_thread(self.connections.accounts.refused, account, str(err))
                    listing.error = listing.refused = str(err)
                except ForgeError as err:
                    listing.error = str(err)
                except NetworkError as err:
                    listing.error = failure(err, account.forge)
                else:
                    listing.repos = sorted(repos, key=lambda repo: repo.full_name.lower())
                    listing.restrictions = restrictions
                    listing.listed_at = _now()
                listing.rate_limit = forge.rate_limit or listing.rate_limit
            self._listings[key] = listing
            return listing

    async def token(self, account: Account) -> str | None:
        try:
            return await asyncio.to_thread(
                self.connections.accounts.token, account.forge, account.host
            )
        except AccountsError:
            return None

    async def forge(self, account: Account, http: HttpClient) -> Forge | None:
        """La forge du compte, sur ``http`` (le client de la boucle où elle servira), avec son
        token, renouvelé s'il expire ; ``None`` si le token n'est plus dans le trousseau."""
        token = await self.token(account)
        if token is None:
            return None
        return forges.client(
            account.forge,
            http,
            token,
            host=account.host,
            renew=self.connections.renew(account),
        )

    async def worker_forge_of(self, account: Account) -> Forge:
        """La forge du compte, pour la boucle des analyses ; lève ``RepositoryError``."""
        forge = await self.forge(account, self._worker_http())
        if forge is None:
            raise RepositoryError(409, "Le token n'est plus dans le trousseau : se reconnecter.")
        return forge

    def _account(
        self, account: Account, listing: Listing, batch: Batch | None
    ) -> schemas.RepositoryAccount:
        rate = listing.rate_limit
        used = batch.forges.get((account.forge, account.host)) if batch is not None else None
        if (
            batch is not None
            and used is not None
            and used.rate_limit is not None
            and (listing.listed_at is None or batch.started_at > listing.listed_at)
        ):
            rate = used.rate_limit
        return schemas.RepositoryAccount(
            forge=account.forge,
            host=account.host,
            login=account.login,
            access=account.access,
            problem=account.problem or listing.refused,
            listed_at=listing.listed_at,
            error=listing.error,
            repositories=len(listing.repos),
            restrictions=tuple(listing.restrictions),
            rate_limit=rate,
        )

    # -- un dépôt ------------------------------------------------------------------

    def _row(self, repo: Repository) -> schemas.RepositoryRow:
        scan = self.jobs.latest(repo)
        hidden = self.hidden_reason(repo)
        state, reason, counts, languages = RepositoryState.NOT_SCANNED, None, None, None
        if scan is None or scan.status is TaskStatus.CANCELLED:
            if hidden is not None:
                state, reason = RepositoryState.SKIPPED, hidden
            elif scan is not None:
                reason = "analyse annulée"
        elif scan.status is TaskStatus.RUNNING:
            state = RepositoryState.RUNNING
        elif scan.status is TaskStatus.FAILED or scan.report is None:
            state, reason = RepositoryState.INCONCLUSIVE, scan.error
        else:
            summary = self._summary(scan)
            truncated = isinstance(scan.source, ForgeSource) and scan.source.truncated
            state = _VERDICT_STATE[verdict(summary, partial=truncated)]
            if state is RepositoryState.INCONCLUSIVE:
                reason = _inconclusive_reason(summary, truncated)
            counts = schemas.RepositoryCounts(
                vulnerabilities=sum(summary.vulnerabilities.values()),
                critical=summary.vulnerabilities.get(Severity.CRITICAL, 0),
                worst=next((s for s in Severity if summary.vulnerabilities.get(s, 0)), None),
                to_update=summary.to_update,
                inconclusive=summary.findings.get(FindingKind.INCONCLUSIVE, 0),
                updates=sum(
                    1
                    for project in scan.report.projects
                    for update in project.updates
                    if update.selected is not None
                ),
            )
            languages = tuple(language.name for language in scan.report.languages)
        if not languages:  # pas encore analysé, ou aucun fichier de code reconnu
            languages = (repo.language,) if repo.language else ()
        return schemas.RepositoryRow(
            forge=repo.forge,
            host=repo.host,
            full_name=repo.full_name,
            owner=repo.owner,
            name=repo.name,
            url=repo.url,
            default_branch=repo.default_branch,
            private=repo.private,
            archived=repo.archived,
            fork=repo.fork,
            empty=repo.empty,
            can_push=repo.can_push,
            pushed_at=repo.pushed_at,
            hidden=hidden is not None,
            languages=languages,
            state=state,
            reason=reason,
            counts=counts,
            scan=scan.summary() if scan is not None else None,
            request=self.request(repo, scan),
        )

    def hidden_reason(self, repo: Repository) -> str | None:
        """Pourquoi un dépôt est masqué par défaut, et pas analysé avec les autres : vide,
        archivé, fork, ou exclu dans les réglages de la personne (E29)."""
        if self.preferences is not None and self.preferences.current.excludes(
            repo.host, repo.full_name
        ):
            return EXCLUDED
        return _hidden_reason(repo)

    def _summary(self, scan: Scan) -> Summary:
        """Le résumé du rapport d'une analyse finie, calculé une fois (il ne change plus)."""
        found = self._summaries.get(scan.id)
        if found is None:
            assert scan.report is not None
            found = self._summaries[scan.id] = summarize(scan.report)
        return found

    def _synthesis(self, rows: list[schemas.RepositoryRow]) -> schemas.RepositorySynthesis:
        states = [row.state for row in rows]
        finished = [
            self._summary(scan)
            for row in rows
            if row.scan is not None
            and row.scan.status is TaskStatus.DONE
            and (scan := self.jobs.scans.get(row.scan.id)) is not None
            and scan.report is not None
        ]
        combined = combine(finished)
        return schemas.RepositorySynthesis(
            repositories=len(rows),
            hidden=sum(1 for row in rows if row.hidden),
            archived=sum(1 for row in rows if row.archived),
            forks=sum(1 for row in rows if row.fork),
            empty=sum(1 for row in rows if row.empty),
            analyzed=len(finished),
            running=states.count(RepositoryState.RUNNING),
            not_scanned=states.count(RepositoryState.NOT_SCANNED),
            skipped=states.count(RepositoryState.SKIPPED),
            to_update=states.count(RepositoryState.TO_UPDATE),
            up_to_date=states.count(RepositoryState.UP_TO_DATE),
            inconclusive=states.count(RepositoryState.INCONCLUSIVE),
            no_dependencies=states.count(RepositoryState.NO_DEPENDENCIES),
            vulnerabilities=sum(combined.vulnerabilities.values()),
            critical=combined.vulnerabilities[Severity.CRITICAL],
            vulnerable_repositories=combined.vulnerable_reports,
            findings=combined.findings,
            severities=combined.severities,
            open_requests=sum(1 for row in rows if row.request is not None),
        )

    # -- les analyses --------------------------------------------------------------

    async def start_batch(self, keys: list[RepositoryKey], options: ScanOptions) -> Batch:
        """Analyse ensemble les dépôts ``keys`` des comptes connectés (de plusieurs comptes au
        besoin) ; les vides sont sautés. Lève ``RepositoryError``."""
        if not keys:
            raise RepositoryError(400, "Aucun dépôt à analyser.")
        repos = await self.chosen(keys)
        slots = asyncio.Semaphore(CONCURRENCY)
        batch = Batch(id=secrets.token_hex(6), forges={}, scans=[], skipped=[])
        refused: dict[tuple[ForgeKind, str], Callable[[str], None]] = {}
        for account, _ in repos.values():
            key = (account.forge, account.host)
            if key not in batch.forges:
                batch.forges[key] = await self.worker_forge_of(account)
                refused[key] = refused_callback(self.connections, account)
        for account, repo in repos.values():
            if repo.empty:
                batch.skipped.append(repo.full_name)
                continue
            key = (account.forge, account.host)
            target = RepositoryTarget(
                forge=batch.forges[key], repo=repo, slots=slots, refused=refused[key]
            )
            batch.scans.append(self.jobs.start_repository_scan(target, options, batch=batch.id))
        self.batches[batch.id] = batch
        self._forget_old_batches()
        return batch

    def cancel_batch(self, batch: Batch) -> None:
        """Annule les analyses du lot pas encore finies ; celles qui le sont restent."""
        if batch.running:
            batch.cancelled = True
        for scan in batch.scans:
            self.jobs.cancel(scan)

    async def chosen(
        self, keys: list[RepositoryKey]
    ) -> dict[tuple[ForgeKind, str, str], tuple[Account, Repository]]:
        """Les dépôts ``keys`` des listes des comptes connectés, chacun avec son compte, dans
        l'ordre, sans doublon. Lève ``RepositoryError`` (compte non connecté, dépôt pas dans
        la liste)."""
        accounts: dict[tuple[ForgeKind, str], Account] = {}
        found: dict[tuple[ForgeKind, str, str], tuple[Account, Repository]] = {}
        unknown: list[str] = []
        for key in keys:
            host = key.host.lower()
            if (key.forge, host) not in accounts:
                accounts[(key.forge, host)] = await self.connected(key.forge, host)
            account = accounts[(key.forge, host)]
            repo = self.listed(key.forge, host, key.full_name)
            if repo is None:
                unknown.append(key.full_name)
            else:
                found.setdefault((repo.forge, repo.host, repo.full_name.lower()), (account, repo))
        if unknown:
            raise RepositoryError(
                400,
                f"{', '.join(unknown)} : pas dans la liste des dépôts du compte (la recharger).",
            )
        return found

    async def start_scan(self, text: str, options: ScanOptions) -> Scan:
        """Analyse un dépôt donné par son nom ou son adresse, même d'un autre compte s'il est
        public : avec le token du compte connecté à sa forge (et à son hôte) s'il y en a un,
        sans sinon. Lève ``RepositoryError``."""
        connected = await self._accounts()
        instances = {
            account.host: account.forge
            for account in connected
            if account.host != forges.HOSTS[account.forge]
        }
        try:
            forge_info, host, full_name = forges.parse_repository(text, instances=instances)
        except ValueError as err:
            raise RepositoryError(400, str(err)) from None
        if not forge_info.available:
            raise RepositoryError(
                409, f"{forge_info.name} : l'analyse de ses dépôts n'est pas encore disponible."
            )
        account = next((a for a in connected if (a.forge, a.host) == (forge_info.kind, host)), None)
        name = forges.label(forge_info.kind, host)
        if account is not None:
            lookup = await self.forge(account, self.connections.http)
        else:
            lookup = forges.client(forge_info.kind, self.connections.http, None, host=host)
        try:
            if lookup is None:
                raise TokenRefused("Le token n'est plus dans le trousseau : se reconnecter.")
            repo = self.listed(forge_info.kind, host, full_name) or await lookup.repository(
                full_name
            )
        except TokenRefused as err:
            if account is not None:
                await asyncio.to_thread(self.connections.accounts.refused, account, str(err))
            raise RepositoryError(400, str(err)) from None
        except NotFound:
            who = "le compte connecté" if account is not None else "sans compte connecté, on"
            message = (
                f"Dépôt introuvable sur {name} : {full_name} n'existe pas, ou il est privé et "
                f"{who} n'y a pas accès."
            )
            raise RepositoryError(404, message) from None
        except RateLimited as err:
            raise RepositoryError(409, str(err)) from None
        except ForgeError as err:
            raise RepositoryError(400, str(err)) from None
        except NetworkError as err:
            raise RepositoryError(502, failure(err, forge_info.kind)) from None
        if repo.empty:
            raise RepositoryError(409, f"{repo.full_name} est vide : rien à analyser.")
        if account is not None:
            forge = await self.worker_forge_of(account)
        else:
            forge = forges.client(forge_info.kind, self._worker_http(), None, host=host)
        target = RepositoryTarget(
            forge=forge,
            repo=repo,
            slots=asyncio.Semaphore(1),
            refused=refused_callback(self.connections, account) if account is not None else None,
        )
        return self.jobs.start_repository_scan(target, options)

    def _worker_http(self) -> HttpClient:
        """Le client de la boucle des analyses, d'où partiront les requêtes de ses forges."""
        http = self.jobs.worker.http
        assert http is not None, "Jobs.start d'abord"
        return http

    async def connected(self, kind: ForgeKind, host: str | None = None) -> Account:
        """Le compte connecté à ``kind`` sur ``host`` (par défaut, son service en ligne) ;
        lève ``RepositoryError``."""
        host = (host or forges.HOSTS[kind]).lower()
        name = forges.label(kind, host)
        if not forges.info(kind).available:
            raise RepositoryError(409, f"{name} : la connexion n'est pas encore disponible.")
        account = next(
            (a for a in await self._accounts() if (a.forge, a.host) == (kind, host)), None
        )
        if account is None:
            raise RepositoryError(404, f"Aucun compte {name} connecté.")
        return account

    def _forget_old_batches(self) -> None:
        finished = sorted(
            (batch for batch in self.batches.values() if not batch.running),
            key=lambda batch: batch.started_at,
        )
        for batch in finished[: max(len(self.batches) - MAX_BATCHES, 0)]:
            del self.batches[batch.id]


def _hidden_reason(repo: Repository) -> str | None:
    """Pourquoi un dépôt est masqué par défaut, et pas analysé avec les autres."""
    if repo.empty:
        return "vide"
    if repo.archived:
        return "archivé"
    if repo.fork:
        return "fork"
    return None


def _inconclusive_reason(summary: Summary, truncated: bool) -> str:
    unanswered = summary.findings.get(FindingKind.INCONCLUSIVE, 0)
    if unanswered:
        noun = "paquet non vérifié" if unanswered == 1 else "paquets non vérifiés"
        return f"{unanswered} {noun} : registre ou OSV muet"
    assert truncated
    return "arborescence tronquée par la forge : analyse partielle"


def refused_callback(connections: Connections, account: Account) -> Callable[[str], None]:
    """Ce qui note sur le compte que la forge refuse son token (appelé dans un thread)."""
    accounts = connections.accounts

    def refused(problem: str) -> None:
        try:
            accounts.refused(account, problem)
        except AccountsError as err:
            logger.warning("token refusé, non noté sur le compte : %s", err)

    return refused
