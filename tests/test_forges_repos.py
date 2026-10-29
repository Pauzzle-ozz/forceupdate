"""Les dépôts d'une forge (E17) : la liste et ses drapeaux, un dépôt par son nom, les
organisations qui restreignent l'accès, l'arborescence et les fichiers (``forges.github``), et
la lecture d'un dépôt donné par son nom ou son adresse (``forges.parse_repository``). GitHub est
simulé par ``fake_forge.FakeGitHubRepos``."""

import asyncio
import copy
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime
from typing import Any, TypeVar

import pytest
import respx
from fake_forge import FakeGitHubRepos, FakeRepo

from forceupdate.forges import ForgeKind, parse_repository
from forceupdate.forges.base import (
    AppRestricted,
    EmptyRepository,
    NotFound,
    RestrictionKind,
    SsoRequired,
    TokenRefused,
)
from forceupdate.forges.github import APPLICATIONS_URL, GitHub
from forceupdate.net import HttpClient

T = TypeVar("T")
TOKEN = "gho_depots"

REPOS = [
    FakeRepo(
        full_name="octo/app",
        files={"package.json": b"{}", "src/index.js": b"x"},
        language="JavaScript",
        private=True,
    ),
    FakeRepo(full_name="octo/ancien", archived=True),
    FakeRepo(full_name="octo/copie", fork=True, push=False),
    FakeRepo(full_name="octo/neuf", empty=True),
    FakeRepo(full_name="octo/petit", files={"README.md": b"x"}, size=0),
    FakeRepo(full_name="atelier/api", push=False, files={"pyproject.toml": b""}),
]


async def _no_sleep(_: float) -> None:
    pass


@pytest.fixture
def github() -> Iterator[FakeGitHubRepos]:
    fake = FakeGitHubRepos(copy.deepcopy(REPOS), tokens={TOKEN}, page_size=2)
    with respx.mock(assert_all_called=False) as router:
        fake.routes(router)
        yield fake


def run(work: Callable[[GitHub], Awaitable[T]], token: str | None = TOKEN) -> T:
    async def main() -> T:
        async with HttpClient(sleep=_no_sleep) as http:
            return await work(GitHub(http, token))

    return asyncio.run(main())


# -- La liste -----------------------------------------------------------------------


def test_list_repos_reads_every_page_and_the_flags(github: FakeGitHubRepos) -> None:
    repos = run(lambda forge: forge.list_repos())
    assert [repo.full_name for repo in repos] == [r.full_name for r in REPOS]
    app = repos[0]
    assert (app.forge, app.host, app.owner, app.name) == (
        ForgeKind.GITHUB,
        "github.com",
        "octo",
        "app",
    )
    assert (app.private, app.archived, app.fork, app.empty, app.can_push) == (
        True,
        False,
        False,
        False,
        True,
    )
    assert app.default_branch == "main"
    assert app.language == "JavaScript"
    assert app.pushed_at == datetime(2026, 10, 20, 10, 0, tzinfo=UTC)
    assert app.url == "https://github.com/octo/app"
    assert app.clone_url == "https://github.com/octo/app.git"
    flags = {repo.name: (repo.archived, repo.fork, repo.empty, repo.can_push) for repo in repos}
    assert flags["ancien"] == (True, False, False, True)
    assert flags["copie"] == (False, True, False, False)
    assert flags["api"] == (False, False, False, False)
    # Taille nulle : vérifié un par un (« petit » a un commit, « neuf » aucun).
    assert flags["neuf"][2] is True
    assert repos[3].default_branch is None
    assert flags["petit"][2] is False
    pages = [r for r in github.requests if r.url.path == "/user/repos"]
    assert len(pages) == 3
    assert pages[0].url.params["affiliation"] == "owner,collaborator,organization_member"
    checked = [r.url.path for r in github.requests if r.url.path.endswith("/commits")]
    assert sorted(checked) == ["/repos/octo/neuf/commits", "/repos/octo/petit/commits"]


def test_the_requests_sent_and_remaining_are_counted(github: FakeGitHubRepos) -> None:
    async def work(forge: GitHub) -> tuple[int, Any]:
        await forge.list_repos()
        return forge.requests, forge.rate_limit

    sent, rate = run(work)
    assert sent == len(github.requests) == 5
    assert (rate.limit, rate.remaining) == (5000, 4995)


def test_a_refused_token_while_listing(github: FakeGitHubRepos) -> None:
    with pytest.raises(TokenRefused):
        run(lambda forge: forge.list_repos(), token="gho_revoque")


def test_repository_by_name(github: FakeGitHubRepos) -> None:
    repo = run(lambda forge: forge.repository("Octo/App"))
    assert repo.full_name == "octo/app"
    assert repo.can_push is True
    with pytest.raises(NotFound):
        run(lambda forge: forge.repository("octo/inconnu"))
    assert run(lambda forge: forge.repository("octo/neuf")).empty is True


def test_without_a_token_only_public_repositories_are_seen(github: FakeGitHubRepos) -> None:
    repo = run(lambda forge: forge.repository("atelier/api"), token=None)
    assert repo.can_push is False  # pas de droits sans compte
    assert "authorization" not in github.requests[-1].headers
    with pytest.raises(NotFound):
        run(lambda forge: forge.repository("octo/app"), token=None)  # privé : 404


