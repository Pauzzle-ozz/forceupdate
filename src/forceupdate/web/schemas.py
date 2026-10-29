"""Ce que l'API reçoit et rend, en plus du rapport (``report.json.Document``).

Des dataclasses, comme les modèles : FastAPI en tire le schéma OpenAPI (``web/openapi.json``),
d'où viennent les types du front. Les réponses sont écrites par ``models.to_dict`` (enums par
leur valeur, dates en ISO 8601), comme le JSON de ``forceupdate scan`` ; chacun de leurs champs
est toujours présent, ``null`` compris.

**Ce que rend l'API (tranché à E12)** : les mises à jour et leurs options sont dans le rapport
(``Project.updates``) ; le reste les désigne par l'identifiant de la mise à jour (``Update.id``)
et la version de l'option (``Chosen``), au lieu de les recopier. Les ``Changes``, ``Job`` et
``Regenerated`` du moteur restent sur le serveur : il garde le plan, et c'est lui qu'on
applique, par son identifiant.

Les types de requête (``…Request``) ne servent qu'en entrée, les autres qu'en sortie : le
schéma marque requis tous les champs des réponses (``web.openapi``).
"""

import enum
from dataclasses import dataclass, field
from datetime import datetime

from forceupdate.forges.accounts import Account, ConnectMethod
from forceupdate.forges.base import Access, ChangeRequest, ForgeKind, RateLimit, Restriction
from forceupdate.models import Ecosystem, Event, FindingKind, Gap, ScanOptions, Severity
from forceupdate.report.json import Document, SummaryDocument
from forceupdate.update.forge import Step
from forceupdate.update.lockfiles import Installed, Job, LockKind, LockStatus, Reach, Regenerated
from forceupdate.update.writers import Choice, Skipped

# -- Requêtes ---------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class ScanRequest:
    """Une analyse à lancer : un dossier ou un fichier de l'ordinateur, et ce qu'elle vérifie
    (voir ``models.ScanOptions``)."""

    path: str
    """Chemin absolu du dossier ou du fichier."""
    dev: bool = True
    transitive: bool = False
    include_tests: bool = False
    offline: bool = False
    cache: bool = True

    def options(self) -> ScanOptions:
        return ScanOptions(
            include_tests=self.include_tests,
            dev=self.dev,
            transitive=self.transitive,
            offline=self.offline,
            cache=self.cache,
        )


@dataclass(frozen=True, kw_only=True)
class PlanRequest:
    """Une sélection à préparer, sur le rapport d'une analyse finie."""

    scan: str
    """L'identifiant de l'analyse."""
    selection: dict[str, str]
    """Les mises à jour choisies : ``Update.id`` → version d'une de ses options
    (``planner.Selection``). Un paquet absent n'est pas mis à jour."""


@dataclass(frozen=True, kw_only=True)
class ApplyRequest:
    """Un plan à appliquer."""

    plan: str
    """L'identifiant du plan (``POST /api/updates/plan``)."""
    force: bool = False
    """Écrire même si des fichiers à toucher ont des changements que git n'a pas en commit."""


@dataclass(frozen=True, kw_only=True)
class RepositoryOptions:
    """Ce que vérifie l'analyse d'un dépôt (voir ``models.ScanOptions``). Jamais hors ligne :
    l'arborescence et les fichiers viennent de la forge."""

    dev: bool = True
    transitive: bool = False
    include_tests: bool = False
    cache: bool = True

    def options(self) -> ScanOptions:
        return ScanOptions(
            include_tests=self.include_tests,
            dev=self.dev,
            transitive=self.transitive,
            offline=False,
            cache=self.cache,
        )


@dataclass(frozen=True, kw_only=True)
class RepositoryKey:
    """Un dépôt d'un compte connecté : sa forge, l'hôte du compte, son nom."""

    forge: ForgeKind
    host: str
    """``github.com``, ``gitlab.com``, ou l'hôte d'une instance GitLab auto-hébergée."""
    full_name: str
    """``owner/nom`` ; sur GitLab, le chemin complet du projet (``groupe/sous-groupe/nom``)."""


@dataclass(frozen=True, kw_only=True)
class BatchRequest(RepositoryOptions):
    """Des dépôts des comptes connectés à analyser ensemble (de plusieurs comptes, plusieurs
    forges au besoin)."""

    repositories: list[RepositoryKey]
    """Parmi ceux de ``GET /api/repositories``."""


