"""L'API des dépôts (``web.routes.repositories``, ``web.repositories``) : la liste des dépôts du
compte connecté et leurs drapeaux, les organisations restreintes, les requêtes restantes, les
analyses groupées et leur annulation, la synthèse calculée par le serveur, et l'analyse d'un
dépôt public donné par son nom. GitHub est simulé (``fake_forge``), les registres et OSV
répondent avec les réponses enregistrées, le trousseau est en mémoire."""

import json
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from conftest import recorded_responses
from fake_forge import FakeGitHubRepos, FakeRepo, from_directory, make_remote, remotes_url
from fastapi.testclient import TestClient

from forceupdate.forges import github as github_module
from forceupdate.forges.accounts import Accounts, ConnectMethod
from forceupdate.forges.base import Access, ForgeKind, Identity
from forceupdate.net import http as http_module
from forceupdate.web import jobs as jobs_module
from forceupdate.web import openapi

PROJECTS = Path(__file__).parent / "projects"
TOKEN = "gho_depots"
Finished = Callable[[str], dict[str, Any]]


def repos() -> list[FakeRepo]:
    return [
        from_directory("octo/vulnerable", PROJECTS / "vulnerable", private=True, language="Python"),
        FakeRepo(full_name="octo/a-jour", files={"requirements.txt": b"werkzeug==3.1.9\n"}),
        FakeRepo(full_name="octo/docs", files={"README.md": b"# docs\n"}, language="Markdown"),
        FakeRepo(
            full_name="octo/immense",
            files={"requirements.txt": b"werkzeug==3.1.9\n"},
            truncated=True,
        ),
        FakeRepo(full_name="octo/ancien", archived=True, files={"requirements.txt": b"flask\n"}),
        FakeRepo(full_name="octo/copie", fork=True, files={"requirements.txt": b"flask\n"}),
        FakeRepo(full_name="octo/neuf", empty=True),
        FakeRepo(
            full_name="atelier/site", push=False, files={"package.json": b'{"dependencies": {}}'}
        ),
    ]


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[FakeGitHubRepos]:
    monkeypatch.setattr(http_module, "_backoff", lambda attempt: 0.0)
    other = FakeRepo(
        full_name="ailleurs/public", files={"requirements.txt": b"flask==0.12\n"}, member=False
    )
    fake = FakeGitHubRepos(
        [*repos(), other], tokens={TOKEN}, organizations={"atelier": "ok", "nord": "restricted"}
    )
    # L'arborescence tronquée : le dépôt est cloné, depuis un dépôt « bare » du test.
    make_remote(fake.repos["octo/immense"], tmp_path / "distants")
    monkeypatch.setattr(github_module, "GIT_URL", remotes_url(tmp_path / "distants"))
    with recorded_responses(extra=fake.routes):
        yield fake


def connect(api: TestClient, token: str = TOKEN) -> Accounts:
    """Range un compte GitHub connecté, comme le fait ``POST /api/accounts/github/token``."""
    accounts: Accounts = api.app.state.connections.accounts  # type: ignore[attr-defined]
    identity = Identity(
        forge=ForgeKind.GITHUB,
        host="github.com",
        login="octo",
        name="Octo Cat",
        url="https://github.com/octo",
        access=Access.WRITE,
        scopes=("repo", "read:org"),
        warnings=(),
    )
    accounts.save(identity, token, ConnectMethod.TOKEN)
    return accounts


def rows(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["full_name"]: row for row in document["repositories"]}


def keys(*names: str, forge: str = "github", host: str = "github.com") -> list[dict[str, str]]:
    """Les dépôts ``names`` d'un compte, comme les désigne l'API."""
    return [{"forge": forge, "host": host, "full_name": name} for name in names]


def run_batch(
    api: TestClient, finished: Finished, names: list[str], **options: Any
) -> dict[str, Any]:
    response = api.post("/api/repositories/batches", json={"repositories": keys(*names), **options})
    assert response.status_code == 202, response.text
    batch = response.json()
    for scan_id in batch["scans"]:
        finished(f"/api/scans/{scan_id}")
    return api.get(f"/api/repositories/batches/{batch['id']}").json()


