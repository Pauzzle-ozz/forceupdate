"""La mise à jour d'un dépôt par une PR, de bout en bout (``update.forge.deliver``) : clone,
réécriture et lockfiles sur le clone, commit au nom du compte, push de
``forceupdate/dependencies``, PR ouverte puis mise à jour (jamais une deuxième), rien de poussé
quand il n'y a rien à faire ou que la branche a des commits d'un autre.

GitHub est simulé (``fake_forge``), git pousse vers un dépôt « bare » du dossier du test, npm et
uv sont simulés (``FakeTools``, avec ce que font ceux du serveur de bout en bout), les registres
et OSV répondent avec les réponses enregistrées."""

import asyncio
import dataclasses
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import e2e_server
import pytest
from conftest import FakeTools, ToolCall, recorded_responses
from fake_forge import FakeGitHubRepos, from_directory, git, make_remote, push_commit, remotes_url

from forceupdate import engine
from forceupdate.forges import git as forge_git
from forceupdate.forges.base import Access, BranchCommit, ForgeKind, Identity, Repository
from forceupdate.forges.github import GitHub
from forceupdate.models import Report
from forceupdate.net import HttpClient
from forceupdate.sources.local import LocalSource
from forceupdate.update import forge, local, planner
from forceupdate.update.forge import BRANCH, Delivered, Outcome, Step
from forceupdate.update.lockfiles import LockStatus

VULNERABLE = Path(__file__).parent / "projects" / "vulnerable"
TOKEN = "gho_pr"
NAME = "octo/vulnerable"

AUTHOR = Identity(
    forge=ForgeKind.GITHUB,
    host="github.com",
    login="octo",
    name="Octo Cat",
    url="https://github.com/octo",
    access=Access.WRITE,
    scopes=("repo",),
    warnings=(),
    email="583231+octo@users.noreply.github.com",
)

pytestmark = pytest.mark.skipif(not forge_git.available(), reason="git n'est pas installé")


@pytest.fixture
def remotes(tmp_path: Path) -> Path:
    return tmp_path / "distants"


@pytest.fixture
def github(remotes: Path) -> Iterator[FakeGitHubRepos]:
    repo = from_directory(NAME, VULNERABLE, private=True)
    make_remote(repo, remotes)
    fake = FakeGitHubRepos([repo], tokens={TOKEN})
    with recorded_responses(extra=fake.routes):
        yield fake


@pytest.fixture
def report(tmp_path: Path, github: FakeGitHubRepos) -> Report:
    """L'analyse du dépôt : celle d'une copie de ses fichiers (les chemins sont les mêmes)."""
    copy = tmp_path / "analyse"
    shutil.copytree(VULNERABLE, copy)
    found = engine.scan(LocalSource(copy))
    found.source = NAME  # comme une analyse par l'API
    return found


def tools(fake_tools: Callable[..., FakeTools], *programs: str) -> FakeTools:
    """npm et uv simulés comme dans le serveur de bout en bout : ils écrivent dans le lockfile
    les versions que leur commande demande."""
    found = fake_tools(*programs)
    found.handlers["npm"] = lambda call: e2e_server._npm(call.cwd)

    def uv(call: ToolCall) -> None:
        output = call.arguments[call.arguments.index("-o") + 1]
        e2e_server._uv(call.cwd / output, call.arguments)

    found.handlers["uv"] = uv
    return found


class Run:
    """``deliver`` sur le faux GitHub, avec ce qu'il a annoncé."""

    def __init__(self, remotes: Path, workdir: Path, token: str = TOKEN) -> None:
        self.remotes = remotes
        self.workdir = workdir
        self.token = token
        self.steps: list[Step] = []
        self.count = 0

    def repository(self, name: str = NAME) -> Repository:
        return asyncio.run(self._with(lambda github: github.repository(name)))

    def __call__(
        self,
        report: Report,
        selection: planner.Selection | None = None,
        *,
        repo: Repository | None = None,
        author: Identity = AUTHOR,
    ) -> Delivered:
        self.count += 1
        workdir = self.workdir / f"envoi-{self.count}"
        workdir.mkdir(parents=True)
        target = repo or self.repository()
        chosen = planner.select(report) if selection is None else selection
        return asyncio.run(
            self._with(
                lambda github: forge.deliver(
                    github,
                    target,
                    report,
                    chosen,
                    author=author,
                    workdir=workdir,
                    on_step=self.steps.append,
                )
            )
        )

    async def _with(self, work: Callable[[GitHub], Any]) -> Any:
        async with HttpClient() as http:
            return await work(GitHub(http, self.token, git_url=remotes_url(self.remotes)))


@pytest.fixture
def deliver(remotes: Path, tmp_path: Path) -> Run:
    return Run(remotes, tmp_path / "travail")


def branch_files(github: FakeGitHubRepos) -> list[str]:
    remote = github.repos[NAME].remote
    assert remote is not None
    return git(remote, "diff", "--name-only", "main", BRANCH).split()


