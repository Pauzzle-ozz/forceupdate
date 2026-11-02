"""Les tables tenues à la main, comparées à leur source (E34) : tests ``network`` (le vrai réseau,
``pytest --run-network``), à relancer de temps en temps (un job hebdomadaire de la CI, E35).

- ``checks.eol.FRAMEWORKS`` et les produits d'endoflife.date (``/api/v1/products/full``) : chaque
  produit de la table existe ; un produit nouveau qui a un ``purl`` d'un écosystème de forceupdate,
  ni dans la table ni dans ``REVIEWED``, est dit (l'ajouter à l'une ou à l'autre) ;
- ``parsers.runtimes.NODE_CODENAMES`` et les noms des LTS de Node.js (``nodejs.org/dist/
  index.json``) ;
- ``update.project_npm.NODE_NPM`` et la majeure de npm livrée avec chaque version de Node.js ;
- ``parsers.code.IMPORT_PACKAGES`` : chaque paquet existe sur PyPI. Vérifier qu'il fournit bien
  l'import demanderait son ``top_level.txt``, dans la roue elle-même (des dizaines de Mo pour
  certaines) : pas fait.
"""

import asyncio
from typing import Any
from urllib.parse import quote, unquote

import pytest

from forceupdate.checks.eol import FRAMEWORKS
from forceupdate.models import Ecosystem
from forceupdate.net import HttpClient
from forceupdate.parsers.code import IMPORT_PACKAGES
from forceupdate.parsers.runtimes import NODE_CODENAMES
from forceupdate.update.project_npm import NODE_NPM

PURL_TYPES = {
    "pypi": Ecosystem.PYPI,
    "npm": Ecosystem.NPM,
    "composer": Ecosystem.PACKAGIST,
    "gem": Ecosystem.RUBYGEMS,
    "maven": Ecosystem.MAVEN,
    "nuget": Ecosystem.NUGET,
    "cargo": Ecosystem.CRATES_IO,
    "golang": Ecosystem.GO,
}

REVIEWED = frozenset(
    {
        # Revus le 2026-11-03 : des applications, des serveurs, des bases de données ou des
        # outils, pas un framework dont dépend le code d'un projet ; ou un runtime.
        "amazon-cdk", "ansible", "apache-activemq", "ant", "apache-cassandra", "apache-hadoop",
        "apache-maven", "apache-nifi", "bun", "cachet", "caddy", "composer", "concrete-cms",
        "consul", "deno", "drush", "elasticsearch", "envoy", "etcd", "gorilla", "grafana",
        "grails", "grumphp", "grunt", "jreleaser", "jruby", "kubernetes-csi-node-driver-registrar",
        "liquibase-secure", "neos", "phpmyadmin", "pnpm", "prometheus", "renovate", "robo",
        "silverstripe", "statamic", "tarteaucitron", "yarn", "zookeeper",
    }
)  # fmt: skip
"""Les produits d'endoflife.date à ``purl`` d'un écosystème de forceupdate, vus et laissés hors de
``FRAMEWORKS``."""


def get_json(*urls: str) -> list[Any]:
    async def main() -> list[Any]:
        async with HttpClient() as http:
            responses = await asyncio.gather(*(http.get(url) for url in urls))
        return [r.json() if r.status_code == 200 else None for r in responses]

    return asyncio.run(main())


@pytest.fixture(scope="module")
def products() -> list[dict[str, Any]]:
    (found,) = get_json("https://endoflife.date/api/v1/products/full")
    return found["result"]


@pytest.fixture(scope="module")
def node_versions() -> list[dict[str, Any]]:
    (found,) = get_json("https://nodejs.org/dist/index.json")
    return found


@pytest.mark.network
def test_every_framework_is_an_endoflife_product(products: list[dict[str, Any]]) -> None:
    names = {p["name"] for p in products} | {a for p in products for a in p.get("aliases", [])}
    missing = sorted({product for _, _, product in FRAMEWORKS} - names)
    assert missing == [], f"plus sur endoflife.date : {missing}"


@pytest.mark.network
def test_no_new_framework_product(products: list[dict[str, Any]]) -> None:
    known = {product for _, _, product in FRAMEWORKS}
    new = []
    for product in products:
        if product["name"] in known or product["name"] in REVIEWED:
            continue
        purls = [
            unquote(i["id"]) for i in product.get("identifiers", []) if i.get("type") == "purl"
        ]
        if any(p.removeprefix("pkg:").split("/", 1)[0] in PURL_TYPES for p in purls):
            new.append(f"{product['name']} ({product.get('category')}) : {purls[:2]}")
    assert new == [], "produits nouveaux, à ranger dans FRAMEWORKS ou REVIEWED :\n" + "\n".join(new)


@pytest.mark.network
def test_node_lts_codenames(node_versions: list[dict[str, Any]]) -> None:
    found: dict[str, str] = {}
    for version in node_versions:
        if isinstance(version.get("lts"), str):
            major = version["version"].lstrip("v").split(".")[0]
            found.setdefault(version["lts"].lower(), major)
    assert found == NODE_CODENAMES


@pytest.mark.network
def test_npm_shipped_with_each_node_line(node_versions: list[dict[str, Any]]) -> None:
    wrong = []
    for version in node_versions:
        text = version["version"].lstrip("v")
        if "-" in text or not version.get("npm"):
            continue
        major, minor = (int(part) for part in text.split(".")[:2])
        steps = NODE_NPM.get(major)
        if steps is None:
            if major >= min(NODE_NPM):
                wrong.append(f"Node {text} : ligne absente de NODE_NPM")
            continue
        expected = max((step for step in steps if step[0] <= minor), default=steps[0])[1]
        shipped = int(version["npm"].split(".")[0])
        if shipped != expected:
            wrong.append(f"Node {text} : npm {version['npm']}, la table dit {expected}")
    assert wrong == []


@pytest.mark.network
def test_import_packages_exist_on_pypi() -> None:
    names = sorted(set(IMPORT_PACKAGES.values()))
    found = get_json(*(f"https://pypi.org/pypi/{quote(name)}/json" for name in names))
    missing = [name for name, data in zip(names, found, strict=True) if data is None]
    assert missing == [], f"introuvables sur PyPI : {missing}"