@dataclass(frozen=True, kw_only=True)
class RepositoryRequest(RepositoryOptions):
    """Un dépôt à analyser, même d'un autre compte s'il est public."""

    repository: str
    """``owner/nom``, ou son adresse (``https://github.com/owner/nom``)."""


@dataclass(frozen=True, kw_only=True)
class ProposedSelection(RepositoryKey):
    """Un dépôt à mettre dans un récapitulatif de PR (MR sur GitLab), parmi ceux de
    ``GET /api/repositories``."""

    selection: dict[str, str] | None = None
    """Les mises à jour choisies sur sa dernière analyse (comme ``PlanRequest.selection``) ;
    ``null`` : la sélection par défaut (les ``selected`` du rapport)."""


@dataclass(frozen=True, kw_only=True)
class ProposalRequest:
    """Des dépôts des comptes connectés pour lesquels préparer une PR (une MR sur GitLab)
    chacun ; de plusieurs forges au besoin."""

    repositories: list[ProposedSelection]


@dataclass(frozen=True, kw_only=True)
class SendRequest:
    """Les dépôts d'un récapitulatif à envoyer : rien ne part sans cette validation."""

    repositories: list[RepositoryKey]
    """Parmi ceux prêts du récapitulatif."""


@dataclass(frozen=True, kw_only=True)
class TokenRequest:
    """Un token collé, pour connecter un compte. Le navigateur l'envoie au serveur ; le serveur
    ne le renvoie jamais."""

    token: str = field(repr=False)
    url: str | None = None
    """L'adresse d'une instance auto-hébergée (GitLab : ``https://gitlab.example.com``) ;
    ``null`` : le service en ligne de la forge."""


# -- Analyses ---------------------------------------------------------------------


class SourceKind(enum.StrEnum):
    """Ce qui est analysé."""

    FOLDER = "folder"
    FILE = "file"
    UPLOAD = "upload"
    """Un fichier envoyé par l'interface (glisser-déposer) : on télécharge sa version
    réécrite, rien n'est écrit sur le disque de la personne."""
    REPOSITORY = "repository"
    """Un dépôt d'une forge, lu par son API sans le cloner (E17)."""


@dataclass(frozen=True, kw_only=True)
class RepositoryRef:
    """Le dépôt d'une analyse de dépôt."""

    forge: ForgeKind
    host: str
    full_name: str
    """``owner/nom``."""
    url: str
    """Sa page sur la forge."""
    commit: str | None
    """Le commit lu (celui de la branche par défaut au début de l'analyse) ; ``null`` tant
    que l'arborescence n'est pas lue."""
    truncated: bool
    """La forge n'a pas rendu toute l'arborescence (GitHub : plus de 100 000 entrées), et le
    dépôt n'a pas pu être cloné : l'analyse est partielle."""
    cloned: bool
    """La forge n'a pas rendu toute l'arborescence : le dépôt a été cloné (superficiellement),
    et c'est le clone qui est analysé."""


class TaskStatus(enum.StrEnum):
    """Où en est une analyse, ou l'application d'un plan."""

    PLANNED = "planned"
    """Un plan préparé, pas encore appliqué."""
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, kw_only=True)
class ScanSummary:
    """Une analyse, sans son rapport."""

    id: str
    source: str
    """Le chemin analysé, absolu ; pour un fichier envoyé, son nom ; pour un dépôt,
    ``owner/nom``."""
    kind: SourceKind
    repository: RepositoryRef | None
    """Un dépôt d'une forge : lequel, à quel commit."""
    batch: str | None
    """L'analyse groupée dont elle fait partie (écran 7), s'il y en a une."""
    status: TaskStatus
    """``running``, puis ``done``, ``failed`` ou ``cancelled``."""
    options: ScanOptions
    started_at: datetime
    finished_at: datetime | None
    error: str | None
    """``failed`` : ce qui s'est passé."""
    progress: Event | None
    """Le dernier événement de progression."""
    summary: SummaryDocument | None
    """Les chiffres du rapport (son ``summary``) une fois l'analyse finie ; ``null`` avant, ou
    si elle n'a pas abouti. L'accueil les montre sans charger chaque rapport."""