VISIBLE = ["octo/vulnerable", "octo/a-jour", "octo/docs", "octo/immense", "atelier/site"]


# -- La liste -----------------------------------------------------------------------


def test_without_an_account_there_is_nothing(api: TestClient, github: FakeGitHubRepos) -> None:
    document = api.get("/api/repositories").json()
    assert document["accounts"] == []
    assert document["repositories"] == []
    assert document["synthesis"]["repositories"] == 0
    assert document["batch"] is None
    assert github.requests == []


def test_the_repositories_of_the_account_and_their_flags(
    api: TestClient, github: FakeGitHubRepos
) -> None:
    connect(api)
    document = api.get("/api/repositories").json()
    (account,) = document["accounts"]
    assert account["forge"] == "github"
    assert account["login"] == "octo"
    assert account["error"] is None
    assert account["repositories"] == 8
    assert account["listed_at"] is not None
    assert account["restrictions"] == [
        {
            "organization": "nord",
            "kind": "app_access",
            "url": "https://github.com/settings/applications",
        }
    ]
    assert account["rate_limit"]["limit"] == 5000
    assert account["rate_limit"]["remaining"] < 5000
    found = rows(document)
    assert list(found) == sorted(found, key=str.lower)
    vulnerable = found["octo/vulnerable"]
    assert (vulnerable["owner"], vulnerable["name"]) == ("octo", "vulnerable")
    assert vulnerable["private"] is True
    assert vulnerable["can_push"] is True
    assert vulnerable["hidden"] is False
    assert vulnerable["state"] == "not_scanned"
    assert vulnerable["languages"] == ["Python"]
    assert vulnerable["pushed_at"] == "2026-10-20T10:00:00+00:00"
    assert vulnerable["scan"] is None
    assert found["atelier/site"]["can_push"] is False
    hidden = {name: (row["state"], row["reason"]) for name, row in found.items() if row["hidden"]}
    assert hidden == {
        "octo/ancien": ("skipped", "archivé"),
        "octo/copie": ("skipped", "fork"),
        "octo/neuf": ("skipped", "vide"),
    }
    assert found["octo/neuf"]["empty"] is True
    synthesis = document["synthesis"]
    assert (synthesis["repositories"], synthesis["hidden"], synthesis["skipped"]) == (8, 3, 3)
    assert (synthesis["archived"], synthesis["forks"], synthesis["empty"]) == (1, 1, 1)
    assert (synthesis["analyzed"], synthesis["not_scanned"]) == (0, 5)
    # La liste est gardée : la redemander ne coûte rien ; « reload » la recharge.
    sent = len(github.requests)
    api.get("/api/repositories")
    assert len(github.requests) == sent
    api.get("/api/repositories", params={"reload": True})
    assert len(github.requests) > sent


def test_a_refused_token_is_said_on_the_account(api: TestClient, github: FakeGitHubRepos) -> None:
    accounts = connect(api, token="gho_revoque")
    document = api.get("/api/repositories").json()
    (account,) = document["accounts"]
    assert "GitHub refuse le token (401)" in account["error"]
    assert account["listed_at"] is None
    assert document["repositories"] == []
    # L'écran Comptes le montre (``problem``) ; le token ne sort jamais.
    assert account["problem"] == account["error"]
    assert accounts.get(ForgeKind.GITHUB, "github.com").problem == account["error"]  # type: ignore[union-attr]
    assert "gho_revoque" not in json.dumps(document)
    # Reconnecté (un autre token) : la liste est rechargée sans qu'on le demande.
    connect(api)
    document = api.get("/api/repositories").json()
    assert document["accounts"][0]["problem"] is None
    assert document["accounts"][0]["error"] is None
    assert len(document["repositories"]) == 8


def test_the_last_list_stays_when_github_does_not_answer(
    api: TestClient, github: FakeGitHubRepos
) -> None:
    connect(api)
    api.get("/api/repositories")
    github.down = True
    document = api.get("/api/repositories", params={"reload": True}).json()
    (account,) = document["accounts"]
    assert account["error"].startswith("GitHub ne répond pas")
    assert account["listed_at"] is not None
    assert len(document["repositories"]) == 8


# -- Les analyses groupées ----------------------------------------------------------


