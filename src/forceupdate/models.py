"""Les structures de données du moteur : dépendances, constats, projets, rapport.

Elles suivent le chemin de l'analyse (Source → Project → Dependency → Finding →
Report) et sortent en JSON avec ``to_dict`` : c'est ce que l'API renverra au front
et ce que ``scan --format json`` écrira.

Les chemins sont des chaînes au format POSIX (``backend/pyproject.toml``),
relatifs à la racine de la source analysée (le dossier choisi, ou le dépôt). Ils
ont la même forme sous Windows, sous Linux et pour un dépôt distant.

Les enums sont des ``StrEnum`` : leur valeur passe telle quelle en JSON. Pour trier
par gravité ou par écart, utiliser ``rank`` : comparer deux membres avec ``<``
compare des chaînes.
"""

import dataclasses
import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class Ecosystem(enum.StrEnum):
    """Un écosystème de paquets. Les valeurs sont les noms qu'utilise OSV."""

    PYPI = "PyPI"
    NPM = "npm"
    CRATES_IO = "crates.io"
    GO = "Go"
    PACKAGIST = "Packagist"
    RUBYGEMS = "RubyGems"
    MAVEN = "Maven"
    NUGET = "NuGet"


class Severity(enum.StrEnum):
    """Gravité d'un constat, du plus grave au moins grave.

    Remplace l'enum d'Argos (``ARGOS (1)`` dans ``reference/``), mêmes membres.
    """

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

    @property
    def rank(self) -> int:
        """Rang pour trier : 4 pour ``CRITICAL``, 0 pour ``INFO``."""
        return _SEVERITY_RANKS[self]


_SEVERITY_RANKS = {
    Severity.CRITICAL: 4,
    Severity.HIGH: 3,
    Severity.MEDIUM: 2,
    Severity.LOW: 1,
    Severity.INFO: 0,
}


class FindingKind(enum.StrEnum):
    """Le type d'un constat : les quatre types du brief, et ce qui n'a pas pu être vérifié."""

    OUTDATED = "outdated"
    """Type 1 : une version plus récente existe."""
    VULNERABLE = "vulnerable"
    """Type 2 : la version utilisée a une faille connue."""
    EOL = "eol"
    """Type 3 : le runtime ou le framework est en fin de vie, ou le sera bientôt."""
    YANKED = "yanked"
    """Type 4 : la version utilisée a été retirée du registre."""
    DEPRECATED = "deprecated"
    """Type 4 : le paquet est déprécié ou abandonné, ou la version utilisée est dépréciée (npm,
    qui n'a pas de retrait : c'est sa façon de désavouer une version)."""
    UNVERIFIABLE = "unverifiable"
    """Impossible à vérifier : dépendance git ou locale, paquet introuvable sur le registre."""
    INCONCLUSIVE = "inconclusive"
    """On ne conclut rien : la vérification a échoué (réseau, hors ligne sans cache), ou il
    manque de quoi conclure (version utilisée inconnue, inconnue du registre)."""


class Gap(enum.StrEnum):
    """L'écart entre deux versions.

    Depuis ``2.3.1`` : ``2.3.4`` est un correctif, ``2.9.0`` une mineure, ``3.0.0`` une majeure.
    """

    PATCH = "patch"
    MINOR = "minor"
    MAJOR = "major"

    @property
    def rank(self) -> int:
        """Rang pour trier : 2 pour ``MAJOR``, 0 pour ``PATCH``."""
        return _GAP_RANKS[self]


_GAP_RANKS = {Gap.MAJOR: 2, Gap.MINOR: 1, Gap.PATCH: 0}


class Scope(enum.StrEnum):
    """À quoi sert une dépendance dans son projet."""

    RUNTIME = "runtime"
    """Nécessaire pour faire tourner le code."""
    DEV = "dev"
    """Développement et tests seulement (``devDependencies``, groupe ``dev``…)."""
    OPTIONAL = "optional"
    """Facultative (extras Python, ``optionalDependencies`` npm)."""
    PEER = "peer"
    """Fournie par le projet qui l'utilise (``peerDependencies`` npm)."""
    BUILD = "build"
    """Nécessaire à la construction seulement (``build-dependencies`` Cargo…)."""