@dataclass(frozen=True, kw_only=True)
class ScanDetail(ScanSummary):
    """Une analyse, avec son rapport une fois finie."""

    report: Document | None
    """Le JSON de ``forceupdate scan --format json`` (``docs/JSON_FORMAT.md``) ; ``null`` tant
    que l'analyse n'est pas finie, ou si elle n'a pas abouti."""


# -- Plans et mises à jour --------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class Chosen:
    """Une option de mise à jour, désignée dans le rapport de l'analyse."""

    update: str
    """``Update.id``."""
    version: str
    """``UpdateOption.version``."""


@dataclass(frozen=True, kw_only=True)
class SkippedOption:
    """Une option choisie qui ne sera pas appliquée, et pourquoi (``writers.Skipped``)."""

    update: str
    version: str
    reason: str


@dataclass(frozen=True, kw_only=True)
class FileDiff:
    """Un fichier à réécrire, et son diff unifié."""

    path: str
    diff: str


@dataclass(frozen=True, kw_only=True)
class LockJob:
    """Un lockfile à régénérer après l'écriture, et comment (``lockfiles.Job``)."""

    lockfile: str
    kind: LockKind
    tool: str
    """Le nom de l'outil, pour le dire (« uv pip compile »)."""
    program: str
    """Le programme à installer pour le régénérer."""
    available: bool
    """L'outil est installé ; sinon, la commande est à lancer à la main."""
    command: str
    """La commande à lancer à la main, dans ``directory``."""
    directory: str
    updates: tuple[Chosen, ...]
    """Les mises à jour qu'il porte."""
    workspace: bool
    reason: str | None
    """Pourquoi il est régénéré sans mise à jour à lui (pip-tools)."""
    warnings: tuple[str, ...]
    """Ce que l'outil exécute, une option d'en-tête pas reprise…"""


@dataclass(frozen=True, kw_only=True)
class InstalledVersion:
    """La version qu'une mise à jour a donnée, lockfile relu (``lockfiles.Installed``)."""

    update: str
    version: str
    """La version choisie."""
    versions: tuple[str, ...]
    """Les versions installées."""
    reach: Reach
    held_by: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class LockResult:
    """Ce qu'il est advenu d'un lockfile (``lockfiles.Regenerated``)."""

    lockfile: str
    status: LockStatus
    error: str | None
    restored: tuple[str, ...]
    installed: tuple[InstalledVersion, ...]
    changed: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class UpdatePlan:
    """Un plan de mise à jour : ce qu'écrira la sélection, puis ce qu'il en est advenu."""

    id: str
    scan: str
    """L'analyse dont il vient."""
    status: TaskStatus
    """``planned``, puis ``running`` (écriture et lockfiles), ``done`` (écrit : chaque lockfile
    dit ce qu'il est advenu de lui dans ``results``) ou ``failed`` (rien n'est écrit)."""
    created_at: datetime
    finished_at: datetime | None
    selection: dict[str, str]
    applied: tuple[Chosen, ...]
    """Les options qui seront appliquées."""
    skipped: tuple[SkippedOption, ...]
    files: tuple[FileDiff, ...]
    """Les fichiers réécrits, par chemin."""
    lockfiles: tuple[LockJob, ...]
    """Les lockfiles à régénérer ensuite, dans l'ordre ; aucun pour un fichier envoyé."""
    uncommitted: tuple[str, ...] | None
    """Parmi les fichiers à écrire, ceux qui ont des changements que git n'a pas en commit
    (vérifié de nouveau en appliquant) ; ``null`` hors d'un dépôt git."""
    applicable: bool
    """On peut l'appliquer : pas encore fait, quelque chose à écrire ou à lancer, et une source
    sur le disque (un fichier envoyé se télécharge)."""
    error: str | None
    """``failed`` : pourquoi rien n'a été écrit."""
    results: tuple[LockResult, ...]
    """``done`` : chaque lockfile."""
    progress: Event | None


# -- Dossiers ---------------------------------------------------------------------


class EntryKind(enum.StrEnum):
    DRIVE = "drive"
    """Un lecteur (``C:\\``), ou ``/``."""
    FOLDER = "folder"
    FILE = "file"
    """Un manifeste ou un lockfile que forceupdate sait reconnaître."""


@dataclass(frozen=True, kw_only=True)
class Entry:
    name: str
    path: str
    """Chemin absolu, dans la forme du système (``C:\\Users\\…`` sous Windows)."""
    kind: EntryKind
    hidden: bool
    """Nom en ``.``, ou caché pour Windows."""


