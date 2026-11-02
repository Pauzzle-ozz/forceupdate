"""Les dépôts Composer déclarés (E33) : un dépôt ``composer`` de ``repositories``
(``packages.json``, ``metadata-url``, ``available-packages``, paquets écrits en entier), ``only``,
Packagist retiré, et ``auth.json`` ; de bout en bout par le moteur, avec un dépôt simulé."""

import asyncio
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import respx
from conftest import UserFiles, recorded_responses

from forceupdate import engine
from forceupdate.models import FindingKind, Report
from forceupdate.net import Cache, HttpClient
from forceupdate.sources.local import LocalSource

MakeTree = Callable[..., Path]
SATIS = "https://satis.acme.example"

PRIVATE_P2 = {
    "packages": {
        "acme/private": [
            {"name": "acme/private", "version": "1.2.0", "time": "2026-10-01T00:00:00+00:00"},
            {"version": "1.0.0", "time": "2026-01-01T00:00:00+00:00"},
        ]
    },
    "minified": "composer/2.0",
}


def composer_json(repositories: Any, **require: str) -> str:
    wanted = require or {"acme/private": "^1.0", "monolog/monolog": "^3.0"}
    return json.dumps({"repositories": repositories, "require": wanted})


async def no_sleep(_: float) -> None:
    pass


@contextmanager
def satis(
    packages_json: dict[str, Any] | None = None,
    status: int = 200,
    includes: dict[str, Any] | None = None,
) -> Iterator[dict[str, respx.Route]]:
    """Les réponses enregistrées, plus un dépôt Satis (``packages.json`` et ``p2/``), et une route
    qui note si Packagist est demandé pour ``acme/private``."""
    root = packages_json or {
        "packages": [],
        "metadata-url": "/p2/%package%.json",
        "available-packages": ["acme/private"],
    }
    extra: dict[str, respx.Route] = {}

    def add(router: respx.MockRouter) -> None:
        extra["root"] = router.get(f"{SATIS}/packages.json").respond(status, json=root)
        for path, content in (includes or {}).items():
            router.get(f"{SATIS}/{path}").respond(200, json=content)
        extra["p2"] = router.get(f"{SATIS}/p2/acme/private.json").respond(status, json=PRIVATE_P2)
        extra["p2-other"] = router.get(url__regex=rf"^{SATIS}/p2/").respond(404)
        extra["packagist-private"] = router.get(
            "https://repo.packagist.org/p2/acme/private.json"
        ).respond(200, json={"packages": {"acme/private": [{"version": "9.9.9"}]}})

    with recorded_responses(add) as routes:
        yield {**routes, **extra}


def analyze(root: Path) -> Report:
    async def main() -> Report:
        async with HttpClient(sleep=no_sleep) as http:
            return await engine.analyze(LocalSource(root), http=http, cache=Cache.disabled())

    return asyncio.run(main())


def findings(report: Report, name: str) -> list[tuple[FindingKind, str]]:
    return [
        (f.kind, f.message)
        for project in report.projects
        for f in project.findings
        if f.dependency is not None and f.dependency.name == name
    ]


def osv_names(routes: dict[str, respx.Route]) -> set[str]:
    return {
        query["package"]["name"]
        for call in routes["osv:querybatch"].calls
        for query in json.loads(call.request.content)["queries"]
    }


def test_a_composer_repository_is_asked_before_packagist(make_tree: MakeTree) -> None:
    root = make_tree({"composer.json": composer_json([{"type": "composer", "url": SATIS}])})
    with satis() as routes:
        report = analyze(root)
    assert routes["root"].call_count == 1  # une fois pour l'analyse
    assert routes["p2"].call_count == 1
    assert routes["packagist-private"].call_count == 0
    # monolog n'est pas dans available-packages : demandé à Packagist, sans requête au dépôt.
    assert routes["p2-other"].call_count == 0
    assert routes["packagist:monolog/monolog"].call_count == 1
    ((kind, message),) = findings(report, "acme/private")
    assert kind is FindingKind.OUTDATED
    assert "1.2.0" in message


