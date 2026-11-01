"""Ré-enregistre les réponses réelles des registres et d'OSV, pour les tests hors ligne.

    uv run python tests/fixtures/record.py          # toutes
    uv run python tests/fixtures/record.py npm      # celles d'un registre (pypi, npm, crates,
                                                    # goproxy, packagist, rubygems, maven, nuget,
                                                    # osv, endoflife)
    uv run python tests/fixtures/record.py pypi:jinja2   # un seul paquet
    uv run python tests/fixtures/record.py endoflife:python   # un seul produit

À relancer quand un format de réponse change. Chaque réponse est demandée comme le fait
forceupdate (même URL, mêmes en-têtes) et gardée telle quelle, dans
``tests/fixtures/<registre>/<paquet>.json`` (``/`` d'un nom scopé écrit ``__``) ; pour
crates.io, le fichier de l'index, une ligne JSON par version : ``<paquet>.jsonl`` ; pour
RubyGems, le fichier ``info`` de l'index compact, une ligne par version : ``<gem>.txt`` ; pour
Maven, le ``maven-metadata.xml`` de l'artefact (``:`` écrit ``__``) : ``<groupe>__<artefact>.xml``.
Le proxy Go demande plusieurs fichiers par module (la liste, le ``go.mod`` de la dernière version,
``@latest``, le chemin de la majeure suivante) : ``goproxy/<module>.json`` les garde tous, par
chemin (``github.com/!burnt!sushi/toml/@v/list``), avec leur statut (404 compris). NuGet aussi
(l'index de l'API « registration », puis ses pages au-delà de 128 versions) :
``nuget/<id>.json.gz``, compressé par gzip (les réponses de Serilog pèsent 2,7 Mo, 74 Ko une fois
compressées).

OSV : ``osv/queries.json`` garde, pour chaque version demandée (``écosystème/nom@version``),
le résultat de ``querybatch`` (les identifiants des failles) ; ``osv/vulns/<id>.json``, chaque
avis complet (``GET /v1/vulns/{id}``). Les versions demandées sont celles des mini-projets
``tests/projects/vulnerable``, ``cargo``, ``cargo-workspace``, ``go``, ``go-workspace``,
``composer``, ``bundler``, ``maven``, ``gradle``, ``nuget`` et ``eol`` (``OSV_PROJECTS``), plus
``OSV_EXTRA``.

endoflife.date : ``endoflife/<produit>.json``, la réponse de ``/api/v1/products/{produit}`` pour
chaque produit de ``LIFECYCLES``. Ses dates bougent avec le temps (« fin de vie dans moins de 6
mois ») : les tests se placent au jour de l'enregistrement (``RECORDED_ON``, la fixture
``_fixed_today`` de ``tests/conftest.py``), à changer avec un nouvel enregistrement.

Les tests s'appuient surtout sur ce qui ne bouge plus : une version publiée, retirée ou
dépréciée le reste, une faille corrigée aussi. Ceux qui citent la dernière version, le nombre
de versions ou de failles, sont à mettre à jour après un nouvel enregistrement.
"""

import asyncio
import gzip
import json
import sys
from collections.abc import Mapping
from datetime import date
from pathlib import Path

from forceupdate import engine
from forceupdate.advisories.osv import BASE_URL
from forceupdate.checks import vulns
from forceupdate.endoflife import EndOfLifeDate
from forceupdate.models import Ecosystem, ScanOptions
from forceupdate.net import Cache, HttpClient
from forceupdate.net.http import Response
from forceupdate.registries.base import PackageNotFound, Registry
from forceupdate.registries.crates import Crates
from forceupdate.registries.goproxy import GoProxy
from forceupdate.registries.maven import Maven
from forceupdate.registries.npm import Npm
from forceupdate.registries.nuget import NuGet
from forceupdate.registries.packagist import Packagist
from forceupdate.registries.pypi import PyPI
from forceupdate.registries.rubygems import RubyGems
from forceupdate.sources.local import LocalSource

FIXTURES = Path(__file__).parent
PROJECTS = FIXTURES.parent / "projects"
OSV_PROJECTS = (
    PROJECTS / "vulnerable",
    PROJECTS / "cargo",
    PROJECTS / "cargo-workspace",
    PROJECTS / "go",
    PROJECTS / "go-workspace",
    PROJECTS / "composer",
    PROJECTS / "bundler",
    PROJECTS / "maven",
    PROJECTS / "gradle",
    PROJECTS / "nuget",
    PROJECTS / "eol",
)
"""Les mini-projets dont les versions sont demandées à OSV."""