def test_a_request_is_opened_with_the_updates(
    github: FakeGitHubRepos,
    report: Report,
    deliver: Run,
    fake_tools: Callable[..., FakeTools],
) -> None:
    tools(fake_tools, "npm", "uv")
    done = deliver(report)
    assert done.outcome is Outcome.OPENED, done.error
    assert done.pushed
    assert done.request is not None and done.request.number == 41
    assert deliver.steps == [Step.CLONING, Step.UPDATING, Step.PUSHING, Step.REQUESTING]
    assert [r.status for r in done.results] == [LockStatus.REGENERATED] * 2
    assert sorted(done.committed) == [
        "package-lock.json",
        "package.json",
        "requirements.in",
        "requirements.txt",
    ]
    assert branch_files(github) == sorted(done.committed)
    remote = github.repos[NAME].remote
    assert remote is not None
    # Un commit, au nom du compte, sur la branche par défaut telle qu'elle est.
    assert git(remote, "rev-list", "--count", f"main..{BRANCH}").strip() == "1"
    assert git(remote, "log", "-1", "--format=%an <%ae>", BRANCH).strip() == (
        "Octo Cat <583231+octo@users.noreply.github.com>"
    )
    message = git(remote, "log", "-1", "--format=%B", BRANCH)
    assert message.startswith(
        "Mise à jour des dépendances\n\n"
        "- flask 0.12 → 0.12.5\n- jinja2 2.10 → 2.11.3\n- lodash 4.17.15 → 4.18.1\n\n"
    )
    assert "Generated-by: forceupdate" in message
    assert done.base == github.repos[NAME].commit
    lock = git(remote, "show", f"{BRANCH}:package-lock.json")
    assert '"version": "4.18.1"' in lock
    pull = github.pull(NAME)
    assert pull.title == forge.TITLE
    assert "| `lodash` | `.` | 4.17.15 → 4.18.1 |" in pull.body
    assert "`package-lock.json` : régénéré par npm." in pull.body
    assert "## Rapport de l'analyse" in pull.body
    assert "### Projet `.`" in pull.body  # les titres du rapport, un niveau plus bas
    # Le dossier de travail est à l'appelant ; le token n'est nulle part dans le clone.
    config = (deliver.workdir / "envoi-1" / "depot" / ".git" / "config").read_text()
    assert TOKEN not in config


def test_relaunching_updates_the_same_request(
    github: FakeGitHubRepos,
    report: Report,
    deliver: Run,
    fake_tools: Callable[..., FakeTools],
) -> None:
    tools(fake_tools, "npm", "uv")
    first = deliver(report)
    remote = github.repos[NAME].remote
    assert remote is not None
    head = git(remote, "rev-parse", BRANCH).strip()
    github.pull(NAME).body = "modifiée à la main"

    # Même contenu : rien n'est poussé, la description est remise à jour.
    second = deliver(report)
    assert second.outcome is Outcome.UPDATED, second.error
    assert not second.pushed
    assert second.request == first.request
    assert git(remote, "rev-parse", BRANCH).strip() == head
    assert len(github.repos[NAME].pulls) == 1
    assert "## Mises à jour" in github.pull(NAME).body

    # La branche par défaut a avancé : la branche est refaite dessus, la même PR suit.
    push_commit(github.repos[NAME], "main", {"README.md": "# vulnerable\n"}, "Doc")
    third = deliver(report)
    assert third.outcome is Outcome.UPDATED, third.error
    assert third.pushed
    assert third.request is not None and third.request.number == 41
    assert (
        git(remote, "rev-parse", f"{BRANCH}~1").strip() == git(remote, "rev-parse", "main").strip()
    )
    assert len(github.repos[NAME].pulls) == 1


def test_a_missing_tool_is_said_in_the_request(
    github: FakeGitHubRepos, report: Report, deliver: Run
) -> None:
    done = deliver(report)  # ni npm ni uv : garde-fou des tests
    assert done.outcome is Outcome.OPENED, done.error
    assert [r.status for r in done.results] == [LockStatus.TOOL_MISSING] * 2
    assert sorted(done.committed) == ["package.json", "requirements.in"]
    body = github.pull(NAME).body
    assert "`package-lock.json` : **pas régénéré**, npm n'est pas installé" in body
    assert "npm install --package-lock-only --ignore-scripts" in body
    assert "lockfile à régénérer (npm absent)" in body


