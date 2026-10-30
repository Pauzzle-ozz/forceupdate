"""L'API des PR (``web.routes.proposals``, ``web.proposals``) : le récapitulatif (ce que chaque
PR fera, les dépôts sautés et pourquoi, rien de poussé), l'envoi validé dépôt par dépôt, la PR
ouverte puis mise à jour en relançant, la colonne et le compteur des PR de l'écran 7.

GitHub est simulé (``fake_forge``) ; git clone et pousse vers des dépôts « bare » du dossier du
test ; npm et uv sont simulés (``FakeTools``) ; les registres et OSV répondent avec les réponses
enregistrées ; le trousseau est en mémoire."""

import json
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import FakeTools, recorded_responses
from fake_forge import (
    FakeGitHubRepos,
    FakePull,
    FakeRepo,
    from_directory,
    git,
    make_remote,
    push_commit,
    remotes_url,
)
from fastapi.testclient import TestClient
from test_update_forge import tools
from test_web_repositories import Finished, connect, rows, run_batch

from forceupdate.forges import git as forge_git
from forceupdate.forges import github as github_module
from forceupdate.net import http as http_module
from forceupdate.update.forge import BRANCH
from forceupdate.web import openapi

PROJECTS = Path(__file__).parent / "projects"
TOKEN = "gho_depots"

pytestmark = pytest.mark.skipif(not forge_git.available(), reason="git n'est pas installé")


def repos() -> list[FakeRepo]:
    return [
        from_directory("octo/vulnerable", PROJECTS / "vulnerable", private=True),
        FakeRepo(full_name="octo/a-jour", files={"requirements.txt": b"werkzeug==3.1.9\n"}),
        FakeRepo(full_name="octo/docs", files={"README.md": b"# docs\n"}),
        FakeRepo(full_name="octo/muet", files={"requirements.txt": b"muet==1.0\nflask==0.12\n"}),
        FakeRepo(full_name="octo/ancien", archived=True, files={"requirements.txt": b"flask\n"}),
        FakeRepo(full_name="octo/neuf", empty=True),
        FakeRepo(full_name="atelier/site", push=False, files={"requirements.txt": b"flask\n"}),
    ]


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[FakeGitHubRepos]:
    monkeypatch.setattr(http_module, "_backoff", lambda attempt: 0.0)
    fake = FakeGitHubRepos(
        repos(), tokens={TOKEN}, user={"login": "octo", "id": 583231, "name": "Octo Cat"}
    )
    remotes = tmp_path / "distants"
    for repo in fake.repos.values():
        if not repo.empty:
            make_remote(repo, remotes)
    monkeypatch.setattr(github_module, "GIT_URL", remotes_url(remotes))

    def routes(router: Any) -> None:
        # PyPI en panne pour un paquet : l'analyse de octo/muet n'est pas concluante.
        router.get("https://pypi.org/simple/muet/").respond(503)
        fake.routes(router)

    with recorded_responses(extra=routes):
        yield fake


@pytest.fixture
def analyzed(api: TestClient, github: FakeGitHubRepos, finished: Finished) -> None:
    connect(api)
    api.get("/api/repositories")
    run_batch(api, finished, ["octo/vulnerable", "octo/a-jour", "octo/docs", "octo/muet"])


@pytest.fixture
def npm_uv(fake_tools: Callable[..., FakeTools]) -> FakeTools:
    return tools(fake_tools, "npm", "uv")


def propose(api: TestClient, *names: str, **selections: dict[str, str]) -> dict[str, Any]:
    wanted = [{**key(name), "selection": selections.get(name)} for name in names]
    response = api.post("/api/proposals", json={"repositories": wanted})
    assert response.status_code == 201, response.text
    assert response.headers["location"] == f"/api/proposals/{response.json()['id']}"
    return response.json()


def key(name: str, forge: str = "github", host: str = "github.com") -> dict[str, str]:
    """Un dépôt d'un compte, comme le désigne l'API."""
    return {"forge": forge, "host": host, "full_name": name}


def items(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["full_name"]: item for item in document["repositories"]}


def sent(api: TestClient, proposal: str, *names: str) -> dict[str, Any]:
    """Envoie, puis attend (20 s au plus) la fin de l'envoi."""
    body = {"repositories": [key(name) for name in names]}
    response = api.post(f"/api/proposals/{proposal}/send", json=body)
    assert response.status_code == 202, response.text
    deadline = time.monotonic() + 20
    while True:
        document: dict[str, Any] = api.get(f"/api/proposals/{proposal}").json()
        if document["status"] == "done":
            return document
        assert time.monotonic() < deadline, "l'envoi tourne encore"
        time.sleep(0.05)