@dataclass(frozen=True, kw_only=True)
class Location:
    """L'endroit exact où une contrainte est écrite dans son fichier.

    ``line`` commence à 1 ; les colonnes commencent à 0, comptent des caractères
    (pas des octets), et ``end_column`` est exclue. C'est ce qui permet de
    réécrire la contrainte sans toucher au reste du fichier (E10).
    """

    line: int
    column: int
    end_column: int

    def __post_init__(self) -> None:
        if self.line < 1 or self.column < 0 or self.end_column < self.column:
            raise ValueError(f"emplacement invalide : {self!r}")

    def extract(self, text: str) -> str:
        """Le texte à cet emplacement dans ``text``, le contenu du fichier.

        Les lignes sont coupées sur ``\\n`` seulement, comme le font les parseurs.
        Chaîne vide si la ligne n'existe pas.
        """
        lines = text.split("\n")
        if self.line > len(lines):
            return ""
        return lines[self.line - 1][self.column : self.end_column]


@dataclass(frozen=True, kw_only=True)
class Dependency:
    """Une dépendance d'un projet.

    Une directe vient du manifeste (``package.json``, ``pyproject.toml``…). Une
    transitive vient seulement du lockfile : ``direct=False``, sans ``location``.
    """

    ecosystem: Ecosystem
    name: str
    """Nom du paquet, tel que le registre le connaît (normalisé selon PEP 503 pour PyPI)."""
    constraint: str = ""
    """Contrainte telle qu'écrite (``^4.18.0``, ``>=2.0,<3``) ; vide s'il n'y en a pas."""
    resolved_constraint: str | None = None
    """La plage que désigne ``constraint`` quand elle renvoie ailleurs : pour ``catalog:``
    (pnpm), celle du catalogue dans ``pnpm-workspace.yaml``. ``None`` si ``constraint`` est
    elle-même la plage, ou si la plage est introuvable."""
    installed: str | None = None
    """Version installée, lue dans le lockfile ; ``None`` sans lockfile."""
    lockfile: str | None = None
    """Le lockfile où ``installed`` a été lu, celui qu'une mise à jour régénère (E11) ;
    ``None`` sans version installée. Pour une indirecte, c'est ``file``."""
    direct: bool = True
    scope: Scope = Scope.RUNTIME
    file: str
    """Fichier où la dépendance est déclarée (le lockfile pour une transitive)."""
    location: Location | None = None
    """Emplacement de ``constraint`` dans ``file`` ; ``None`` si on ne sait pas la réécrire."""
    unverifiable_reason: str | None = None
    """Pourquoi on ne peut pas la vérifier (dépendance git, ``file:``, ``workspace:``…)."""

    @property
    def verifiable(self) -> bool:
        """Vrai si on peut interroger le registre et OSV pour cette dépendance."""
        return self.unverifiable_reason is None

    @property
    def effective_constraint(self) -> str:
        """La contrainte à interpréter (``forceupdate.versions``) : ``resolved_constraint``
        s'il y en a une, sinon ``constraint``."""
        return self.constraint if self.resolved_constraint is None else self.resolved_constraint


@dataclass(frozen=True, kw_only=True)
class Override:
    """Une version forcée : ``overrides`` (npm), ``resolutions`` (Yarn), ``pnpm.overrides``,
    ou ``overrides`` de ``pnpm-workspace.yaml`` (pnpm 10+).

    Elle s'impose à toutes les copies du paquet dans l'arbre (ou à celles que tire un paquet
    précis), quoi que demandent les paquets qui le tirent. Une indirecte forcée ne bouge pas
    avec ``npm update x`` : c'est la version forcée qu'il faut réécrire.
    """

    ecosystem: Ecosystem
    name: str
    """Le paquet forcé."""
    constraint: str
    """La version forcée telle qu'écrite (``^3.4.13``, ``$dompurify``, ``npm:autre@1.0``)."""
    key: str
    """La clé telle qu'écrite : ``dompurify``, ``**/lodash`` (Yarn), ``foo@<2`` ou ``a>b``
    (pnpm) ; pour npm, le chemin des clés imbriquées, séparées par ``>`` (``a>b``)."""
    section: str
    """``overrides``, ``resolutions`` ou ``pnpm.overrides`` (``overrides`` aussi dans
    ``pnpm-workspace.yaml``)."""
    file: str
    """Le ``package.json``, ou le ``pnpm-workspace.yaml``."""
    location: Location | None = None
    """Emplacement de ``constraint`` dans ``file`` ; ``None`` si on ne sait pas la réécrire."""