RECORDED_ON = date(2026, 11, 1)
"""Le jour où les réponses d'endoflife.date ont été enregistrées : celui des tests."""

LIFECYCLES: dict[str, str] = {
    "python": "Python 3.8 (eol), 3.11 et 3.12 (uv, poetry, pipenv) ; pas de LTS",
    "nodejs": "Node.js 16 (eol) ; des LTS, 26 LTS depuis le 2026-10-28",
    "django": "Django 3.2 du mini-projet eol ; 5.2 LTS conseillée",
    "go": "Go 1.21 (go, go-workspace) ; les cycles maintenus sans date de fin",
    "php": "PHP 8.1 (config.platform.php du mini-projet composer)",
    "ruby": "Ruby 3.2 en fin de vie depuis le 2026-03-31",
    "eclipse-temurin": "Java : 8u504-b01 pour dernière version, des LTS",
    "dotnet": "net8.0 (fin le 2026-11-10 : bientôt) et net10.0 du mini-projet nuget ; Core 2.1",
    "dotnetfx": "net48 ; 3.5-sp1 pour la 3.5 ; 4.8 sans date de fin",
    "symfony": "symfony/console ~5.4 du mini-projet composer : 5.4 LTS jusqu'en 2029",
    "guzzle": "guzzlehttp/guzzle 7.4.0 du mini-projet composer : 7 maintenue",
    "spring-framework": "spring-webmvc 5.3.17 du mini-projet maven : 5.3 en fin de vie",
    "spring-boot": "le plugin org.springframework.boot du mini-projet gradle",
    "log4j": "log4j-core 2.14.1 du mini-projet maven : les cycles 2 et 2.12",
    "react": "react des mini-projets npm : des cycles sans date de fin",
    "numpy": "numpy du mini-projet pip",
    "electron": "des cycles de 8 mois : la dernière finit toujours bientôt",
    "angularjs": "tous les cycles en fin de vie : aucun à conseiller",
    "nestjs": "NestJS 10 en fin de vie sans date",
}
"""Les produits d'endoflife.date enregistrés, avec le cas que chacun couvre."""

