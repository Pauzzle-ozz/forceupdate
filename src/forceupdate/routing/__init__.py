"""À quel registre demander chaque paquet (E33) : le registre public, ou ceux que déclarent le
projet et la personne, avec leurs identifiants (``net.auth``).

D'après la configuration de l'outil de chaque écosystème (un module par écosystème : ``npm``,
``go``, ``composer``, ``maven``, ``nuget``, ``python``, ``ruby`` et ``cargo``, E34), trois cas :

- un registre **qui remplace** le public pour tous les paquets (un miroir : ``registry=`` de npm,
  ``--index-url``, un ``<mirror>`` Maven de ``central``, un autre ``GOPROXY``) : les paquets y
  sont demandés, et à OSV (ce sont des paquets publics, servis par un miroir) ;
- des registres **en plus** du public (``--extra-index-url``, un dépôt ``composer``, des
  ``<repositories>`` Maven, les sources de NuGet) : demandés d'abord, dans l'ordre ; le premier
  qui connaît le paquet l'emporte (comme Composer et uv), et le public n'est demandé que si aucun
  ne le connaît — jamais quand l'un d'eux refuse l'accès ou ne répond pas : il pourrait l'avoir ;
- un paquet **privé par son nom** (une portée npm ``@acme:registry``, un module de ``GOPRIVATE``,
  un paquet rattaché à un index par uv, Poetry ou Pipfile, un motif de ``packageSourceMapping`` de
  NuGet) : demandé à son registre seul, **jamais au public** (un homonyme y serait une attaque par
  confusion de dépendances) **ni à OSV** (qui ne connaît que les paquets publics, et n'a pas à
  apprendre son nom). Sans registre à qui le demander (un module que ``go`` prend chez son hôte) :
  « privé : non vérifié ».

Les fichiers du projet sont lus par la source (``read_text`` : une forge les télécharge, comme ceux
des parseurs) ; ceux de la personne par ``userfiles``. Un registre déclaré en http sur une autre
machine est demandé comme l'outil du projet le ferait, mais sans identifiant : un identifiant ne
part qu'en https, ou en http vers la machine elle-même (``net.auth``), et une remarque le dit
(E35 : seul Bundler le disait). Ses messages citent son hôte, jamais son adresse.
"""

import dataclasses
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from forceupdate import registries
from forceupdate.models import Dependency, Ecosystem, Notice, Project, Report
from forceupdate.net import Cache, HttpClient
from forceupdate.net.auth import Credential, Credentials, is_loopback
from forceupdate.parsers.base import ReadText
from forceupdate.registries import PackageInfo, PackageNotFound, Registry


@dataclass(frozen=True, kw_only=True)
class Declared:
    """Un registre déclaré : son adresse (sans identifiants), le fichier qui le déclare, et la
    sorte de client qui le lit quand ce n'est pas celui de l'écosystème (``composer`` : un dépôt
    Composer, pas Packagist ; voir ``registries.declared``)."""

    url: str
    file: str
    kind: str = ""

    @property
    def host(self) -> str:
        """Son nom dans les messages : l'hôte, et le port s'il est écrit."""
        return urlsplit(self.url).netloc.rpartition("@")[2].lower()


@dataclass(frozen=True, kw_only=True)
class Route:
    """Où demander un paquet : les registres déclarés, dans l'ordre, puis le public
    (``public``). ``private`` : privé par son nom, jamais demandé au public ni à OSV.
    ``unchecked`` : personne à qui le demander ; le message du constat, sans son point final
    (« Privé : non vérifié : module de GOPRIVATE… », « Non vérifié : GOPROXY=direct… »).
    ``attached`` : un paquet que le parseur dit venu d'un autre index (Python), que l'aiguillage
    sait demander à celui-ci."""

    registries: tuple[Declared, ...] = ()
    public: bool = True
    private: bool = False
    unchecked: str | None = None
    attached: bool = False

    @property
    def key(self) -> tuple[tuple[tuple[str, str], ...], bool]:
        """Ce qui distingue deux routes pour un même paquet (les registres et le public)."""
        return tuple((d.kind, d.url) for d in self.registries), self.public

    @property
    def hosts(self) -> str:
        return ", ".join(dict.fromkeys(d.host for d in self.registries))


PUBLIC = Route()

Router = Callable[[Dependency], Route]


@dataclass(kw_only=True)
class Reading:
    """Ce qu'un module d'écosystème a lu pour un projet : l'aiguillage de ses dépendances, les
    identifiants à utiliser, et des remarques (un identifiant illisible…)."""

    router: Router
    credentials: list[Credential] = field(default_factory=list)
    notices: list[Notice] = field(default_factory=list)


class User:
    """Ce qu'une analyse a lu des fichiers de la personne : chaque fichier une fois, quel que soit
    le nombre de projets (``memo``)."""

    def __init__(self) -> None:
        self._memo: dict[str, Any] = {}

    def memo(self, key: str, load: Callable[[], Any]) -> Any:
        if key not in self._memo:
            self._memo[key] = load()
        return self._memo[key]