@dataclass(frozen=True, kw_only=True)
class RecentPath:
    """Un chemin analysé récemment."""

    path: str
    kind: EntryKind
    """``folder`` ou ``file`` (un lecteur est un dossier)."""


@dataclass(frozen=True, kw_only=True)
class Listing:
    """Le contenu d'un dossier, pour choisir quoi analyser : ses dossiers, et les fichiers de
    dépendances qu'il contient. Jamais le contenu d'un fichier."""

    path: str | None
    """Le dossier listé ; ``null`` pour les points de départ (dossier personnel, lecteurs)."""
    parent: str | None
    entries: tuple[Entry, ...]
    """Les dossiers, puis les fichiers, par nom."""
    truncated: bool
    """Le dossier a plus d'entrées que n'en montre la liste."""
    home: str
    """Le dossier personnel."""
    recent: tuple[RecentPath, ...]
    """Les derniers chemins analysés qui existent encore, du plus récent au plus ancien."""


# -- Comptes ----------------------------------------------------------------------


class ConnectionStatus(enum.StrEnum):
    """Où en est la connexion d'un compte."""

    PENDING = "pending"
    """En attente : de l'autorisation sur la forge, ou du code tapé (device flow)."""
    DONE = "done"
    FAILED = "failed"
    EXPIRED = "expired"
    """Pas d'autorisation à temps (10 min pour OAuth, la durée du code pour le device
    flow)."""
    CANCELLED = "cancelled"
    """Annulée, ou remplacée par une autre connexion à la même forge."""


@dataclass(frozen=True, kw_only=True)
class AccountConnection:
    """Une connexion en cours ou finie, par OAuth ou par device flow."""

    id: str
    forge: ForgeKind
    method: ConnectMethod
    """``oauth`` ou ``device``."""
    status: ConnectionStatus
    created_at: datetime
    expires_at: datetime
    authorize_url: str | None
    """OAuth : la page d'autorisation de la forge, où envoyer le navigateur."""
    user_code: str | None
    """Device flow : le code à taper sur la forge."""
    verification_uri: str | None
    """Device flow : où le taper."""
    interval: int | None
    """Device flow : secondes entre deux demandes à la forge."""
    error: str | None
    """``failed``, ``expired`` : ce qui s'est passé."""
    account: Account | None
    """``done`` : le compte connecté."""


@dataclass(frozen=True, kw_only=True)
class ForgeStatus:
    """Une forge : peut-on s'y connecter, comment, et qui y est connecté."""

    forge: ForgeKind
    name: str
    host: str
    available: bool
    """La connexion est prête ; sinon, elle arrive à une étape à venir (GitLab : E19,
    Bitbucket : E20)."""
    methods: tuple[ConnectMethod, ...]
    """Les façons de se connecter possibles maintenant : ``gh`` seulement s'il est installé,
    ``oauth`` seulement si l'application a son secret."""
    scopes: tuple[str, ...]
    """Les portées demandées par OAuth et par le device flow."""
    token_url: str | None
    """Où créer un token à coller, portées pré-cochées (sur le service en ligne)."""
    self_hosted: bool
    """On peut aussi y connecter une instance auto-hébergée (GitLab), par son adresse et un
    token."""
    request: str
    """Le nom d'une proposition de changements sur cette forge : ``PR``, ``MR`` (GitLab)."""
    account: Account | None
    """Le compte connecté au service en ligne (``host``)."""
    instances: tuple[Account, ...]
    """Les comptes connectés à des instances auto-hébergées, par hôte."""
    connection: AccountConnection | None
    """La connexion en attente, s'il y en a une (un device flow se retrouve après un
    rechargement)."""


@dataclass(frozen=True, kw_only=True)
class AccountList:
    keyring: str | None
    """Pourquoi le trousseau du système ne peut pas garder de token ; ``null`` s'il marche."""
    forges: tuple[ForgeStatus, ...]


@dataclass(frozen=True, kw_only=True)
class Disconnection:
    """Un compte déconnecté : son token est effacé du trousseau."""

    forge: ForgeKind
    host: str
    login: str
    revoked: bool | None
    """Le token est aussi révoqué auprès de la forge (``true``), ne l'a pas été (``false`` :
    forge injoignable) ; ``null`` pour un token collé ou celui de gh, qui ne sont pas à
    forceupdate et restent valables."""
    message: str