PACKAGES: dict[str, tuple[type[Registry], dict[str, str]]] = {
    "pypi": (
        PyPI,
        {
            "flask": "un paquet ordinaire",
            "requests": "deux versions retirées avec leur raison (2.32.0, 2.32.1), un vieux .egg",
            "aioredis": "un projet archivé (PEP 792)",
            "jinja2": "indirecte du mini-projet vulnerable : failles corrigées en 2.x et 3.x",
            "werkzeug": "indirecte du mini-projet vulnerable : failles corrigées en 3.x seulement",
            "django": "3.2.25 du mini-projet eol : requires-python de chaque version (5.0 : 3.10)",
        },
    ),
    "npm": (
        Npm,
        {
            "left-pad": "toutes ses versions dépréciées",
            "@hapi/joi": "un nom scopé, des étiquettes lts et preview, la latest dépréciée",
            "colors": "une étiquette next plus basse que latest",
            "crossenv": "remplacé par l'équipe sécurité de npm",
            "lodash": "une version dépréciée (4.18.0), des failles corrigées en 4.17.x et 4.18",
            "p-limit": "engines.node de chaque version (4.0.0 : >=16 ; 5 et 6 : >=18 ; 7 : >=20)",
        },
    ),
    "crates": (
        Crates,
        {
            "rand": "deux versions retirées (0.4.4, 0.7.1), des pré-versions (0.9.0-alpha…)",
            "regex": "directe du mini-projet cargo, =1.5.4 : faille corrigée en 1.5.5",
            "time": "facultative du mini-projet cargo, 0.1.45 : faille corrigée en 0.2.x",
            "anyhow": "figée sous la plus haute que permet sa contrainte (cargo, workspace)",
            "log": "renommée (my-log) dans le mini-projet cargo, reprise du workspace",
            "smallvec": "=1.6.0 dans [workspace.dependencies] : faille corrigée en 1.6.1",
        },
    ),
    "goproxy": (
        GoProxy,
        {
            "github.com/BurntSushi/toml": "des majuscules dans le chemin (!burnt!sushi)",
            "github.com/go-chi/chi": "déprécié, des +incompatible, la v5 sous …/chi/v5",
            "github.com/golang-jwt/jwt/v4": "v4.4.0 retirée (retract, sa raison), la v5 à part",
            "github.com/google/uuid": "remplacé par lui-même en v1.4.0 (replace) dans go",
            "github.com/stretchr/testify": "directe du mini-projet go, de ses tests",
            "golang.org/x/text": "v0.3.7 : trois failles, corrigées en 0.3.8, 0.39.0 et 0.41.0",
            "github.com/davecgh/go-spew": "indirecte du mini-projet go",
            "github.com/pmezard/go-difflib": "indirecte du mini-projet go",
            "gopkg.in/yaml.v3": "indirecte en pseudo-version, faille corrigée en pseudo-version",
            "golang.org/x/exp": "aucune étiquette : la pseudo-version de @latest",
            "github.com/mattn/go-sqlite3": "un intervalle de +incompatible retiré",
            "github.com/golang/protobuf": "déprécié au profit d'un autre module",
        },
    ),
    "packagist": (
        Packagist,
        {
            "monolog/monolog": "directe du mini-projet composer : 2.11.* écartées (conflict)",
            "guzzlehttp/guzzle": "7.4.0 exacte, treize failles, une majeure 8",
            "guzzlehttp/psr7": "indirecte du mini-projet composer, six failles",
            "twig/twig": "3.4.* (joker), quinze failles, une 4.0.0-alpha1 au-dessus des stables",
            "symfony/console": "des versions à v (v5.4.10), ~5.4",
            "psr/log": "une union (^1.1 || ^2.0)",
            "php-http/message-factory": "abandonné, remplacé par psr/http-factory",
            "doctrine/cache": "abandonné sans remplaçant (true), en require-dev",
        },
    ),
    "rubygems": (
        RubyGems,
        {
            "rack": "~> 2.2.3 dans le mini-projet bundler, 32 failles ; les choix de Bundler",
            "nokogiri": "des versions à plateforme (1.19.0-x86_64-linux-gnu), onze failles",
            "puma": "5.6.4 exacte, failles corrigées en 5.6.x et 7.2.1",
            "sinatra": "~> 2.2, une faille corrigée en 2.2.3, d'autres en 4.x",
            "mustermann": "dans le .gemspec du mini-projet ; des pré-versions (4.0.0.rc1)",
            "tilt": "dans le .gemspec du mini-projet (add_runtime_dependency)",
            "diff-lcs": "add_development_dependency du .gemspec du mini-projet",
            "rake": "require: false dans le mini-projet",
            "rspec": "groupe :development, :test du mini-projet",
            "minitest": "group: :test en option ; ses 5.x demandent Ruby < 4.0 jusqu'à 5.26.0",
            "tzinfo-data": "sans contrainte, platforms: %i[windows jruby]",
            "json": "dans le .gemspec de la gem locale helper (path:)",
            "rack-protection": "indirecte du mini-projet, figée = 2.2.2 par sinatra",
            "nio4r": "indirecte du mini-projet (puma)",
            "racc": "indirecte du mini-projet (nokogiri)",
            "concurrent-ruby": "indirecte du mini-projet (tzinfo)",
            "tzinfo": "indirecte du mini-projet (tzinfo-data)",
            "ruby2_keywords": "indirecte du mini-projet (mustermann)",
            "rspec-core": "indirecte de dev du mini-projet",
            "rspec-expectations": "indirecte de dev du mini-projet",
            "rspec-mocks": "indirecte de dev du mini-projet",
            "rspec-support": "indirecte de dev du mini-projet",
            "rest-client": "versions retirées (1.6.10 à 1.6.13) absentes de l'index",
        },
    ),
    "maven": (
        Maven,
        {
            "org.apache.logging.log4j:log4j-core": "Log4Shell : 2.14.1 par une propriété partagée",
            "org.apache.logging.log4j:log4j-api": "la même propriété que log4j-core (maven)",
            "org.apache:apache": "un parent hors du dépôt (23), une majeure à chaque version",
            "com.fasterxml.jackson:jackson-bom": "un BOM importé (maven), une plateforme (gradle)",
            "junit:junit": "4.12 en faille, géré par le parent avec le scope test (maven)",
            "org.apache.maven.plugins:maven-compiler-plugin": "dans pluginManagement (maven)",
            "org.apache.maven.plugins:maven-war-plugin": "un plugin à version (maven)",
            "com.google.guava:guava": "variantes -jre et -android ; faille corrigée en -android",
            "org.apache.commons:commons-text": "une plage [1.9,2.0) ; Text4Shell, corrigée en 1.10",
            "org.springframework:spring-webmvc": "5.3.17 par une propriété du module (maven)",
            "javax.servlet:javax.servlet-api": "scope provided (maven), à jour",
            "org.yaml:snakeyaml": "1.30 facultative (maven), dans gradle.properties (gradle)",
            "com.squareup.okhttp3:okhttp": "version.ref du catalogue, partagée (gradle)",
            "com.squareup.okhttp3:logging-interceptor": "la même version.ref qu'okhttp (gradle)",
            "com.github.ben-manes.versions": "un plugin du catalogue : le portail des plugins",
            "org.springframework.boot": "un plugin de build.gradle.kts : le portail des plugins",
            "androidx.annotation:annotation": "Google Maven (gradle)",
            "org.mockito:mockito-core": "notation en carte, group: name: version: (gradle)",
        },
    ),
    "nuget": (
        NuGet,
        {
            "Newtonsoft.Json": "12.0.1 centrale, en faille ; 13.0.1 en VersionOverride",
            "Serilog": "une version centrale par une propriété ; dix pages hors de l'index",
            "Microsoft.AspNetCore.Http": "2.1.0 en faille, CentralTransitive dans les tests",
            "Microsoft.SourceLink.GitHub": "PrivateAssets=all : un outil de construction",
            "xunit": "xunit 2 déprécié (Legacy), remplacé par xunit.v3",
            "xunit.runner.visualstudio": "un projet de tests : dev",
            "Microsoft.NET.Test.Sdk": "trois pages hors de l'index",
            "StyleCop.Analyzers": "un GlobalPackageReference, à jour (1.2 en pré-versions)",
            "log4net": "2.0.8 non listée et en faille (packages.config)",
            "NUnit": "allowedVersions=[3,4) : la 4 jamais proposée",
            "System.Text.Encodings.Web": "4.5.0 indirecte en faille (CVE-2021-26701)",
        },
    ),
}
"""Les paquets enregistrés, par registre, avec le cas que chacun couvre."""