def test_the_proposal_says_what_each_request_will_do(
    api: TestClient, github: FakeGitHubRepos, analyzed: None, npm_uv: FakeTools
) -> None:
    document = propose(
        api,
        "octo/vulnerable",
        "octo/a-jour",
        "octo/docs",
        "octo/muet",
        "octo/ancien",
        "octo/neuf",
        "atelier/site",
    )
    assert document["status"] == "planned"
    assert (document["ready"], document["existing"]) == (2, 0)
    found = items(document)
    vulnerable = found["octo/vulnerable"]
    assert (vulnerable["state"], vulnerable["checked"], vulnerable["request"]) == (
        "ready",
        True,
        None,
    )
    assert (vulnerable["branch"], vulnerable["default_branch"]) == (BRANCH, "main")
    assert vulnerable["commit"] == github.repos["octo/vulnerable"].commit
    assert len(vulnerable["selection"]) == 3
    assert [f["path"] for f in vulnerable["files"]] == ["package.json", "requirements.in"]
    assert [(j["lockfile"], j["available"]) for j in vulnerable["lockfiles"]] == [
        ("package-lock.json", True),
        ("requirements.txt", True),
    ]
    muet = found["octo/muet"]
    assert (muet["state"], muet["inconclusive"], muet["checked"]) == ("ready", True, False)
    reasons = {name: item["reason"] for name, item in found.items() if item["state"] == "skipped"}
    assert reasons == {
        "octo/a-jour": "aucune mise à jour cochée",
        "octo/docs": "aucune mise à jour cochée",
        "octo/ancien": "archivé : lecture seule",
        "octo/neuf": "vide",
        "atelier/site": "lecture seule : pas de droit de push",
    }
    # Rien n'est poussé ni ouvert tant que ce n'est pas envoyé.
    remote = github.repos["octo/vulnerable"].remote
    assert remote is not None
    assert not git(remote, "branch", "--list", BRANCH).strip()
    assert github.repos["octo/vulnerable"].pulls == []
    assert npm_uv.calls == []


def test_send_opens_then_relaunching_updates_the_same_request(
    api: TestClient, github: FakeGitHubRepos, analyzed: None, npm_uv: FakeTools
) -> None:
    proposal = propose(api, "octo/vulnerable", "octo/muet")
    done = sent(api, proposal["id"], "octo/vulnerable")
    found = items(done)
    vulnerable = found["octo/vulnerable"]
    assert vulnerable["state"] == "opened", vulnerable["error"]
    assert vulnerable["request"]["number"] == 41
    assert vulnerable["request"]["url"] == "https://github.com/octo/vulnerable/pull/41"
    assert vulnerable["pushed"]
    assert vulnerable["base"] == github.repos["octo/vulnerable"].commit
    assert [r["status"] for r in vulnerable["results"]] == ["regenerated", "regenerated"]
    assert sorted(vulnerable["committed"]) == [
        "package-lock.json",
        "package.json",
        "requirements.in",
        "requirements.txt",
    ]
    assert (vulnerable["step"], vulnerable["error"]) == (None, None)
    # Pas coché à l'envoi : rien.
    assert (found["octo/muet"]["state"], found["octo/muet"]["reason"]) == (
        "skipped",
        "pas coché à l'envoi",
    )
    assert github.repos["octo/muet"].pulls == []
    # L'auteur du commit : le compte du token.
    remote = github.repos["octo/vulnerable"].remote
    assert remote is not None
    assert git(remote, "log", "-1", "--format=%an <%ae>", BRANCH).strip() == (
        "Octo Cat <583231+octo@users.noreply.github.com>"
    )
    # L'écran 7 voit la PR.
    listing = api.get("/api/repositories").json()
    assert rows(listing)["octo/vulnerable"]["request"]["number"] == 41
    assert listing["synthesis"]["open_requests"] == 1

    # Relancer : la PR existante est dite, puis mise à jour, jamais doublée.
    again = propose(api, "octo/vulnerable")
    assert again["existing"] == 1
    assert items(again)["octo/vulnerable"]["request"]["number"] == 41
    updated = items(sent(api, again["id"], "octo/vulnerable"))["octo/vulnerable"]
    assert updated["state"] == "updated", updated["error"]
    assert updated["request"]["number"] == 41
    assert not updated["pushed"]  # même contenu : rien n'est poussé
    assert len(github.repos["octo/vulnerable"].pulls) == 1