def test_a_batch_analyzes_each_repository_without_cloning_but_a_truncated_one(
    api: TestClient, github: FakeGitHubRepos, finished: Finished
) -> None:
    connect(api)
    api.get("/api/repositories")
    batch = run_batch(api, finished, [*VISIBLE, "octo/neuf"])
    assert batch["status"] == "done"
    assert (batch["total"], batch["finished"], batch["failed"]) == (5, 5, 0)
    assert batch["skipped"] == ["octo/neuf"]
    assert batch["concurrency"] == 4
    assert batch["requests"] > 0
    # Les requêtes restantes sont celles du compte, d'après la dernière réponse du lot.
    account = api.get("/api/repositories").json()["accounts"][0]
    assert account["rate_limit"]["remaining"] < 5000
    # Seuls les fichiers de dépendances sont lus (le dépôt tronqué est ensuite cloné).
    downloaded = {item.split(":")[1] for item in github.contents()}
    assert downloaded == {
        "package.json",
        "package-lock.json",
        "requirements.txt",
        "requirements.in",
    }

    document = api.get("/api/repositories").json()
    found = rows(document)
    vulnerable = found["octo/vulnerable"]
    assert vulnerable["state"] == "to_update"
    assert vulnerable["counts"] == {
        "vulnerabilities": 28,
        "critical": 0,
        "worst": "high",
        "to_update": 30,
        "inconclusive": 0,
        "updates": 3,
    }
    # Que des manifestes, aucun fichier de code : le langage dit par GitHub reste.
    assert vulnerable["languages"] == ["Python"]
    assert vulnerable["scan"]["kind"] == "repository"
    assert vulnerable["scan"]["batch"] == batch["id"]
    assert vulnerable["scan"]["repository"]["commit"] == github.repos["octo/vulnerable"].commit
    assert found["octo/a-jour"]["state"] == "up_to_date"
    assert found["octo/docs"]["state"] == "no_dependencies"
    # L'arborescence tronquée par GitHub : c'est un clone superficiel qui est analysé, en entier.
    immense = found["octo/immense"]
    assert immense["state"] == "up_to_date"
    assert immense["scan"]["repository"]["cloned"]
    assert not immense["scan"]["repository"]["truncated"]
    assert immense["scan"]["repository"]["commit"] == github.repos["octo/immense"].commit
    events = api.get(f"/api/scans/{immense['scan']['id']}/events").text
    assert events.index('"kind":"cloning"') < events.index('"kind":"reading"')
    # Un package.json sans dépendance : rien n'est en retard.
    assert found["atelier/site"]["state"] == "up_to_date"
    synthesis = document["synthesis"]
    assert synthesis["analyzed"] == 5
    assert (synthesis["to_update"], synthesis["up_to_date"], synthesis["inconclusive"]) == (1, 3, 0)
    assert synthesis["no_dependencies"] == 1
    assert synthesis["skipped"] == 3
    assert (synthesis["vulnerabilities"], synthesis["vulnerable_repositories"]) == (28, 1)
    assert synthesis["findings"]["vulnerable"] == 28
    assert sum(synthesis["severities"].values()) == 30
    assert document["batch"]["id"] == batch["id"]

    # Le rapport d'un dépôt est celui d'un dossier, avec owner/nom pour source.
    detail = api.get(f"/api/scans/{vulnerable['scan']['id']}").json()
    assert detail["source"] == "octo/vulnerable"
    assert detail["report"]["source"] == "octo/vulnerable"
    assert detail["report"]["summary"]["vulnerabilities"]["high"] == 13
    # Un dépôt ne se met pas à jour par un plan local (ce sera une PR).
    response = api.post("/api/updates/plan", json={"scan": detail["id"], "selection": {}})
    assert response.status_code == 409
    assert "pull request" in response.json()["detail"]
    # La progression passe par le téléchargement des fichiers.
    text = api.get(f"/api/scans/{detail['id']}/events").text
    assert text.index('"kind":"downloading"') < text.index('"kind":"reading"')