# -- Dépôts -----------------------------------------------------------------------


class RepositoryState(enum.StrEnum):
    """Où en est un dépôt (écran 7), d'après sa dernière analyse."""

    NOT_SCANNED = "not_scanned"
    """Pas encore analysé (ou analyse annulée)."""
    RUNNING = "running"
    """Analyse en cours, ou en attente de son tour."""
    TO_UPDATE = "to_update"
    UP_TO_DATE = "up_to_date"
    INCONCLUSIVE = "inconclusive"
    """L'analyse n'a pas tout vérifié (registre, OSV ou forge muets, arborescence tronquée),
    ou n'a pas abouti : ni « à jour », ni « à mettre à jour »."""
    NO_DEPENDENCIES = "no_dependencies"
    """Aucun fichier de dépendances."""
    SKIPPED = "skipped"
    """Pas analysé : vide (toujours), archivé ou fork (par défaut)."""


@dataclass(frozen=True, kw_only=True)
class RepositoryCounts:
    """Les chiffres de la dernière analyse d'un dépôt."""

    vulnerabilities: int
    critical: int
    """Les failles critiques, parmi ``vulnerabilities``."""
    worst: Severity | None
    """La gravité de la faille la plus grave ; ``null`` sans faille."""
    to_update: int
    """Les constats à mettre à jour (``summary.to_update``)."""
    inconclusive: int
    """Les constats « non concluant »."""
    updates: int
    """Les mises à jour pré-cochées (celles qu'une PR porterait par défaut)."""


@dataclass(frozen=True, kw_only=True)
class RepositoryRow:
    """Un dépôt d'un compte connecté, ses drapeaux, et sa dernière analyse."""

    forge: ForgeKind
    host: str
    full_name: str
    owner: str
    name: str
    url: str
    default_branch: str | None
    private: bool
    archived: bool
    fork: bool
    empty: bool
    can_push: bool
    """Le compte peut pousser une branche et ouvrir une PR ; sinon : lecture seule."""
    pushed_at: datetime | None
    hidden: bool
    """Archivé, fork ou vide : masqué par défaut, et pas analysé avec les autres."""
    languages: tuple[str, ...]
    """Ceux de la dernière analyse ; avant, le langage principal d'après la forge."""
    state: RepositoryState
    reason: str | None
    """Pourquoi : sauté (« vide », « archivé », « fork »), non concluant (l'erreur, ou ce qui
    n'a pas répondu), annulé."""
    counts: RepositoryCounts | None
    """Les chiffres de la dernière analyse finie."""
    scan: ScanSummary | None
    """La dernière analyse du dépôt (sa progression, s'il tourne)."""
    request: ChangeRequest | None
    """La PR de forceupdate ouverte sur le dépôt, d'après ce qu'on en sait de plus récent
    (dernière analyse, dernier récapitulatif ou dernier envoi)."""


@dataclass(frozen=True, kw_only=True)
class RepositoryAccount:
    """Un compte connecté, vu depuis ses dépôts."""

    forge: ForgeKind
    host: str
    login: str
    access: Access
    problem: str | None
    """La forge refuse le token (voir l'écran Comptes)."""
    listed_at: datetime | None
    """Le dernier chargement de la liste de ses dépôts ; ``null`` s'il n'a jamais abouti."""
    error: str | None
    """Pourquoi le dernier chargement a échoué (la liste est alors celle d'avant, s'il y en a
    une)."""
    repositories: int
    restrictions: tuple[Restriction, ...]
    """Les organisations du compte dont les dépôts ne sont pas tous lisibles : à dire, pas à
    cacher."""
    rate_limit: RateLimit | None
    """Les requêtes d'API restantes, d'après la dernière réponse de la forge."""


@dataclass(frozen=True, kw_only=True)
class RepositorySynthesis:
    """La synthèse de tous les dépôts listés, calculée par le serveur."""

    repositories: int
    hidden: int
    """Masqués par défaut : archivés, forks, vides."""
    archived: int
    forks: int
    empty: int
    analyzed: int
    """Ceux dont la dernière analyse a abouti."""
    running: int
    not_scanned: int
    skipped: int
    to_update: int
    up_to_date: int
    inconclusive: int
    no_dependencies: int
    vulnerabilities: int
    """Les failles, tous dépôts confondus (un même paquet dans deux dépôts compte deux
    fois)."""
    critical: int
    vulnerable_repositories: int
    """Les dépôts qui ont au moins une faille."""
    findings: dict[FindingKind, int]
    """Les constats par type, additionnés, tous les types présents."""
    severities: dict[Severity, int]
    """Les constats à mettre à jour par gravité, additionnés."""
    open_requests: int
    """Les dépôts qui ont une PR de forceupdate ouverte."""


