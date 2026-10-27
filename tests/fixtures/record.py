"""Ré-enregistre les réponses réelles des registres, pour les tests hors ligne.

    uv run python tests/fixtures/record.py          # toutes
    uv run python tests/fixtures/record.py npm      # celles d'un registre

À relancer quand un format de réponse change. Chaque réponse est demandée comme le fait
forceupdate (même URL, mêmes en-têtes) et gardée telle quelle, dans
``tests/fixtures/<registre>/<paquet>.json`` (``/`` d'un nom scopé écrit ``__``).

Les tests s'appuient surtout sur ce qui ne bouge plus : une version publiée, retirée ou
dépréciée le reste. Ceux qui citent la dernière version, ou le nombre de versions, sont à
mettre à jour après un nouvel enregistrement.
"""

import asyncio
import sys
from pathlib import Path

from forceupdate.net import Cache, HttpClient
from forceupdate.registries.base import Registry
from forceupdate.registries.npm import Npm
from forceupdate.registries.pypi import PyPI

FIXTURES = Path(__file__).parent

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
        },
    ),
}
"""Les paquets enregistrés, par registre, avec le cas que chacun couvre."""


def fixture_path(registry: str, name: str) -> Path:
    return FIXTURES / registry / f"{name.replace('/', '__')}.json"


async def record(registries: list[str]) -> None:
    async with HttpClient() as http:
        for key in registries:
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


def main() -> None:
    wanted = sys.argv[1:] or list(PACKAGES)
    unknown = [key for key in wanted if key not in PACKAGES]
    if unknown:
        raise SystemExit(
            f"registre inconnu : {', '.join(unknown)} (connus : {', '.join(PACKAGES)})"
        )
    asyncio.run(record(wanted))


if __name__ == "__main__":
    main()
