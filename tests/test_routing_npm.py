"""Les registres npm privés (E33) : ``.npmrc`` (portées, miroir, identifiants) et ``.yarnrc.yml``,
de bout en bout par le moteur, avec un registre privé simulé."""

import asyncio
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
import respx
from conftest import UserFiles, recorded_responses

from forceupdate import engine
from forceupdate.models import FindingKind, Report
from forceupdate.net import Cache, CacheKind, HttpClient
from forceupdate.routing import User
from forceupdate.routing.npm import parse_npmrc
from forceupdate.sources.local import LocalSource

MakeTree = Callable[..., Path]
FIXTURES = Path(__file__).parent / "fixtures" / "npm"
PRIVATE = "https://npm.acme.example"

PACKAGE_JSON = json.dumps(
    {"name": "web", "dependencies": {"@acme/ui": "^1.0.0", "left-pad": "^1.1.0"}}
)


def packument(name: str, versions: list[str]) -> dict[str, object]:
    return {
        "name": name,
        "dist-tags": {"latest": versions[-1]},
        "versions": {v: {"name": name, "version": v} for v in versions},
        "time": {v: "2026-01-01T00:00:00.000Z" for v in versions},
    }


async def no_sleep(_: float) -> None:
    pass


@contextmanager
def registries(
    private: Callable[[httpx.Request], httpx.Response] | None = None,
) -> Iterator[dict[str, respx.Route]]:
    """Les réponses enregistrées, plus le registre privé (``private`` répond pour ``@acme/ui``) et
    une route qui note si npmjs.org est demandé pour ``@acme/ui``."""
    extra: dict[str, respx.Route] = {}

    def add(router: respx.MockRouter) -> None:
        answer = private or (
            lambda _: httpx.Response(200, json=packument("@acme/ui", ["1.0.0", "1.4.0"]))
        )
        extra["private"] = router.get(f"{PRIVATE}/@acme%2Fui").mock(side_effect=answer)
        extra["public-ui"] = router.get("https://registry.npmjs.org/@acme%2Fui").respond(
            200,
            json=packument("@acme/ui", ["9.9.9"]),  # un homonyme public
        )
        extra["mirror"] = router.get(url__regex=r"^https://mirror\.example/npm/").mock(
            side_effect=lambda request: _from_fixtures(request, "https://mirror.example/npm/")
        )

    with recorded_responses(add) as routes:
        yield {**routes, **extra}


def _from_fixtures(request: httpx.Request, base: str) -> httpx.Response:
    name = str(request.url).removeprefix(base).replace("%2F", "/").replace("%2f", "/")
    path = FIXTURES / f"{name.replace('/', '__')}.json"
    if not path.is_file():
        return httpx.Response(404, json={})
    return httpx.Response(
        200, content=path.read_bytes(), headers={"content-type": "application/json"}
    )


def analyze(root: Path, cache: Cache | None = None) -> Report:
    async def main() -> Report:
        async with HttpClient(sleep=no_sleep) as http:
            return await engine.analyze(
                LocalSource(root), http=http, cache=cache or Cache.disabled()
            )

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


def test_a_scope_registry_is_asked_with_the_person_token(
    make_tree: MakeTree, user_files: UserFiles
) -> None:
    root = make_tree(
        {"package.json": PACKAGE_JSON, ".npmrc": "@acme:registry=https://npm.acme.example/\n"}
    )
    user_files.env["ACME_TOKEN"] = "t0k"
    user_files.write(".npmrc", "//npm.acme.example/:_authToken=${ACME_TOKEN}\n")
    with registries() as routes:
        report = analyze(root)
    request = routes["private"].calls.last.request
    assert request.headers["authorization"] == "Bearer t0k"
    assert routes["public-ui"].call_count == 0  # jamais l'homonyme public
    assert "@acme/ui" not in osv_names(routes)  # ni OSV
    assert "left-pad" in osv_names(routes)
    ((kind, message),) = findings(report, "@acme/ui")
    assert kind is FindingKind.OUTDATED
    assert message.startswith("Version 1.4.0 disponible (mineure)")  # du registre privé
    (project,) = report.projects
    assert any("paquet privé" in n.message for n in project.notices)
    # Le jeton n'est nulle part dans le rapport.
    assert "t0k" not in json.dumps(engine_json(report))


def engine_json(report: Report) -> dict[str, object]:
    from forceupdate.report.json import build

    return build(report)


def test_the_token_never_goes_to_another_host(make_tree: MakeTree, user_files: UserFiles) -> None:
    root = make_tree(
        {"package.json": PACKAGE_JSON, ".npmrc": "@acme:registry=https://npm.acme.example/\n"}
    )
    user_files.write(
        ".npmrc", "//registry.npmjs.org/:_authToken=npm-token\n//other.example/:_authToken=x\n"
    )
    with registries() as routes:
        analyze(root)
    assert "authorization" not in routes["private"].calls.last.request.headers
    # Celui de npmjs.org part vers npmjs.org (un paquet privé peut y être hébergé), lui seul.
    assert routes["left-pad"].calls.last.request.headers["authorization"] == "Bearer npm-token"
    assert "authorization" not in routes["osv:querybatch"].calls.last.request.headers