def test_a_truncated_repository_that_cannot_be_cloned_stays_partial(
    api: TestClient,
    github: FakeGitHubRepos,
    finished: Finished,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(github_module, "GIT_URL", remotes_url(tmp_path / "nulle-part"))
    connect(api)
    api.get("/api/repositories")
    run_batch(api, finished, ["octo/immense"])
    immense = rows(api.get("/api/repositories").json())["octo/immense"]
    assert immense["state"] == "inconclusive"
    assert immense["reason"] == "arborescence tronquée par la forge : analyse partielle"
    assert immense["scan"]["repository"]["truncated"]
    assert not immense["scan"]["repository"]["cloned"]


def test_a_batch_refuses_what_it_cannot_do(api: TestClient, github: FakeGitHubRepos) -> None:
    def start(body: dict[str, Any]) -> Any:
        return api.post("/api/repositories/batches", json=body)

    response = start({"repositories": keys("octo/vulnerable")})
    assert response.status_code == 404
    assert response.json() == {"detail": "Aucun compte GitHub connecté."}
    connect(api)
    api.get("/api/repositories")
    response = start({"repositories": keys("octo/vulnerable", "octo/inconnu")})
    assert response.status_code == 400
    assert response.json()["detail"].startswith("octo/inconnu : pas dans la liste")
    assert start({"repositories": []}).status_code == 400
    response = start({"repositories": keys("a/b", forge="gitlab", host="gitlab.com")})
    assert response.status_code == 404
    assert response.json() == {"detail": "Aucun compte GitLab connecté."}
    response = start({"repositories": keys("a/b", forge="bitbucket", host="bitbucket.org")})
    assert response.status_code == 404
    assert response.json() == {"detail": "Aucun compte Bitbucket connecté."}


def test_a_token_refused_during_a_batch(
    api: TestClient, github: FakeGitHubRepos, finished: Finished
) -> None:
    accounts = connect(api)
    api.get("/api/repositories")
    github.tokens = set()  # révoqué sur github.com entre la liste et l'analyse
    batch = run_batch(api, finished, ["octo/a-jour"])
    assert batch["failed"] == 1
    row = rows(api.get("/api/repositories").json())["octo/a-jour"]
    assert row["state"] == "inconclusive"
    assert row["reason"].startswith("GitHub refuse le token (401)")
    assert accounts.get(ForgeKind.GITHUB, "github.com").problem is not None  # type: ignore[union-attr]


def test_cancel_a_batch(
    api: TestClient, github: FakeGitHubRepos, monkeypatch: pytest.MonkeyPatch
) -> None:
    connect(api)
    api.get("/api/repositories")
    blocked: list[str] = []
    original = github._dispatch

    def slow(request: Any) -> Any:
        if "/git/trees/" in request.url.path:
            blocked.append(request.url.path)
            time.sleep(0.5)
        return original(request)

    github._dispatch = slow  # type: ignore[method-assign]
    batch = api.post("/api/repositories/batches", json={"repositories": keys(*VISIBLE)}).json()
    response = api.delete(f"/api/repositories/batches/{batch['id']}")
    assert response.status_code == 200
    cancelled = response.json()
    assert cancelled["status"] == "cancelled"
    assert cancelled["finished"] == 5
    states = {api.get(f"/api/scans/{i}").json()["status"] for i in cancelled["scans"]}
    assert states == {"cancelled"}
    assert {row["state"] for row in rows(api.get("/api/repositories").json()).values()} <= {
        "not_scanned",
        "skipped",
    }
    assert api.get("/api/repositories/batches/inconnu").status_code == 404


def test_the_latest_scan_of_each_repository_is_never_forgotten(
    api: TestClient, github: FakeGitHubRepos, finished: Finished, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jobs_module, "MAX_SCANS", 0)
    connect(api)
    api.get("/api/repositories")
    first = run_batch(api, finished, VISIBLE)
    second = run_batch(api, finished, VISIBLE)
    jobs = api.app.state.jobs  # type: ignore[attr-defined]
    assert set(second["scans"]) <= set(jobs.scans)
    assert not set(first["scans"]) & set(jobs.scans)
    found = rows(api.get("/api/repositories").json())
    assert found["octo/vulnerable"]["scan"]["id"] in second["scans"]


# -- Un dépôt donné par son nom -----------------------------------------------------


def test_scan_a_public_repository_of_another_account(
    api: TestClient, github: FakeGitHubRepos, finished: Finished
) -> None:
    response = api.post(
        "/api/repositories/scans", json={"repository": "https://github.com/ailleurs/public"}
    )
    assert response.status_code == 202, response.text
    started = response.json()
    assert started["kind"] == "repository"
    assert started["source"] == "ailleurs/public"
    assert started["batch"] is None
    assert started["repository"]["url"] == "https://github.com/ailleurs/public"
    assert response.headers["location"] == f"/api/scans/{started['id']}"
    state = finished(f"/api/scans/{started['id']}")
    assert state["status"] == "done"
    assert state["summary"]["vulnerabilities"]["high"] > 0
    # Sans compte connecté, sans token.
    assert all("authorization" not in r.headers for r in github.requests)


def test_scan_a_repository_with_the_connected_account(
    api: TestClient, github: FakeGitHubRepos, finished: Finished
) -> None:
    connect(api)
    response = api.post("/api/repositories/scans", json={"repository": "octo/vulnerable"})
    assert response.status_code == 202
    finished(f"/api/scans/{response.json()['id']}")
    assert all(r.headers["authorization"] == f"Bearer {TOKEN}" for r in github.requests)
    # Sa dernière analyse est celle de la liste, même faite hors d'un lot.
    found = rows(api.get("/api/repositories").json())
    assert found["octo/vulnerable"]["scan"]["id"] == response.json()["id"]


@pytest.mark.parametrize(
    ("repository", "status", "detail"),
    [
        ("pas un/dépôt", 400, "n'est pas un nom de dépôt"),
        ("octo", 400, "donner owner/nom"),
        ("https://exemple.org/a/b", 400, "seuls GitHub, GitLab et Bitbucket"),
        ("https://bitbucket.org/espace", 400, "donner owner/nom"),
        ("https://gitlab.example.com/a/b", 400, "et les instances GitLab connectées"),
        ("octo/vulnerable", 404, "privé et sans compte connecté, on n'y a pas accès"),
        ("octo/inconnu", 404, "Dépôt introuvable sur GitHub : octo/inconnu n'existe pas"),
        ("octo/neuf", 409, "octo/neuf est vide : rien à analyser."),
    ],
)
def test_scan_a_repository_refused(
    api: TestClient, github: FakeGitHubRepos, repository: str, status: int, detail: str
) -> None:
    response = api.post("/api/repositories/scans", json={"repository": repository})
    assert response.status_code == status
    assert detail in response.json()["detail"]


def test_scan_a_repository_when_github_does_not_answer(
    api: TestClient, github: FakeGitHubRepos
) -> None:
    github.down = True
    response = api.post("/api/repositories/scans", json={"repository": "octo/a-jour"})
    assert response.status_code == 502
    assert response.json()["detail"].startswith("GitHub ne répond pas")


# -- Le schéma ----------------------------------------------------------------------


def test_responses_follow_the_exported_schema(
    api: TestClient, github: FakeGitHubRepos, finished: Finished
) -> None:
    from test_web_server import conforms

    schema = json.loads(openapi.OPENAPI_JSON.read_text(encoding="utf-8"))
    components = schema["components"]["schemas"]

    def check(value: Any, name: str) -> None:
        assert conforms(value, {"$ref": f"#/components/schemas/{name}"}, components) == []

    check(api.get("/api/repositories").json(), "RepositoryList")
    connect(api)
    check(api.get("/api/repositories").json(), "RepositoryList")
    batch = api.post("/api/repositories/batches", json={"repositories": keys(*VISIBLE)}).json()
    check(batch, "RepositoryBatch")
    for scan_id in batch["scans"]:
        check(finished(f"/api/scans/{scan_id}"), "ScanDetail")
    check(api.get("/api/repositories").json(), "RepositoryList")
    check(api.get(f"/api/repositories/batches/{batch['id']}").json(), "RepositoryBatch")
    check(api.delete(f"/api/repositories/batches/{batch['id']}").json(), "RepositoryBatch")
    started = api.post("/api/repositories/scans", json={"repository": "ailleurs/public"}).json()
    check(started, "ScanSummary")
    check(api.get("/api/scans").json()[0], "ScanSummary")
    assert datetime.fromisoformat(started["started_at"]).tzinfo == UTC
