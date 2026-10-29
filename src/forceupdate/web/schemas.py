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
from forceupdate.forges.base import ForgeKind
from forceupdate.models import Event, ScanOptions
from forceupdate.report.json import Document, SummaryDocument
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
class TokenRequest:
    """Un token collé, pour connecter un compte. Le navigateur l'envoie au serveur ; le serveur
    ne le renvoie jamais."""

    token: str = field(repr=False)


# -- Analyses ---------------------------------------------------------------------


class SourceKind(enum.StrEnum):
    """Ce qui est analysé."""

    FOLDER = "folder"
    FILE = "file"
    UPLOAD = "upload"
    """Un fichier envoyé par l'interface (glisser-déposer) : on télécharge sa version
    réécrite, rien n'est écrit sur le disque de la personne."""


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
    """Le chemin analysé, absolu ; pour un fichier envoyé, son nom."""
    kind: SourceKind
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
    """Où créer un token à coller, portées pré-cochées."""
    account: Account | None
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
    login: str
    revoked: bool | None
    """Le token est aussi révoqué auprès de la forge (``true``), ne l'a pas été (``false`` :
    forge injoignable) ; ``null`` pour un token collé ou celui de gh, qui ne sont pas à
    forceupdate et restent valables."""
    message: str


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