def test_a_refusal_says_private_unchecked_and_is_not_cached(
    make_tree: MakeTree, tmp_path: Path
) -> None:
    root = make_tree(
        {"package.json": PACKAGE_JSON, ".npmrc": "@acme:registry=https://npm.acme.example/\n"}
    )
    cache = Cache(tmp_path / "cache.sqlite3")
    with registries(lambda _: httpx.Response(401)) as routes:
        report = analyze(root, cache)
    assert findings(report, "@acme/ui") == [
        (
            FindingKind.UNVERIFIABLE,
            "Registre privé : non vérifié : npm.acme.example refuse l'accès à @acme/ui "
            "(HTTP 401) : identifiants absents ou refusés.",
        )
    ]
    assert routes["public-ui"].call_count == 0
    assert cache.get(CacheKind.VERSIONS, f"{PRIVATE}/@acme%2Fui") is None
    cache.close()


def test_a_project_variable_is_never_expanded(make_tree: MakeTree, user_files: UserFiles) -> None:
    root = make_tree(
        {
            "package.json": PACKAGE_JSON,
            ".npmrc": "@acme:registry=https://npm.acme.example/\n"
            "//npm.acme.example/:_authToken=${ACME_TOKEN}\n",
        }
    )
    user_files.env["ACME_TOKEN"] = "t0k"
    with registries() as routes:
        report = analyze(root)
    assert "authorization" not in routes["private"].calls.last.request.headers
    (project,) = report.projects
    (notice,) = [n for n in project.notices if "variable" in n.message]
    assert notice.file == ".npmrc"
    assert "jamais celles d'un fichier du projet" in notice.message
    assert "~/.npmrc" in notice.message


def test_a_mirror_serves_every_package_and_osv_still_checks_them(make_tree: MakeTree) -> None:
    root = make_tree(
        {
            "package.json": json.dumps({"name": "w", "dependencies": {"left-pad": "^1.1.0"}}),
            ".npmrc": 'registry = "https://mirror.example/npm/"\n',
        }
    )
    with registries() as routes:
        report = analyze(root)
    assert routes["mirror"].call_count == 1
    assert routes["left-pad"].call_count == 0
    assert "left-pad" in osv_names(routes)  # un miroir sert des paquets publics
    assert findings(report, "left-pad")


def test_the_environment_registry_comes_first(make_tree: MakeTree, user_files: UserFiles) -> None:
    root = make_tree(
        {
            "package.json": json.dumps({"name": "w", "dependencies": {"left-pad": "^1.1.0"}}),
            ".npmrc": "registry=https://registry.npmjs.org/\n",
        }
    )
    user_files.env["npm_config_registry"] = "https://mirror.example/npm/"
    with registries() as routes:
        analyze(root)
    assert routes["mirror"].call_count == 1


def test_a_workspace_member_reads_the_root_npmrc(make_tree: MakeTree) -> None:
    root = make_tree(
        {
            "package.json": json.dumps({"name": "root", "workspaces": ["packages/*"]}),
            ".npmrc": "@acme:registry=https://npm.acme.example/\n",
            "packages/a/package.json": PACKAGE_JSON,
        }
    )
    with registries() as routes:
        analyze(root)
    assert routes["private"].call_count == 1
    assert routes["public-ui"].call_count == 0


def test_a_scope_set_to_the_public_registry_is_public(make_tree: MakeTree) -> None:
    root = make_tree(
        {"package.json": PACKAGE_JSON, ".npmrc": "@acme:registry=https://registry.npmjs.org/\n"}
    )
    with registries() as routes:
        analyze(root)
    assert routes["public-ui"].call_count == 1
    assert routes["private"].call_count == 0


def test_yarn_berry_scopes(make_tree: MakeTree, user_files: UserFiles) -> None:
    root = make_tree(
        {
            "package.json": PACKAGE_JSON,
            ".yarnrc.yml": "npmScopes:\n  acme:\n    npmRegistryServer: https://npm.acme.example\n",
            ".npmrc": "@acme:registry=https://ignored.example/\n",  # Yarn 2+ ne le lit pas
        }
    )
    user_files.write(
        ".yarnrc.yml",
        'npmScopes:\n  acme:\n    npmAuthIdent: "jo:pw"\n'
        'npmRegistries:\n  "//npm.acme.example":\n    npmAuthToken: yarn-t0k\n',
    )
    with registries() as routes:
        analyze(root)
    assert routes["private"].calls.last.request.headers["authorization"] == "Bearer yarn-t0k"
    assert routes["public-ui"].call_count == 0


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('registry = "https://x/"\n', {"registry": "https://x/"}),
        ("; comment\n# other\n@a:registry=https://a/\n", {"@a:registry": "https://a/"}),
        ("[section]\nregistry=https://no/\n", {}),
        ("key[] = a\n", {}),
        ("//h/:_authToken='t'\n", {"//h/:_authToken": "t"}),
    ],
)
def test_parse_npmrc(text: str, expected: dict[str, str]) -> None:
    assert parse_npmrc(text) == expected


def test_basic_auth_and_auth_in_the_registry_address(
    make_tree: MakeTree, user_files: UserFiles
) -> None:
    root = make_tree({"package.json": PACKAGE_JSON})
    user_files.write(
        ".npmrc",
        "@acme:registry=https://npm.acme.example/\n"
        "//npm.acme.example/:username=jo\n//npm.acme.example/:_password=cHc=\n",
    )
    with registries() as routes:
        analyze(root)
    assert routes["private"].calls.last.request.headers["authorization"] == "Basic am86cHc="


def test_the_person_files_are_read_once(make_tree: MakeTree, user_files: UserFiles) -> None:
    user = User()
    calls = []
    user.memo("k", lambda: calls.append(1))
    user.memo("k", lambda: calls.append(1))
    assert calls == [1]
