"""Ré-enregistre les réponses réelles des registres et d'OSV, pour les tests hors ligne.

    uv run python tests/fixtures/record.py          # toutes
    uv run python tests/fixtures/record.py npm      # celles d'un registre (pypi, npm, crates, osv)
    uv run python tests/fixtures/record.py pypi:jinja2   # un seul paquet

À relancer quand un format de réponse change. Chaque réponse est demandée comme le fait
forceupdate (même URL, mêmes en-têtes) et gardée telle quelle, dans
``tests/fixtures/<registre>/<paquet>.json`` (``/`` d'un nom scopé écrit ``__``) ; pour
crates.io, le fichier de l'index, une ligne JSON par version : ``<paquet>.jsonl``. Le proxy Go
demande plusieurs fichiers par module (la liste, le ``go.mod`` de la dernière version,
``@latest``, le chemin de la majeure suivante) : ``goproxy/<module>.json`` les garde tous, par
chemin (``github.com/!burnt!sushi/toml/@v/list``), avec leur statut (404 compris).

OSV : ``osv/queries.json`` garde, pour chaque version demandée (``écosystème/nom@version``),
le résultat de ``querybatch`` (les identifiants des failles) ; ``osv/vulns/<id>.json``, chaque
avis complet (``GET /v1/vulns/{id}``). Les versions demandées sont celles des mini-projets
``tests/projects/vulnerable``, ``cargo``, ``cargo-workspace``, ``go`` et ``go-workspace``
(``OSV_PROJECTS``), plus ``OSV_EXTRA``.

Les tests s'appuient surtout sur ce qui ne bouge plus : une version publiée, retirée ou
dépréciée le reste, une faille corrigée aussi. Ceux qui citent la dernière version, le nombre
de versions ou de failles, sont à mettre à jour après un nouvel enregistrement.
"""

import asyncio
import json
import sys
from collections.abc import Mapping
from pathlib import Path

from forceupdate import engine
from forceupdate.advisories.osv import BASE_URL
from forceupdate.checks import vulns
from forceupdate.models import Ecosystem, ScanOptions
from forceupdate.net import Cache, HttpClient
from forceupdate.net.http import Response
from forceupdate.registries.base import PackageNotFound, Registry
from forceupdate.registries.crates import Crates
from forceupdate.registries.goproxy import GoProxy
from forceupdate.registries.npm import Npm
from forceupdate.registries.pypi import PyPI
from forceupdate.sources.local import LocalSource

FIXTURES = Path(__file__).parent
PROJECTS = FIXTURES.parent / "projects"
OSV_PROJECTS = (
    PROJECTS / "vulnerable",
    PROJECTS / "cargo",
    PROJECTS / "cargo-workspace",
    PROJECTS / "go",
    PROJECTS / "go-workspace",
)
"""Les mini-projets dont les versions sont demandées à OSV."""

PACKAGES: dict[str, tuple[type[Registry], dict[str, str]]] = {
    "pypi": (
        PyPI,
        {
            "flask": "un paquet ordinaire",
            "requests": "deux versions retirées avec leur raison (2.32.0, 2.32.1), un vieux .egg",
            "aioredis": "un projet archivé (PEP 792)",
            "jinja2": "indirecte du mini-projet vulnerable : failles corrigées en 2.x et 3.x",
            "werkzeug": "indirecte du mini-projet vulnerable : failles corrigées en 3.x seulement",
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

SUFFIXES = {"crates": ".jsonl"}
"""L'extension des réponses d'un registre ; ``.json`` sinon."""


def fixture_path(registry: str, name: str) -> Path:
    suffix = SUFFIXES.get(registry, ".json")
    return FIXTURES / registry / f"{name.replace('/', '__')}{suffix}"


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


async def record_goproxy(only: str | None = None) -> None:
    _, names = PACKAGES["goproxy"]
    for name in names if only is None else [only]:
        async with _Recording() as http:
            proxy = GoProxy(http, Cache.disabled())
            try:
                await proxy.package(name)
            except PackageNotFound as error:
                raise SystemExit(str(error)) from error
            found = {
                url.removeprefix(f"{GoProxy.base_url}/"): {
                    "status": response.status_code,
                    "content_type": response.media_type,
                    "body": response.content.decode("utf-8"),
                }
                for url, response in http.seen.items()
            }
        path = fixture_path("goproxy", name)
        path.parent.mkdir(exist_ok=True)
        text = json.dumps(found, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"{path.relative_to(FIXTURES)} : {len(found)} réponses, {len(text) // 1024} Ko")


async def record_registries(http: HttpClient, key: str, only: str | None = None) -> None:
    if key == "goproxy":
        await record_goproxy(only)
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


async def record(wanted: list[str]) -> None:
    async with HttpClient() as http:
        for item in wanted:
            key, _, only = item.partition(":")
            if key == "osv":
                await record_osv(http)
            else:
                await record_registries(http, key, only or None)


def main() -> None:
    known = [*PACKAGES, "osv"]
    wanted = sys.argv[1:] or known
    unknown = [item for item in wanted if item.partition(":")[0] not in known]
    if unknown:
        raise SystemExit(f"registre inconnu : {', '.join(unknown)} (connus : {', '.join(known)})")
    for item in wanted:
        key, _, only = item.partition(":")
        if only and only not in PACKAGES.get(key, (None, {}))[1]:
            raise SystemExit(f"{only} : pas dans la liste des paquets de {key} (PACKAGES).")
    asyncio.run(record(wanted))


if __name__ == "__main__":
    main()