@dataclass(frozen=True, kw_only=True)
class Finding:
    """Un constat : quelque chose à mettre à jour, ou qui n'a pas pu être vérifié.

    Ce sont les contrôles (``checks/``) qui les produisent ; E07, E08 et E27
    complètent ce que chaque type remplit.
    """

    kind: FindingKind
    severity: Severity = Severity.INFO
    """Pour une faille, sa gravité (CVSS) ; pour les autres types, fixée par le contrôle."""
    message: str
    """Le constat en une phrase, en français."""
    dependency: Dependency | None = None
    """La dépendance concernée ; ``None`` pour la fin de vie d'un runtime (Python 3.8…)."""
    current_version: str | None = None
    """Version actuelle : l'installée, sinon la borne basse de la contrainte."""
    current_is_approximate: bool = False
    """Vrai quand ``current_version`` vient de la contrainte, faute de lockfile."""
    target_version: str | None = None
    """Version visée : la dernière stable, la plus proche non retirée, ou la plus petite
    version qui corrige la faille."""
    wanted_version: str | None = None
    """La plus haute version que la contrainte accepte déjà (``outdated``) : on y monte en
    régénérant le lockfile, sans toucher au manifeste. ``None`` si on ne la connaît pas
    (contrainte illisible, dépendance indirecte)."""
    gap: Gap | None = None
    """Écart entre ``current_version`` et ``target_version``."""
    identifiers: tuple[str, ...] = ()
    """Identifiants de la faille : les CVE, puis les GHSA, puis les autres (PYSEC, MAL…)."""
    cvss_score: float | None = None
    """Score CVSS 3 de la faille, de 0 à 10, s'il est connu."""
    detail: str | None = None
    """Ce que dit la source, tel quel : la raison d'un retrait, le message de dépréciation, le
    titre de l'avis de sécurité."""
    url: str | None = None
    """Lien pour en savoir plus : avis de sécurité (osv.dev), page du paquet, endoflife.date."""


class UpdateReason(enum.StrEnum):
    """Pourquoi une version est proposée. Une même version peut l'être pour plusieurs raisons
    (la dernière mineure corrige souvent aussi les failles)."""

    LATEST_PATCH = "latest_patch"
    """Le dernier correctif de la version utilisée."""
    LATEST_MINOR = "latest_minor"
    """La dernière mineure : la plus haute version sans changer de majeure."""
    LATEST_MAJOR = "latest_major"
    """La dernière version, quand elle est majeure."""
    SECURITY_FIX = "security_fix"
    """La plus petite version publiée qui corrige toutes les failles qui peuvent l'être."""
    REPLACEMENT = "replacement"
    """Remplace une version retirée ou dépréciée."""


class EditKind(enum.StrEnum):
    """Ce qu'une réécriture modifie."""

    DEPENDENCY = "dependency"
    """La contrainte d'une dépendance, dans son manifeste."""
    CATALOG = "catalog"
    """La plage d'un catalogue pnpm, dans ``pnpm-workspace.yaml`` : la réécriture l'y trouve
    (``update.writers``)."""
    OVERRIDE = "override"
    """Une version forcée (``overrides``, ``resolutions``, ``pnpm.overrides``)."""


@dataclass(frozen=True, kw_only=True)
class Edit:
    """Une contrainte à réécrire : à ``location`` dans ``file``, ``old`` devient ``new``.

    C'est le planificateur (E09) qui le calcule ; la réécriture (``update.writers``) vérifie que
    le fichier contient bien ``old`` à cet endroit avant d'y écrire ``new``. La déclaration
    réécrite est celle de ``Update.dependencies`` qui a ce fichier et cet emplacement (pour un
    catalogue : ce fichier et ``old`` pour ``resolved_constraint``).
    """

    kind: EditKind
    file: str
    """Le manifeste ; pour un catalogue pnpm, le ``package.json`` qui y renvoie."""
    location: Location | None
    """``None`` pour un catalogue pnpm (la réécriture cherche sa plage dans
    ``pnpm-workspace.yaml``)."""
    old: str
    new: str
    override: Override | None = None
    """La version forcée réécrite (``OVERRIDE``)."""