def test_a_modified_selection(
    api: TestClient, github: FakeGitHubRepos, analyzed: None, npm_uv: FakeTools
) -> None:
    first = items(propose(api, "octo/vulnerable"))["octo/vulnerable"]
    lodash = next(update for update in first["selection"] if "lodash" in update)
    only = {lodash: first["selection"][lodash]}
    chosen = items(propose(api, "octo/vulnerable", **{"octo/vulnerable": only}))
    assert chosen["octo/vulnerable"]["selection"] == only
    assert [f["path"] for f in chosen["octo/vulnerable"]["files"]] == ["package.json"]
    response = api.post(
        "/api/proposals",
        json={
            "repositories": [{**key("octo/vulnerable"), "selection": {"x|npm|y": "1.0"}}],
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"].startswith("octo/vulnerable : Mise à jour inconnue")
    nothing = items(propose(api, "octo/vulnerable", **{"octo/vulnerable": {}}))
    assert nothing["octo/vulnerable"]["reason"] == "aucune mise à jour cochée"


def test_what_cannot_be_proposed_or_sent(
    api: TestClient,
    github: FakeGitHubRepos,
    analyzed: None,
    npm_uv: FakeTools,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refused(body: dict[str, Any], status: int, text: str) -> None:
        response = api.post("/api/proposals", json=body)
        assert response.status_code == status, response.text
        assert text in response.json()["detail"]

    refused({"repositories": []}, 400, "Aucun dépôt")
    refused({"repositories": [key("x/y")]}, 400, "pas dans la liste")
    refused({"repositories": [key("x/y", "gitlab", "gitlab.com")]}, 404, "Aucun compte GitLab")
    refused(
        {"repositories": [key("x/y", "bitbucket", "bitbucket.org")]}, 404, "Aucun compte Bitbucket"
    )
    assert api.get("/api/proposals/inconnu").status_code == 404
    assert api.post("/api/proposals/inconnu/send", json={"repositories": []}).status_code == 404

    proposal = propose(api, "octo/vulnerable", "octo/a-jour")
    url = f"/api/proposals/{proposal['id']}/send"
    for names, status in ((["octo/a-jour"], 400), ([], 400), (["autre/depot"], 400)):
        body = {"repositories": [key(name) for name in names]}
        assert api.post(url, json=body).status_code == status
    gitlab_one = {"repositories": [key("octo/vulnerable", "gitlab", "gitlab.com")]}
    assert api.post(url, json=gitlab_one).status_code == 400  # pas le même dépôt
    with monkeypatch.context() as patched:  # git absent, le temps d'une requête
        patched.setattr(forge_git, "_which", lambda program: None)
        response = api.post(url, json={"repositories": [key("octo/vulnerable")]})
    assert response.status_code == 409
    assert "git n'est pas installé" in response.json()["detail"]
    sent(api, proposal["id"], "octo/vulnerable")
    again = api.post(url, json={"repositories": [key("octo/vulnerable")]})
    assert again.status_code == 409


def test_a_failing_repository_does_not_stop_the_others(
    api: TestClient,
    github: FakeGitHubRepos,
    analyzed: None,
    fake_tools: Callable[..., FakeTools],
) -> None:
    tools(fake_tools, "npm", "uv")
    proposal = propose(api, "octo/muet", "octo/vulnerable")
    github.repos["octo/muet"].push = False  # GitHub refuse la PR (403)
    done = items(sent(api, proposal["id"], "octo/muet", "octo/vulnerable"))
    assert done["octo/muet"]["state"] == "failed"
    assert "GitHub refuse l'accès (403)" in done["octo/muet"]["error"]
    assert done["octo/vulnerable"]["state"] == "opened"


def test_files_changed_since_the_analysis_are_left_out(
    api: TestClient, github: FakeGitHubRepos, analyzed: None, npm_uv: FakeTools
) -> None:
    proposal = propose(api, "octo/vulnerable")
    # Entre-temps, lodash et flask ont été montés à la main sur la branche par défaut.
    repo = github.repos["octo/vulnerable"]
    package = json.loads(repo.files["package.json"])
    package["dependencies"]["lodash"] = "^4.18.1"
    requirements = repo.files["requirements.in"].decode().replace("flask==0.12", "flask==0.12.5")
    push_commit(
        repo,
        "main",
        {"package.json": json.dumps(package, indent=2) + "\n", "requirements.in": requirements},
        "Mise à jour à la main",
    )
    done = items(sent(api, proposal["id"], "octo/vulnerable"))["octo/vulnerable"]
    # Le clone est préparé de nouveau : ce qui a changé est sauté, avec la raison.
    assert done["state"] == "opened", done["error"]
    assert {item["update"] for item in done["skipped"]} == {".|npm|lodash", ".|PyPI|flask"}
    assert "a changé depuis l'analyse" in done["skipped"][0]["reason"]
    assert done["applied"] == [
        {
            "update": ".|PyPI|jinja2|2.10",
            "name": "jinja2",
            "ecosystem": "PyPI",
            "project": ".",
            "direct": False,
            "current": "2.10",
            "version": "2.11.3",
            "gap": "minor",
            "fixes": ["CVE-2019-10906", "CVE-2020-28493"],
        }
    ]
    assert done["committed"] == ["requirements.txt"]
    assert done["base"] == repo.commit
    assert "## Non appliquées" in github.pull("octo/vulnerable").body


def test_nothing_left_to_do_pushes_nothing(
    api: TestClient, github: FakeGitHubRepos, analyzed: None, npm_uv: FakeTools
) -> None:
    first = items(propose(api, "octo/vulnerable"))["octo/vulnerable"]
    lodash = {".|npm|lodash": first["selection"][".|npm|lodash"]}
    proposal = propose(api, "octo/vulnerable", **{"octo/vulnerable": lodash})
    repo = github.repos["octo/vulnerable"]
    package = json.loads(repo.files["package.json"])
    package["dependencies"]["lodash"] = "^4.18.1"
    push_commit(repo, "main", {"package.json": json.dumps(package, indent=2) + "\n"}, "À la main")
    done = items(sent(api, proposal["id"], "octo/vulnerable"))["octo/vulnerable"]
    assert done["state"] == "nothing", done["error"]
    assert not done["pushed"]
    assert repo.pulls == []
    assert repo.remote is not None
    assert not git(repo.remote, "branch", "--list", BRANCH).strip()


def test_a_token_refused_when_sending(
    api: TestClient, github: FakeGitHubRepos, analyzed: None, npm_uv: FakeTools
) -> None:
    proposal = propose(api, "octo/vulnerable")
    github.tokens = {"autre"}  # révoqué sur github.com
    done = sent(api, proposal["id"], "octo/vulnerable")
    assert done["error"] is None  # un compte refusé n'arrête pas ceux des autres comptes
    assert items(done)["octo/vulnerable"]["state"] == "failed"
    assert "refuse le token" in (items(done)["octo/vulnerable"]["error"] or "")
    accounts = api.get("/api/accounts").json()
    github_account = next(f for f in accounts["forges"] if f["forge"] == "github")["account"]
    assert "refuse le token" in (github_account["problem"] or "")


def test_the_analysis_finds_the_open_request(
    api: TestClient, github: FakeGitHubRepos, finished: Finished
) -> None:
    github.repos["octo/vulnerable"].pulls.append(
        FakePull(number=12, title="t", body="b", head=BRANCH, base="main")
    )
    connect(api)
    api.get("/api/repositories")
    run_batch(api, finished, ["octo/vulnerable", "octo/a-jour"])
    listing = api.get("/api/repositories").json()
    found = rows(listing)
    assert found["octo/vulnerable"]["request"]["number"] == 12
    assert found["octo/a-jour"]["request"] is None
    assert listing["synthesis"]["open_requests"] == 1
    # Un dépôt en lecture seule : la PR n'est pas cherchée.
    asked = [r.url.path for r in github.requests if r.url.path.endswith("/pulls")]
    assert sorted(asked) == ["/repos/octo/a-jour/pulls", "/repos/octo/vulnerable/pulls"]


def test_responses_follow_the_exported_schema(
    api: TestClient, github: FakeGitHubRepos, analyzed: None, npm_uv: FakeTools
) -> None:
    from test_web_server import conforms

    schema = json.loads(openapi.OPENAPI_JSON.read_text(encoding="utf-8"))
    components = schema["components"]["schemas"]

    def check(value: Any, name: str) -> None:
        assert conforms(value, {"$ref": f"#/components/schemas/{name}"}, components) == []

    proposal = propose(api, "octo/vulnerable", "octo/a-jour", "octo/muet")
    check(proposal, "Proposal")
    response = api.post(
        f"/api/proposals/{proposal['id']}/send", json={"repositories": [key("octo/vulnerable")]}
    )
    check(response.json(), "Proposal")
    check(api.get(f"/api/proposals/{proposal['id']}").json(), "Proposal")
    check(sent_document(api, proposal["id"]), "Proposal")
    check(api.get("/api/repositories").json(), "RepositoryList")


def sent_document(api: TestClient, proposal: str) -> dict[str, Any]:
    deadline = time.monotonic() + 20
    while True:
        document: dict[str, Any] = api.get(f"/api/proposals/{proposal}").json()
        if document["status"] == "done":
            return document
        assert time.monotonic() < deadline
        time.sleep(0.05)