OSV_EXTRA: dict[tuple[Ecosystem, str, str], str] = {
    (Ecosystem.NPM, "crossenv", "1.0.0"): "paquet malveillant (avis GitHub marqué CWE-506)",
    (Ecosystem.NPM, "flatmap-stream", "0.1.1"): "paquet malveillant, aussi connu sous MAL-…",
    (Ecosystem.NPM, "ua-parser-js", "0.7.29"): "version malveillante, corrigée en 0.7.30",
    (Ecosystem.PYPI, "flask", "2.3.0"): "deux branches corrigées : 2.2.5 et 2.3.2",
    (Ecosystem.PYPI, "requests", "2.0"): "une borne basse (>=2.0), sans lockfile",
}
"""Les versions demandées à OSV en plus de celles des mini-projets, avec le cas couvert."""

SUFFIXES = {"crates": ".jsonl", "rubygems": ".txt", "maven": ".xml", "nuget": ".json.gz"}
"""L'extension des réponses d'un registre ; ``.json`` sinon."""


def fixture_path(registry: str, name: str) -> Path:
    """Le fichier d'une réponse : ``/`` (npm) et ``:`` (Maven) s'y écrivent ``__``."""
    suffix = SUFFIXES.get(registry, ".json")
    return FIXTURES / registry / f"{name.replace('/', '__').replace(':', '__')}{suffix}"


def osv_queries() -> list[tuple[Ecosystem, str, str]]:
    """Les versions à demander à OSV : celles des mini-projets de ``OSV_PROJECTS``, puis
    ``OSV_EXTRA``."""
    found = []
    for folder in OSV_PROJECTS:
        for project in engine.inventory(LocalSource(folder)).projects:
            for dependency in project.dependencies:
                current = vulns.version_to_check(dependency)
                if vulns.audited(dependency, ScanOptions()) and current and current.version:
                    found.append((dependency.ecosystem, dependency.name, current.version))
    return list(dict.fromkeys([*found, *OSV_EXTRA]))


class _Recording(HttpClient):
    """Un client qui garde chaque réponse ``GET`` : ce que demande le proxy Go pour un module."""

    def __init__(self) -> None:
        super().__init__()
        self.seen: dict[str, Response] = {}

    async def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> Response:
        response = await super().get(url, headers=headers)
        self.seen[url] = response
        return response