@dataclass(frozen=True, kw_only=True)
class UpdateOption:
    """Une version vers laquelle monter un paquet : une case à cocher de l'interface."""

    version: str
    gap: Gap | None
    """Écart depuis la version utilisée ; ``None`` pour un retour à une version plus ancienne
    (la plus proche non retirée d'une version retirée peut être en dessous)."""
    reasons: tuple[UpdateReason, ...]
    fixes: tuple[str, ...] = ()
    """Les failles qu'elle corrige : le premier identifiant de chacune (une CVE s'il y en a)."""
    unfixed: tuple[str, ...] = ()
    """Les failles qu'elle laisse."""
    introduced: tuple[str, ...] = ()
    """Les failles connues de cette version que la version utilisée n'a pas (OSV) : le premier
    identifiant de chacune. Une option qui en a n'est jamais pré-cochée."""
    edits: tuple[Edit, ...] = ()
    """Les contraintes à réécrire. Vide : la version est déjà dans la contrainte, on y monte en
    régénérant le lockfile seul."""
    lockfile: str | None = None
    """Le lockfile à régénérer (E11) ; ``None`` sans lockfile."""
    manual: str | None = None
    """Pourquoi forceupdate ne sait pas l'appliquer seul (contrainte sans emplacement, style
    non géré…) ; ``None`` s'il le sait. Elle n'est jamais pré-cochée."""
    warnings: tuple[str, ...] = ()
    """Ce qu'il faut savoir avant de la cocher (« Majeure : peut demander d'adapter le
    code. »)."""


@dataclass(frozen=True, kw_only=True)
class Update:
    """Les mises à jour possibles d'un paquet d'un projet. Au plus une est choisie : ses
    options s'excluent l'une l'autre, comme des boutons radio qu'on peut aussi tous décocher.

    Pour une directe, toutes ses déclarations (runtime et dev, deux extras) montent ensemble ;
    une indirecte est une version installée précise (npm peut en installer plusieurs).
    """

    id: str
    """Identifiant unique dans le rapport : c'est lui que la sélection désigne."""
    ecosystem: Ecosystem
    name: str
    direct: bool
    dependencies: tuple[Dependency, ...]
    """Ses déclarations (directe), ou l'indirecte."""
    current_version: str | None
    current_is_approximate: bool = False
    options: tuple[UpdateOption, ...] = ()
    """De la plus ancienne à la plus récente version."""
    selected: str | None = None
    """La version pré-cochée (brief, décision n°12) ; ``None`` si aucune ne l'est."""
    note: str | None = None
    """Ce que les options ne disent pas : faille sans version corrigée, versions publiées
    inconnues…"""

    def option(self, version: str) -> UpdateOption | None:
        """L'option de version ``version`` (le même texte) ; ``None`` s'il n'y en a pas."""
        return next((option for option in self.options if option.version == version), None)


@dataclass(frozen=True, kw_only=True)
class Language:
    """Un langage de la source, avec son poids en octets, comme GitHub Linguist."""

    name: str
    """Nom du langage, celui de Linguist (``Python``, ``TypeScript``, ``C++``)."""
    bytes: int
    """Octets de code dans ce langage, sans les fichiers vendorisés, générés ni la documentation."""
    ecosystem: Ecosystem | None = None
    """Son écosystème de paquets ; ``None`` si forceupdate n'en gère aucun (C, C++, Shell…)."""


@dataclass(frozen=True, kw_only=True)
class Notice:
    """Une remarque sur un fichier d'un projet : non lu, illisible, mal formé…

    Ce n'est pas un constat sur une dépendance : c'est ce que l'analyse n'a pas pu
    faire, pour que le rapport ne passe rien sous silence.
    """

    file: str
    """Le fichier concerné, relatif à la source."""
    message: str
    """La remarque en une phrase, en français."""


@dataclass(kw_only=True)
class Project:
    """Un projet : un dossier qui contient au moins un manifeste ou un lockfile.

    Un monorepo en donne plusieurs (``backend/`` en Python, ``frontend/`` en npm).
    """

    path: str
    """Dossier du projet (``.`` pour la racine de la source)."""
    ecosystems: list[Ecosystem] = field(default_factory=list)
    """Écosystèmes de ses manifestes et lockfiles, dans l'ordre de ``Ecosystem``."""
    manifests: list[str] = field(default_factory=list)
    lockfiles: list[str] = field(default_factory=list)
    """Ses lockfiles : ceux de son dossier, ou celui de la racine d'un workspace."""
    dependencies: list[Dependency] = field(default_factory=list)
    """Les directes d'abord, dans l'ordre des manifestes, puis les transitives."""
    overrides: list[Override] = field(default_factory=list)
    """Les versions forcées de son ``pnpm-workspace.yaml``, puis de son ``package.json`` (seules
    celles de la racine d'un workspace comptent pour npm, Yarn et pnpm)."""
    findings: list[Finding] = field(default_factory=list)
    updates: list[Update] = field(default_factory=list)
    """Les mises à jour possibles, une par paquet à mettre à jour, dans l'ordre des constats
    (``update.planner``) ; vide si les dépendances n'ont pas été vérifiées."""
    notices: list[Notice] = field(default_factory=list)
    """Ce que l'analyse n'a pas pu lire (``setup.py``, fichier invalide…)."""


