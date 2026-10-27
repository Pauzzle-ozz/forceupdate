"""Ré-enregistre les réponses réelles des registres et d'OSV, pour les tests hors ligne.

    uv run python tests/fixtures/record.py          # toutes
    uv run python tests/fixtures/record.py npm      # celles d'un registre (pypi, npm, osv)

À relancer quand un format de réponse change. Chaque réponse est demandée comme le fait
forceupdate (même URL, mêmes en-têtes) et gardée telle quelle, dans
``tests/fixtures/<registre>/<paquet>.json`` (``/`` d'un nom scopé écrit ``__``).

OSV : ``osv/queries.json`` garde, pour chaque version demandée (``écosystème/nom@version``),
le résultat de ``querybatch`` (les identifiants des failles) ; ``osv/vulns/<id>.json``, chaque
avis complet (``GET /v1/vulns/{id}``). Les versions demandées sont celles du mini-projet
``tests/projects/vulnerable``, plus ``OSV_EXTRA``.

Les tests s'appuient surtout sur ce qui ne bouge plus : une version publiée, retirée ou
dépréciée le reste, une faille corrigée aussi. Ceux qui citent la dernière version, le nombre
de versions ou de failles, sont à mettre à jour après un nouvel enregistrement.
"""

import asyncio
import json
import sys
from pathlib import Path

from forceupdate import engine
from forceupdate.advisories.osv import BASE_URL
from forceupdate.checks import vulns
from forceupdate.models import Ecosystem, ScanOptions
from forceupdate.net import Cache, HttpClient
from forceupdate.registries.base import Registry
from forceupdate.registries.npm import Npm
from forceupdate.registries.pypi import PyPI
from forceupdate.sources.local import LocalSource

FIXTURES = Path(__file__).parent
VULNERABLE_PROJECT = FIXTURES.parent / "projects" / "vulnerable"

PACKAGES: dict[str, tuple[type[Registry], dict[str, str]]] = {
    "pypi": (
        PyPI,
        {
            "flask": "un paquet ordinaire",
            "requests": "deux versions retirées avec leur raison (2.32.0, 2.32.1), un vieux .egg",
            "aioredis": "un projet archivé (PEP 792)",
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
}
"""Les paquets enregistrés, par registre, avec le cas que chacun couvre."""

OSV_EXTRA: dict[tuple[Ecosystem, str, str], str] = {
    (Ecosystem.NPM, "crossenv", "1.0.0"): "paquet malveillant (avis GitHub marqué CWE-506)",
    (Ecosystem.NPM, "flatmap-stream", "0.1.1"): "paquet malveillant, aussi connu sous MAL-…",
    (Ecosystem.NPM, "ua-parser-js", "0.7.29"): "version malveillante, corrigée en 0.7.30",
    (Ecosystem.PYPI, "flask", "2.3.0"): "deux branches corrigées : 2.2.5 et 2.3.2",
    (Ecosystem.PYPI, "requests", "2.0"): "une borne basse (>=2.0), sans lockfile",
}
"""Les versions demandées à OSV en plus de celles du mini-projet, avec le cas couvert."""


def fixture_path(registry: str, name: str) -> Path:
    return FIXTURES / registry / f"{name.replace('/', '__')}.json"


def osv_queries() -> list[tuple[Ecosystem, str, str]]:
    """Les versions à demander à OSV : celles du mini-projet ``vulnerable``, puis
    ``OSV_EXTRA``."""
    report = engine.inventory(LocalSource(VULNERABLE_PROJECT))
    found = []
    for project in report.projects:
        for dependency in project.dependencies:
            current = vulns.version_to_check(dependency)
            if vulns.audited(dependency, ScanOptions()) and current and current.version:
                found.append((dependency.ecosystem, dependency.name, current.version))
    return list(dict.fromkeys([*found, *OSV_EXTRA]))


async def record_registries(http: HttpClient, key: str) -> None:
    registry_class, names = PACKAGES[key]
    registry = registry_class(http, Cache.disabled())
    for name in names:
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
        for key in wanted:
            if key == "osv":
                await record_osv(http)
            else:
                await record_registries(http, key)


def main() -> None:
    known = [*PACKAGES, "osv"]
    wanted = sys.argv[1:] or known
    unknown = [key for key in wanted if key not in known]
    if unknown:
        raise SystemExit(f"registre inconnu : {', '.join(unknown)} (connus : {', '.join(known)})")
    asyncio.run(record(wanted))


if __name__ == "__main__":
    main()