class Routing:
    """L'aiguillage d'une analyse : ``route(projet, dépendance)``, les identifiants lus, et les
    remarques de chaque projet."""

    def __init__(
        self,
        routers: Mapping[tuple[str, Ecosystem], Router] | None = None,
        credentials: Iterable[Credential] = (),
        notices: Mapping[str, list[Notice]] | None = None,
    ) -> None:
        self._routers = dict(routers or {})
        self.credentials = Credentials(credentials)
        self._notices = dict(notices or {})

    def route(self, project: Project, dependency: Dependency) -> Route:
        router = self._routers.get((project.path, dependency.ecosystem))
        return PUBLIC if router is None else router(dependency)

    def notices(self, project: Project) -> list[Notice]:
        return list(self._notices.get(project.path, ()))


ReadProject = Callable[[Project, ReadText, User], "Reading | None"]


def _readers() -> dict[Ecosystem, ReadProject]:
    from forceupdate.routing import cargo, composer, go, maven, npm, nuget, python, ruby

    return {
        Ecosystem.CRATES_IO: cargo.read,
        Ecosystem.MAVEN: maven.read,
        Ecosystem.NPM: npm.read,
        Ecosystem.GO: go.read,
        Ecosystem.PACKAGIST: composer.read,
        Ecosystem.NUGET: nuget.read,
        Ecosystem.PYPI: python.read,
        Ecosystem.RUBYGEMS: ruby.read,
    }


def read(report: Report, read_text: ReadText, user: User | None = None) -> Routing:
    """L'aiguillage des projets de ``report`` : leurs fichiers (``read_text``) et ceux de la
    personne (``userfiles``)."""
    user = user or User()
    readers = _readers()
    routers: dict[tuple[str, Ecosystem], Router] = {}
    credentials: list[Credential] = []
    notices: dict[str, list[Notice]] = {}
    for project in report.projects:
        for ecosystem in project.ecosystems:
            reader = readers.get(ecosystem)
            reading = reader(project, read_text, user) if reader is not None else None
            if reading is None:
                continue
            routers[project.path, ecosystem] = reading.router
            credentials += reading.credentials
            said = notices.setdefault(project.path, [])
            found = [*reading.notices, *_over_http(reading.credentials)]
            said += [n for n in found if n not in said]
    return Routing(routers, credentials, notices)


def _over_http(credentials: Iterable[Credential]) -> list[Notice]:
    """Une remarque par identifiant lié à une adresse en http hors de la machine : il ne partira
    pas (``Credential.matches``), le registre est demandé sans lui."""
    return [
        Notice(
            file=credential.source,
            message=(
                f"L'identifiant pour {credential.host} n'est pas envoyé : l'adresse est en http, "
                "forceupdate n'envoie un identifiant qu'en https (ou vers la machine elle-même)."
            ),
        )
        for credential in credentials
        if credential.scheme == "http" and not is_loopback(credential.host)
    ]


def apply(report: Report, routing: Routing) -> None:
    """Rend vérifiable une dépendance que le parseur dit venue d'un autre index (Python) quand
    l'aiguillage sait le demander (``Route.attached``)."""
    for project in report.projects:
        for index, dependency in enumerate(project.dependencies):
            if dependency.unverifiable_reason is None:
                continue
            if routing.route(project, dependency).attached:
                project.dependencies[index] = _verifiable(dependency)


def _verifiable(dependency: Dependency) -> Dependency:
    return dataclasses.replace(dependency, unverifiable_reason=None)


class Clients:
    """Les clients des registres d'une analyse : le public de chaque écosystème, et un par registre
    déclaré, avec les identifiants de l'aiguillage. ``package`` suit une route."""

    def __init__(self, http: HttpClient, cache: Cache, credentials: Credentials) -> None:
        self._http = http
        self._cache = cache
        self._credentials = credentials
        self.public: dict[Ecosystem, Registry] = {}
        self.unsupported: dict[Ecosystem, str] = {}
        self._declared: dict[tuple[Ecosystem, str, str], Registry] = {}

    def client(self, ecosystem: Ecosystem) -> Registry | None:
        """Le client du registre public de ``ecosystem`` ; ``None`` s'il n'y en a pas."""
        if ecosystem not in self.public and ecosystem not in self.unsupported:
            try:
                self.public[ecosystem] = registries.for_ecosystem(
                    ecosystem, self._http, self._cache, auth=self._credentials
                )
            except LookupError as error:
                self.unsupported[ecosystem] = str(error)
        return self.public.get(ecosystem)

    def declared(self, ecosystem: Ecosystem, registry: Declared) -> Registry:
        key = (ecosystem, registry.kind, registry.url)
        client = self._declared.get(key)
        if client is None:
            client = self._declared[key] = registries.declared(
                ecosystem,
                self._http,
                self._cache,
                base_url=registry.url,
                kind=registry.kind,
                auth=self._credentials,
                label=registry.host,
            )
        return client

    async def package(self, ecosystem: Ecosystem, route: Route, name: str) -> PackageInfo:
        """Ce que disent du paquet ``name`` les registres de ``route`` : le premier qui le connaît,
        puis le public. Un refus ou une erreur d'un registre déclaré s'arrête là : le public ne
        sera pas demandé à sa place."""
        for registry in route.registries:
            try:
                return await self.declared(ecosystem, registry).package(name)
            except PackageNotFound:
                continue
        public = self.client(ecosystem) if route.public else None
        if public is not None:
            return await public.package(name)
        raise PackageNotFound(f"{name} est introuvable sur {route.hosts}.")