class BatchStatus(enum.StrEnum):
    RUNNING = "running"
    DONE = "done"
    """Toutes ses analyses sont finies (abouties ou non)."""
    CANCELLED = "cancelled"


@dataclass(frozen=True, kw_only=True)
class RepositoryBatch:
    """Une analyse groupée : des dépôts analysés ensemble (de plusieurs comptes au besoin),
    ``concurrency`` à la fois, avec le même client et le même cache des registres."""

    id: str
    status: BatchStatus
    started_at: datetime
    finished_at: datetime | None
    concurrency: int
    scans: tuple[str, ...]
    """Les identifiants de ses analyses, une par dépôt."""
    total: int
    finished: int
    """Les analyses finies (abouties, échouées ou annulées)."""
    failed: int
    skipped: tuple[str, ...]
    """Les dépôts demandés mais pas analysés (vides)."""
    requests: int
    """Les requêtes d'API envoyées aux forges."""


@dataclass(frozen=True, kw_only=True)
class RepositoryList:
    """Les dépôts des comptes connectés (écran 7)."""

    accounts: tuple[RepositoryAccount, ...]
    repositories: tuple[RepositoryRow, ...]
    """Par forge, puis par nom."""
    synthesis: RepositorySynthesis
    batch: RepositoryBatch | None
    """La dernière analyse groupée."""


# -- PR / MR ----------------------------------------------------------------------


class ProposalStatus(enum.StrEnum):
    """Où en est un récapitulatif de PR."""

    PLANNED = "planned"
    """Préparé : rien n'est poussé tant qu'il n'est pas envoyé."""
    RUNNING = "running"
    """Envoi en cours, dépôt par dépôt."""
    DONE = "done"


class ProposedState(enum.StrEnum):
    """Où en est un dépôt d'un récapitulatif."""

    READY = "ready"
    """Prêt à envoyer."""
    SKIPPED = "skipped"
    """Pas de PR : archivé, lecture seule, pas analysé, rien à mettre à jour, pas coché à
    l'envoi (``reason``)."""
    WAITING = "waiting"
    """Envoi : en attente de son tour."""
    SENDING = "sending"
    """Envoi : en cours (``step``)."""
    OPENED = "opened"
    """Une PR ouverte."""
    UPDATED = "updated"
    """La PR déjà ouverte, mise à jour."""
    NOTHING = "nothing"
    """Rien à faire sur le dépôt tel qu'il est : rien n'est poussé."""
    FAILED = "failed"
    """Pas de PR (``error``) ; les autres dépôts continuent."""


@dataclass(frozen=True, kw_only=True)
class ProposedUpdate:
    """Une mise à jour qu'une PR porte, avec ce qu'il faut pour la dire."""

    update: str
    """``Update.id``."""
    name: str
    ecosystem: Ecosystem
    project: str
    """Le dossier du projet (``.`` : la racine)."""
    direct: bool
    current: str | None
    """La version utilisée."""
    version: str
    """La version choisie."""
    gap: Gap | None
    fixes: tuple[str, ...]
    """Les failles qu'elle corrige (le premier identifiant de chacune)."""


@dataclass(frozen=True, kw_only=True)
class ProposedSkip:
    """Une mise à jour choisie qu'une PR ne portera pas, et pourquoi."""

    update: str
    name: str
    version: str
    reason: str