async def record_several(key: str, only: str | None = None) -> None:
    """Les registres qui demandent plusieurs fichiers par paquet (le proxy Go, NuGet) : toutes
    leurs réponses, par adresse depuis celle du registre."""
    registry_class, names = PACKAGES[key]
    for name in names if only is None else [only]:
        async with _Recording() as http:
            registry = registry_class(http, Cache.disabled())
            try:
                await registry.package(name)
            except PackageNotFound as error:
                raise SystemExit(str(error)) from error
            found = {
                url.removeprefix(f"{registry_class.base_url}/"): {
                    "status": response.status_code,
                    "content_type": response.media_type,
                    "body": response.content.decode("utf-8"),
                }
                for url, response in http.seen.items()
            }
        path = fixture_path(key, name)
        path.parent.mkdir(exist_ok=True)
        text = json.dumps(found, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        if path.name.endswith(".gz"):
            data = gzip.compress(text.encode("utf-8"), compresslevel=9, mtime=0)
            path.write_bytes(data)
        else:
            path.write_text(text, encoding="utf-8", newline="\n")
        size = path.stat().st_size // 1024
        print(f"{path.relative_to(FIXTURES)} : {len(found)} réponses, {size} Ko")


async def record_registries(http: HttpClient, key: str, only: str | None = None) -> None:
    if key in ("goproxy", "nuget"):
        await record_several(key, only)
        return
    registry_class, names = PACKAGES[key]
    registry = registry_class(http, Cache.disabled())
    for name in names if only is None else [only]:
        url = registry.url_for(registry.normalize(name))
        response = await http.get(url, headers=registry.headers)
        if response.status_code != 200:
            raise SystemExit(f"{url} : HTTP {response.status_code}")
        path = fixture_path(key, name)
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(response.content)
        print(f"{path.relative_to(FIXTURES)} : {len(response.content) // 1024} Ko")


async def record_osv(http: HttpClient) -> None:
    queries = osv_queries()
    body = {
        "queries": [
            {"package": {"ecosystem": ecosystem.value, "name": name}, "version": version}
            for ecosystem, name, version in queries
        ]
    }
    response = await http.request("POST", f"{BASE_URL}/v1/querybatch", json=body, retry=True)
    if response.status_code != 200:
        raise SystemExit(f"querybatch : HTTP {response.status_code}")
    results = response.json()["results"]
    found = {
        f"{ecosystem.value}/{name}@{version}": result
        for (ecosystem, name, version), result in zip(queries, results, strict=True)
    }
    folder = FIXTURES / "osv"
    (folder / "vulns").mkdir(parents=True, exist_ok=True)
    text = json.dumps(found, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    (folder / "queries.json").write_text(text, encoding="utf-8", newline="\n")
    ids = sorted({v["id"] for result in found.values() for v in result.get("vulns", [])})
    print(f"osv/queries.json : {len(queries)} versions, {len(ids)} avis")
    for old in (folder / "vulns").glob("*.json"):
        if old.stem not in ids:
            old.unlink()
    for vuln_id in ids:
        response = await http.get(f"{BASE_URL}/v1/vulns/{vuln_id}")
        if response.status_code != 200:
            raise SystemExit(f"{vuln_id} : HTTP {response.status_code}")
        (folder / "vulns" / f"{vuln_id}.json").write_bytes(response.content)


async def record_endoflife(http: HttpClient, only: str | None = None) -> None:
    client = EndOfLifeDate(http, Cache.disabled())
    folder = FIXTURES / "endoflife"
    folder.mkdir(exist_ok=True)
    for name in LIFECYCLES if only is None else [only]:
        response = await http.get(client.url_for(name), headers={"Accept": "application/json"})
        if response.status_code != 200:
            raise SystemExit(f"{name} : HTTP {response.status_code}")
        path = folder / f"{name}.json"
        path.write_bytes(response.content)
        print(f"{path.relative_to(FIXTURES)} : {len(response.content) // 1024} Ko")


async def record(wanted: list[str]) -> None:
    async with HttpClient() as http:
        for item in wanted:
            key, _, only = item.partition(":")
            if key == "osv":
                await record_osv(http)
            elif key == "endoflife":
                await record_endoflife(http, only or None)
            else:
                await record_registries(http, key, only or None)


def main() -> None:
    known = [*PACKAGES, "osv", "endoflife"]
    wanted = sys.argv[1:] or known
    unknown = [item for item in wanted if item.partition(":")[0] not in known]
    if unknown:
        raise SystemExit(f"registre inconnu : {', '.join(unknown)} (connus : {', '.join(known)})")
    for item in wanted:
        key, _, only = item.partition(":")
        if key == "endoflife" and only and only not in LIFECYCLES:
            raise SystemExit(f"{only} : pas dans la liste des produits (LIFECYCLES).")
        if key not in ("endoflife", "osv") and only and only not in PACKAGES[key][1]:
            raise SystemExit(f"{only} : pas dans la liste des paquets de {key} (PACKAGES).")
    asyncio.run(record(wanted))


if __name__ == "__main__":
    main()