@dataclass(frozen=True, kw_only=True)
class ScanOptions:
    """Ce que vérifie une analyse."""

    include_tests: bool = False
    """Garder aussi les projets rangés dans des dossiers de tests, de fixtures ou d'exemples."""
    dev: bool = True
    """Vérifier aussi les dépendances de développement (``Scope.DEV``)."""
    transitive: bool = False
    """Vérifier aussi les dépendances indirectes (celles du lockfile seul) : versions plus
    récentes, retirées, dépréciées. Par défaut, ce n'est fait que pour les directes (brief,
    décision n°3). Les failles, elles, sont toujours cherchées sur toutes les dépendances."""
    offline: bool = False
    """Hors ligne : seulement le cache, même périmé ; le reste est « non concluant »."""
    cache: bool = True
    """Lire et écrire le cache disque ; faux pour « sans cache »."""


@dataclass(kw_only=True)
class Report:
    """Le résultat d'une analyse : une source, ses langages et ses projets."""

    source: str
    """Ce qui a été analysé : un chemin local, ou ``owner/repo`` sur une forge."""
    languages: list[Language] = field(default_factory=list)
    """Les langages, du plus lourd au plus léger (en octets, comme GitHub Linguist)."""
    projects: list[Project] = field(default_factory=list)
    ignored_manifests: list[str] = field(default_factory=list)
    """Manifestes et lockfiles écartés : rangés dans un dossier de tests, de fixtures ou
    d'exemples, ce ne sont pas de vrais projets (voir ``detect.manifests.is_test_path``)."""
    options: ScanOptions | None = None
    """Ce qui a été vérifié ; ``None`` si les dépendances n'ont pas été vérifiées auprès des
    registres (``engine.inventory``)."""
    scanned_at: datetime | None = None
    """Quand l'analyse a été lancée (UTC)."""
    oldest_data: datetime | None = None
    """La date des plus anciennes données des registres et d'OSV utilisées (UTC). Hors ligne,
    elles viennent du cache, et peuvent dater de plusieurs jours : le rapport le dit."""

    @property
    def findings(self) -> list[Finding]:
        """Les constats de tous les projets."""
        return [finding for project in self.projects for finding in project.findings]


class EventKind(enum.StrEnum):
    """Les étapes d'une analyse, dans l'ordre où elles arrivent."""

    READING = "reading"
    """Lecture de la source : langages, projets, dépendances."""
    PROJECTS_FOUND = "projects_found"
    """Projets trouvés : ``total`` en donne le nombre."""
    CHECKING = "checking"
    """Vérification auprès des registres et d'OSV : ``total`` vérifications, une par paquet à
    demander aux registres, plus une pour les failles."""
    PACKAGE_CHECKED = "package_checked"
    """Un paquet vérifié auprès de son registre (``ecosystem``, ``name``) : ``done`` sur
    ``total``."""
    VULNERABILITIES_CHECKED = "vulnerabilities_checked"
    """Les failles cherchées auprès d'OSV, pour toutes les dépendances : ``done`` sur
    ``total``."""
    FINISHED = "finished"
    """Le rapport est prêt."""


@dataclass(frozen=True, kw_only=True)
class Event:
    """Un événement de progression d'une analyse : la ligne de commande en fait une barre de
    progression, l'API (E12) l'envoie au navigateur."""

    kind: EventKind
    done: int = 0
    total: int = 0
    ecosystem: Ecosystem | None = None
    name: str | None = None
    """Le paquet vérifié (``PACKAGE_CHECKED``)."""


def to_dict(model: Any) -> dict[str, Any]:
    """Convertit un modèle en dictionnaire de types simples, prêt pour ``json.dumps``.

    Les enums donnent leur valeur, les tuples des listes, les dates leur forme ISO 8601.
    """
    if not dataclasses.is_dataclass(model) or isinstance(model, type):
        raise TypeError(f"pas un modèle : {model!r}")
    return _to_plain(model)


def _to_plain(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _to_plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _to_plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_to_plain(item) for item in value]
    return value