def test_auth_json_of_the_person(make_tree: MakeTree, user_files: UserFiles) -> None:
    root = make_tree({"composer.json": composer_json([{"type": "composer", "url": SATIS}])})
    user_files.write(
        "AppData/Roaming/Composer/auth.json",
        json.dumps({"http-basic": {"satis.acme.example": {"username": "jo", "password": "pw"}}}),
    )
    user_files.write(
        ".composer/auth.json",
        json.dumps({"http-basic": {"satis.acme.example": {"username": "jo", "password": "pw"}}}),
    )
    with satis() as routes:
        analyze(root)
    for name in ("root", "p2"):
        assert routes[name].calls.last.request.headers["authorization"] == "Basic am86cHc="
    assert "authorization" not in routes["packagist:monolog/monolog"].calls.last.request.headers


def test_composer_auth_comes_first(make_tree: MakeTree, user_files: UserFiles) -> None:
    root = make_tree(
        {
            "composer.json": composer_json([{"type": "composer", "url": SATIS}]),
            "auth.json": json.dumps({"bearer": {"satis.acme.example": "project"}}),
        }
    )
    user_files.env["COMPOSER_AUTH"] = json.dumps({"bearer": {"satis.acme.example": "env"}})
    with satis() as routes:
        analyze(root)
    assert routes["p2"].calls.last.request.headers["authorization"] == "Bearer env"


def test_a_refusal_says_private_unchecked_and_never_asks_packagist(make_tree: MakeTree) -> None:
    root = make_tree({"composer.json": composer_json([{"type": "composer", "url": SATIS}])})
    with satis(status=401) as routes:
        report = analyze(root)
    assert routes["packagist-private"].call_count == 0
    assert routes["packagist:monolog/monolog"].call_count == 0  # le dépôt pourrait l'avoir
    assert findings(report, "acme/private") == [
        (
            FindingKind.UNVERIFIABLE,
            "Registre privé : non vérifié : satis.acme.example refuse l'accès à son packages.json "
            "(HTTP 401) : identifiants absents ou refusés.",
        )
    ]


def test_only_makes_packages_private(make_tree: MakeTree) -> None:
    repositories = [{"type": "composer", "url": SATIS, "only": ["acme/*"]}]
    root = make_tree({"composer.json": composer_json(repositories)})
    with satis() as routes:
        report = analyze(root)
    assert routes["packagist-private"].call_count == 0
    assert "acme/private" not in osv_names(routes)
    assert "monolog/monolog" in osv_names(routes)
    assert routes["root"].call_count == 1  # monolog n'est pas demandé au dépôt
    (project,) = report.projects
    assert any("paquet privé" in n.message for n in project.notices)


def test_without_packagist(make_tree: MakeTree) -> None:
    repositories = {"acme": {"type": "composer", "url": SATIS}, "packagist.org": False}
    root = make_tree({"composer.json": composer_json(repositories)})
    with satis() as routes:
        report = analyze(root)
    assert routes["packagist:monolog/monolog"].call_count == 0
    assert findings(report, "monolog/monolog") == [
        (FindingKind.UNVERIFIABLE, "monolog/monolog est introuvable sur satis.acme.example.")
    ]


def test_packages_written_in_packages_json(make_tree: MakeTree) -> None:
    """Un Satis ancien, sans ``metadata-url`` : les versions écrites dans ``packages.json`` et
    dans ses ``includes``."""
    root_json = {
        "packages": {"acme/private": {"1.0.0": {"name": "acme/private", "version": "1.0.0"}}},
        "includes": {"include/all$abc.json": {"sha1": "abc"}},
    }
    included = {
        "packages": {
            "acme/private": {
                "1.5.0": {"name": "acme/private", "version": "1.5.0", "abandoned": "acme/new"}
            }
        }
    }
    root = make_tree({"composer.json": composer_json([{"type": "composer", "url": SATIS}])})
    with satis(root_json, includes={"include/all$abc.json": included}):
        report = analyze(root)
    kinds = {kind: message for kind, message in findings(report, "acme/private")}
    assert "1.5.0" in kinds[FindingKind.OUTDATED]
    assert kinds[FindingKind.DEPRECATED].endswith(
        "abandonné sur satis.acme.example, remplacé par acme/new."
    )


def test_a_packagist_repository_is_packagist(make_tree: MakeTree) -> None:
    repositories = [{"type": "composer", "url": "https://repo.packagist.org"}]
    root = make_tree({"composer.json": composer_json(repositories, **{"monolog/monolog": "^3.0"})})
    with satis() as routes:
        analyze(root)
    assert routes["packagist:monolog/monolog"].call_count == 1
    assert routes["root"].call_count == 0
