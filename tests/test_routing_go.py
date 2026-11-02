"""Les modules Go privés (E33) : ``GOPRIVATE``, ``GONOPROXY``, ``GOPROXY`` (environnement et
fichier de ``go env -w``), ``.netrc`` ; de bout en bout par le moteur, avec un proxy simulé."""

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
from forceupdate.net import Cache, HttpClient
from forceupdate.routing import User
from forceupdate.routing.go import go_env, match_prefix_patterns, parse_goenv, proxies
from forceupdate.routing.netrc import parse_netrc
from forceupdate.sources import local
from forceupdate.sources.local import LocalSource

MakeTree = Callable[..., Path]
FIXTURES = Path(__file__).parent / "fixtures" / "goproxy"

GO_MOD = """\
module example.com/app

go 1.22

require (
	github.com/acme/private v1.2.0
	github.com/google/uuid v1.3.0
)
"""


async def no_sleep(_: float) -> None:
    pass


@contextmanager
def proxies_mocked() -> Iterator[dict[str, respx.Route]]:
    """Les réponses enregistrées, plus un proxy d'entreprise qui sert ``github.com/acme/private``
    (et renvoie le reste à ce qu'aurait dit proxy.golang.org), et une route qui note si le proxy
    public est demandé pour le module privé."""
    extra: dict[str, respx.Route] = {}

    def corp(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/go/")
        if path == "github.com/acme/private/@v/list":
            return httpx.Response(200, text="v1.2.0\nv1.3.1\n")
        if path.startswith("github.com/acme/private/@v/") and path.endswith(".mod"):
            return httpx.Response(200, text="module github.com/acme/private\n\ngo 1.22\n")
        if path.startswith("github.com/acme/private/v2/"):
            return httpx.Response(404, text="not found")
        module = path.partition("/@")[0]
        recorded = FIXTURES / f"{module.replace('/', '__')}.json"
        if recorded.is_file():
            answers = json.loads(recorded.read_text(encoding="utf-8"))
            answer = answers.get(path)
            if answer is not None:
                return httpx.Response(answer["status"], text=answer["body"])
        return httpx.Response(404, text="not found")

    def add(router: respx.MockRouter) -> None:
        extra["public-private"] = router.get(
            url__regex=r"^https://proxy\.golang\.org/github\.com/acme/"
        ).respond(404, text="not found: git ls-remote")
        extra["corp"] = router.get(url__regex=r"^https://goproxy\.corp\.example/go/").mock(
            side_effect=corp
        )

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


@pytest.fixture
def project(make_tree: MakeTree) -> Path:
    return make_tree({"go.mod": GO_MOD})


def test_a_goprivate_module_is_asked_to_no_one(project: Path, user_files: UserFiles) -> None:
    user_files.env["GOPRIVATE"] = "github.com/acme/*"
    with proxies_mocked() as routes:
        report = analyze(project)
    assert routes["public-private"].call_count == 0
    assert "github.com/acme/private" not in osv_names(routes)
    assert "github.com/google/uuid" in osv_names(routes)
    assert findings(report, "github.com/acme/private") == [
        (
            FindingKind.UNVERIFIABLE,
            "Privé : non vérifié : module de GOPRIVATE, que go prend directement chez son hôte ; "
            "ni le proxy public ni OSV ne sont interrogés.",
        )
    ]
    (project_,) = report.projects
    assert any("paquet privé" in n.message for n in project_.notices)


def test_an_import_of_a_private_module_is_asked_to_no_one(
    make_tree: MakeTree, user_files: UserFiles, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """E28 : un fichier de code seul ; ses imports sont rattachés à un module en demandant au
    proxy chaque préfixe, sauf pour un module de GOPRIVATE."""
    monkeypatch.setattr(local, "_home", lambda: tmp_path.resolve())
    main = 'package main\n\nimport "github.com/acme/private/pkg"\n\nfunc main() { pkg.Run() }\n'
    root = make_tree({"main.go": main})
    user_files.env["GOPRIVATE"] = "github.com/acme"
    with proxies_mocked() as routes:
        report = analyze(root / "main.go")
    assert routes["public-private"].call_count == 0
    ((kind, message),) = findings(report, "github.com/acme/private/pkg")
    assert kind is FindingKind.UNVERIFIABLE
    assert message.startswith("Privé : non vérifié : module de GOPRIVATE")


def test_without_goprivate_the_public_proxy_is_asked(project: Path) -> None:
    with proxies_mocked() as routes:
        report = analyze(project)
    assert routes["public-private"].call_count == 1
    assert findings(report, "github.com/acme/private")[0][0] is FindingKind.UNVERIFIABLE


def test_go_env_file(project: Path, user_files: UserFiles) -> None:
    """``go env -w GOPRIVATE=…`` écrit dans ``%APPDATA%\\go\\env`` (``GOENV``)."""
    user_files.write("AppData/Roaming/go/env", "GOPRIVATE=*.corp.example,github.com/acme\n")
    user_files.write(".config/go/env", "GOPRIVATE=*.corp.example,github.com/acme\n")
    user_files.write("Library/Application Support/go/env", "GOPRIVATE=github.com/acme\n")
    with proxies_mocked() as routes:
        report = analyze(project)
    assert routes["public-private"].call_count == 0
    (message,) = [m for _, m in findings(report, "github.com/acme/private")]
    assert "module de GOPRIVATE (go env -w)" in message


def test_goenv_variable_and_off(user_files: UserFiles) -> None:
    path = user_files.write("elsewhere/env", "GOPROXY=https://x.example\n")
    user_files.env["GOENV"] = str(path)
    assert go_env(User()).get("GOPROXY") == "https://x.example"
    user_files.env["GOENV"] = "off"
    user_files.env["GOPROXY"] = "direct"
    assert go_env(User()).origins == {"GOPROXY": "GOPROXY"}


def test_a_private_module_through_the_company_proxy(project: Path, user_files: UserFiles) -> None:
    user_files.env["GOPRIVATE"] = "github.com/acme"
    user_files.env["GONOPROXY"] = "none"
    user_files.env["GOPROXY"] = "https://goproxy.corp.example/go,https://proxy.golang.org,direct"
    user_files.write(".netrc", "machine goproxy.corp.example login jo password pw\n")
    with proxies_mocked() as routes:
        report = analyze(project)
    corp_calls = [str(c.request.url) for c in routes["corp"].calls]
    assert "https://goproxy.corp.example/go/github.com/acme/private/@v/list" in corp_calls
    assert all(c.request.headers["authorization"] == "Basic am86cHc=" for c in routes["corp"].calls)
    assert routes["public-private"].call_count == 0
    assert "github.com/acme/private" not in osv_names(routes)
    ((kind, message),) = findings(report, "github.com/acme/private")
    assert kind is FindingKind.OUTDATED
    assert "1.3.1" in message


def test_a_company_proxy_serves_public_modules_too(project: Path, user_files: UserFiles) -> None:
    user_files.env["GOPROXY"] = "https://goproxy.corp.example/go"
    with proxies_mocked() as routes:
        analyze(project)
    asked = {c.request.url.path for c in routes["corp"].calls}
    assert "/go/github.com/google/uuid/@v/list" in asked
    assert routes["goproxy:github.com/google/uuid"].call_count == 0
    assert "github.com/google/uuid" in osv_names(routes)  # un miroir sert des modules publics
    assert all("authorization" not in c.request.headers for c in routes["corp"].calls)


def test_goproxy_direct_asks_no_one(project: Path, user_files: UserFiles) -> None:
    user_files.env["GOPROXY"] = "direct"
    with proxies_mocked() as routes:
        report = analyze(project)
    assert routes["goproxy:github.com/google/uuid"].call_count == 0
    ((kind, message),) = findings(report, "github.com/google/uuid")
    assert kind is FindingKind.UNVERIFIABLE
    assert message.startswith("Non vérifié : GOPROXY=direct, go prend chaque module chez son hôte")


@pytest.mark.parametrize(
    ("globs", "target", "expected"),
    [
        # Les cas de module.TestMatchPrefixPatterns (golang.org/x/mod).
        ("*/quote", "rsc.io/quote", True),
        ("*/quo", "rsc.io/quote", False),
        ("*/quote", "rsc.io/quote/v3", True),
        ("rsc.io", "rsc.io/quote", True),
        ("rsc.io/", "rsc.io/quote", True),
        ("rsc.io/q", "rsc.io/quote", False),
        ("*.io", "rsc.io/quote", True),
        ("*.corp.example.com", "git.corp.example.com/team/mod", True),
        ("github.com/acme/*", "github.com/acme", False),
        ("github.com/acme/*", "github.com/acme/private/sub", True),
        ("a,,github.com/ACME", "github.com/acme/x", False),  # la casse compte
        ("", "rsc.io/quote", False),
    ],
)
def test_match_prefix_patterns(globs: str, target: str, expected: bool) -> None:
    assert match_prefix_patterns(globs, target) is expected


def test_proxies() -> None:
    assert proxies("https://a,https://b|direct,https://c") == (["https://a", "https://b"], "direct")
    assert proxies("off") == ([], "off")
    assert proxies("https://a") == (["https://a"], None)


def test_parse_goenv() -> None:
    assert parse_goenv("GOPRIVATE=a,b\nnot a line\nGOPROXY = x\n") == {
        "GOPRIVATE": "a,b",
        "GOPROXY": "x",
    }


def test_parse_netrc() -> None:
    text = (
        "# un commentaire\n"
        "machine a.example login jo password pw\n"
        "macdef init\ncd /\n\n"
        'machine b.example\n  login "j o"\n  password p2\n'
        "default login anon password x\n"
        "machine a.example login other password other\n"
    )
    assert parse_netrc(text) == [("a.example", "jo", "pw"), ("b.example", "j o", "p2")]