@dataclass(frozen=True, kw_only=True)
class ProposedRepository:
    """Un dépôt d'un récapitulatif : ce que sa PR fera, puis ce qu'elle a fait."""

    forge: ForgeKind
    host: str
    full_name: str
    url: str
    default_branch: str | None
    """La branche visée, jamais poussée directement."""
    branch: str
    """La branche de la PR (``forceupdate/dependencies``)."""
    scan: str | None
    """L'analyse dont vient la sélection."""
    commit: str | None
    """Le commit analysé."""
    state: ProposedState
    reason: str | None
    """``skipped`` : pourquoi."""
    inconclusive: bool
    """L'analyse n'a pas tout vérifié : signalé, et pas coché par défaut."""
    checked: bool
    """À envoyer par défaut : prêt, et analyse concluante."""
    request: ChangeRequest | None
    """La PR déjà ouverte (elle sera mise à jour) ; après l'envoi, celle ouverte ou mise à
    jour."""
    selection: dict[str, str]
    """La sélection préparée (``Update.id`` → version)."""
    applied: tuple[ProposedUpdate, ...]
    """Les mises à jour que la PR porte."""
    skipped: tuple[ProposedSkip, ...]
    """Les options choisies qui ne seront pas appliquées, et pourquoi."""
    files: tuple[FileDiff, ...]
    """Les fichiers réécrits et leurs diffs, d'après l'analyse."""
    lockfiles: tuple[LockJob, ...]
    """Les lockfiles à régénérer : outil trouvé, ou commande écrite dans la description."""
    step: Step | None
    """``sending`` : l'étape (clone, mise à jour, push, PR)."""
    progress: Event | None
    """Le dernier événement de la mise à jour (``regenerating`` : le lockfile en cours)."""
    pushed: bool
    """La branche a été poussée (faux : rien à faire, ou elle avait déjà ce contenu)."""
    base: str | None
    """Le commit de la branche par défaut sur lequel la mise à jour a été faite."""
    results: tuple[LockResult, ...]
    """Ce qu'il est advenu de chaque lockfile, sur le clone."""
    committed: tuple[str, ...]
    """Les fichiers du commit."""
    error: str | None
    """``failed`` : ce qui s'est passé."""


@dataclass(frozen=True, kw_only=True)
class Proposal:
    """Un récapitulatif de PR et de MR (écran 8), de plusieurs comptes au besoin : préparé sans
    rien pousser, puis envoyé dépôt par dépôt, une fois validé."""

    id: str
    status: ProposalStatus
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    repositories: tuple[ProposedRepository, ...]
    """Dans l'ordre demandé."""
    ready: int
    """Les dépôts prêts à envoyer."""
    existing: int
    """Parmi eux, ceux qui ont déjà une PR ouverte (elle sera mise à jour)."""
    error: str | None
    """Pourquoi l'envoi n'a pas pu commencer (git absent…). Un compte dont le token est refusé
    voit ses dépôts en échec, avec la raison ; les autres partent."""


@dataclass(frozen=True, kw_only=True)
class Error:
    """Une erreur : ``detail`` dit ce qui ne va pas, en français."""

    detail: str


# -- Conversions ------------------------------------------------------------------


def chosen(choice: Choice) -> Chosen:
    _, update, option = choice
    return Chosen(update=update.id, version=option.version)


def skipped_option(skipped: Skipped) -> SkippedOption:
    return SkippedOption(
        update=skipped.update.id, version=skipped.option.version, reason=skipped.reason
    )


def lock_job(job: Job) -> LockJob:
    return LockJob(
        lockfile=job.lockfile,
        kind=job.kind,
        tool=job.tool,
        program=job.program_name,
        available=job.program is not None,
        command=job.command,
        directory=job.directory,
        updates=tuple(chosen(choice) for choice in job.choices),
        workspace=job.workspace,
        reason=job.reason,
        warnings=job.warnings,
    )


def installed_version(installed: Installed) -> InstalledVersion:
    return InstalledVersion(
        update=installed.update.id,
        version=installed.option.version,
        versions=installed.versions,
        reach=installed.reach,
        held_by=installed.held_by,
    )


def lock_result(result: Regenerated) -> LockResult:
    return LockResult(
        lockfile=result.job.lockfile,
        status=result.status,
        error=result.error,
        restored=result.restored,
        installed=tuple(installed_version(item) for item in result.installed),
        changed=result.changed,
        warnings=result.warnings,
    )


def proposed_update(choice: Choice) -> ProposedUpdate:
    project, update, option = choice
    return ProposedUpdate(
        update=update.id,
        name=update.name,
        ecosystem=update.ecosystem,
        project=project.path,
        direct=update.direct,
        current=update.current_version,
        version=option.version,
        gap=option.gap,
        fixes=option.fixes,
    )


def proposed_skip(skipped: Skipped) -> ProposedSkip:
    return ProposedSkip(
        update=skipped.update.id,
        name=skipped.update.name,
        version=skipped.option.version,
        reason=skipped.reason,
    )