# -- Organisations ------------------------------------------------------------------


def test_restrictions_of_the_organizations(github: FakeGitHubRepos) -> None:
    github.organizations = {"atelier": "ok", "nord": "restricted", "acme": "sso", "vide": "gone"}
    found = run(lambda forge: forge.restrictions())
    assert [(r.organization, r.kind, r.url) for r in found] == [
        ("nord", RestrictionKind.APP_ACCESS, APPLICATIONS_URL),
        ("acme", RestrictionKind.SSO, "https://github.com/orgs/acme/sso"),
    ]


def test_without_read_org_no_restriction_is_known(github: FakeGitHubRepos) -> None:
    github.organizations = {"nord": "restricted"}
    github.orgs_scope = False
    assert run(lambda forge: forge.restrictions()) == []


def test_restricted_and_sso_errors(github: FakeGitHubRepos) -> None:
    github.organizations = {"nord": "restricted", "acme": "sso"}
    with pytest.raises(AppRestricted, match="restreint l'accès des applications OAuth"):
        run(lambda forge: forge.request("GET", "/orgs/nord/repos"))
    with pytest.raises(SsoRequired) as caught:
        run(lambda forge: forge.request("GET", "/orgs/acme/repos"))
    assert caught.value.url == "https://github.com/orgs/acme/sso"


# -- Arborescence et fichiers -------------------------------------------------------


def test_tree_reads_the_commit_then_its_tree(github: FakeGitHubRepos) -> None:
    github.repos["octo/app"].symlinks = ("lien",)
    github.repos["octo/app"].submodules = ("vendor/lib",)

    async def work(forge: GitHub) -> Any:
        return await forge.tree(await forge.repository("octo/app"))

    tree = run(work)
    assert tree.commit == REPOS[0].commit
    assert [(e.path, e.size) for e in tree.entries] == [("package.json", 2), ("src/index.js", 1)]
    assert tree.truncated is False
    paths = [r.url.path for r in github.requests]
    assert paths[-2:] == [
        "/repos/octo/app/commits/main",
        f"/repos/octo/app/git/trees/{tree.commit}",
    ]


def test_a_truncated_tree_is_said(github: FakeGitHubRepos) -> None:
    github.repos["octo/app"].truncated = True

    async def work(forge: GitHub) -> Any:
        return await forge.tree(await forge.repository("octo/app"))

    assert run(work).truncated is True


def test_an_empty_repository_has_no_tree(github: FakeGitHubRepos) -> None:
    async def listed_empty(forge: GitHub) -> Any:
        return await forge.tree(await forge.repository("octo/neuf"))

    with pytest.raises(EmptyRepository, match="Dépôt vide"):
        run(listed_empty)

    async def became_empty(forge: GitHub) -> Any:
        repo = await forge.repository("octo/app")
        github.repos["octo/app"].empty = True  # vidé entre la liste et l'analyse : 409
        return await forge.tree(repo)

    with pytest.raises(EmptyRepository, match="Dépôt vide"):
        run(became_empty)
    assert github.requests[-1].url.path == "/repos/octo/app/commits/main"


def test_read_file_gets_the_raw_content_at_the_commit(github: FakeGitHubRepos) -> None:
    github.repos["octo/app"].files["dossier avec espace/package.json"] = b'{"name": "x"}'

    async def work(forge: GitHub) -> tuple[Any, Any]:
        repo = await forge.repository("octo/app")
        tree = await forge.tree(repo)
        found = await forge.read_file(repo, "dossier avec espace/package.json", tree.commit)
        missing = await forge.read_file(repo, "absent.txt", tree.commit)
        return found, missing

    found, missing = run(work)
    assert found == b'{"name": "x"}'
    assert missing is None
    request = github.requests[-2]
    assert request.url.raw_path.startswith(b"/repos/octo/app/contents/dossier%20avec%20espace/")
    assert request.headers["accept"] == "application/vnd.github.raw"


# -- Un dépôt donné par la personne -------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "octo/app",
        "  octo/app  ",
        "github.com/octo/app",
        "https://github.com/octo/app",
        "https://www.github.com/octo/app/",
        "https://github.com/octo/app.git",
        "https://github.com/octo/app/tree/main/src",
        "git@github.com:octo/app.git",
        "HTTPS://GitHub.com/octo/app",
    ],
)
def test_parse_repository(text: str) -> None:
    forge, name = parse_repository(text)
    assert (forge.kind, name) == (ForgeKind.GITHUB, "octo/app")


def test_parse_repository_knows_the_other_forges() -> None:
    assert parse_repository("https://gitlab.com/groupe/projet")[0].kind is ForgeKind.GITLAB
    assert parse_repository("bitbucket.org/espace/depot")[0].kind is ForgeKind.BITBUCKET


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "donner owner/nom"),
        ("octo", "donner owner/nom"),
        ("https://exemple.org/octo/app", "seuls GitHub, GitLab et Bitbucket"),
        ("ftp://github.com/octo/app", "l'adresse https"),
        ("octo/../x", "n'est pas un nom de dépôt"),
        ("-octo/app", "n'est pas un nom de dépôt"),
        ("octo/app?x=1", "n'est pas un nom de dépôt"),
    ],
)
def test_parse_repository_refuses(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_repository(text)