def test_a_failing_tool_leaves_its_files_out(
    github: FakeGitHubRepos,
    report: Report,
    deliver: Run,
    fake_tools: Callable[..., FakeTools],
) -> None:
    found = tools(fake_tools, "npm", "uv")
    found.handlers["uv"] = lambda call: (1, "", "error: No solution found when resolving")
    done = deliver(report)
    assert done.outcome is Outcome.OPENED, done.error
    statuses = {r.job.lockfile: r.status for r in done.results}
    assert statuses == {
        "package-lock.json": LockStatus.REGENERATED,
        "requirements.txt": LockStatus.FAILED,
    }
    assert sorted(done.committed) == ["package-lock.json", "package.json"]
    assert branch_files(github) == ["package-lock.json", "package.json"]
    body = github.pull(NAME).body
    assert "**uv pip compile a échoué**" in body
    assert "No solution found" in body
    assert "pas faite : lockfile en échec" in body
    remote = github.repos[NAME].remote
    assert remote is not None
    assert "flask" not in git(remote, "log", "-1", "--format=%B", BRANCH)


def test_nothing_to_do_nothing_pushed(
    github: FakeGitHubRepos, report: Report, deliver: Run
) -> None:
    done = deliver(report, {})
    assert done.outcome is Outcome.NOTHING
    assert not done.pushed
    assert deliver.steps == [Step.CLONING, Step.UPDATING]
    remote = github.repos[NAME].remote
    assert remote is not None
    assert not git(remote, "branch", "--list", BRANCH).strip()
    assert github.repos[NAME].pulls == []


def test_a_branch_with_commits_of_someone_else_is_not_overwritten(
    github: FakeGitHubRepos,
    report: Report,
    deliver: Run,
    fake_tools: Callable[..., FakeTools],
) -> None:
    tools(fake_tools, "npm", "uv")
    deliver(report)
    fix = push_commit(github.repos[NAME], BRANCH, {"app.js": "corrigé\n"}, "Adapter le code")
    done = deliver(report)
    assert done.outcome is Outcome.FAILED
    assert done.error is not None
    assert f"La branche {BRANCH} a un commit qui ne vient pas de forceupdate" in done.error
    assert "« Adapter le code »" in done.error
    remote = github.repos[NAME].remote
    assert remote is not None
    assert git(remote, "rev-parse", BRANCH).strip() == fix


def test_a_merge_of_the_default_branch_is_not_someone_else() -> None:
    assert forge.ours(BranchCommit(sha="a", message="Merge branch 'main' into x", merge=True))
    marked = "Mise à jour\n\nGenerated-by: forceupdate 1.0"
    assert forge.ours(BranchCommit(sha="b", message=marked, merge=False))
    assert not forge.ours(BranchCommit(sha="c", message="Adapter le code", merge=False))


@pytest.mark.parametrize(("flag", "error"), [("archived", "archivé"), ("can_push", "droit")])
def test_what_cannot_receive_a_request(
    github: FakeGitHubRepos, report: Report, deliver: Run, flag: str, error: str
) -> None:
    repo = deliver.repository()
    value = flag == "archived"
    done = deliver(report, repo=dataclasses.replace(repo, **{flag: value}))
    assert done.outcome is Outcome.FAILED
    assert error in (done.error or "")
    assert deliver.steps == []


def test_a_refused_token_is_said(
    github: FakeGitHubRepos, report: Report, remotes: Path, tmp_path: Path
) -> None:
    repo = Run(remotes, tmp_path).repository()
    refused = Run(remotes, tmp_path / "refus", token="gho_revoque")
    done = refused(report, repo=repo)
    assert done.outcome is Outcome.FAILED
    assert done.refused
    assert "refuse le token" in (done.error or "")


def test_a_fine_grained_token_refused_says_what_it_lacks(
    github: FakeGitHubRepos,
    report: Report,
    deliver: Run,
    monkeypatch: pytest.MonkeyPatch,
    fake_tools: Callable[..., FakeTools],
) -> None:
    tools(fake_tools, "npm", "uv")
    github.repos[NAME].push = False  # GitHub refuse la PR (403)
    repo = deliver.repository()
    fine = dataclasses.replace(AUTHOR, access=Access.UNKNOWN, scopes=None)
    done = deliver(report, repo=dataclasses.replace(repo, can_push=True), author=fine)
    assert done.outcome is Outcome.FAILED
    assert "« Contents » et « Pull requests » en écriture" in (done.error or "")


def test_a_long_report_is_shortened(
    github: FakeGitHubRepos, report: Report, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = LocalSource(VULNERABLE)
    prepared = local.prepare(source, report, planner.select(report))
    repo = Repository(
        forge=ForgeKind.GITHUB,
        host="github.com",
        full_name=NAME,
        default_branch="main",
        private=True,
        archived=False,
        fork=False,
        can_push=True,
        url="https://github.com/octo/vulnerable",
        clone_url="https://github.com/octo/vulnerable.git",
    )
    whole = forge.request_body(report, prepared, (), repo=repo, base="abc1234def")
    assert "Rapport raccourci" not in whole
    assert "sur le commit `abc1234` de `main`" in whole
    monkeypatch.setattr(forge, "MAX_BODY", 3000)
    short = forge.request_body(report, prepared, (), repo=repo, base="abc1234def")
    assert len(short) <= 3000
    assert "Rapport raccourci" in short
    assert short.endswith("forceupdate ne l'écrase pas.\n")
