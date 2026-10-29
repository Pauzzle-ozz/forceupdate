"""Un dépôt lu par l'API de sa forge, sans le cloner (``sources.forge``) : seuls les fichiers de
dépendances sont téléchargés (et ceux que les parseurs demandent en plus), puis le moteur le lit
comme un dossier. GitHub est simulé par ``fake_forge.FakeGitHubRepos``."""

import asyncio
import copy
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import respx
from fake_forge import FakeGitHubRepos, FakeRepo, from_directory

from forceupdate import engine
from forceupdate.forges.github import GitHub
from forceupdate.models import Event, EventKind, to_dict
from forceupdate.net import HttpClient
from forceupdate.sources import forge as forge_source
from forceupdate.sources.forge import ForgeSource, relative
from forceupdate.sources.local import LocalSource

PROJECTS = Path(__file__).parent / "projects"
TOKEN = "gho_sources"


@pytest.fixture
def github() -> Iterator[FakeGitHubRepos]:
    fake = FakeGitHubRepos([], tokens={TOKEN})
    with respx.mock(assert_all_called=False) as router:
        fake.routes(router)
        yield fake


def fetch(
    github: FakeGitHubRepos,
    repo: FakeRepo,
    destination: Path,
    *,
    include_tests: bool = False,
    on_event: Callable[[Event], None] | None = None,
) -> ForgeSource:
    github.repos[repo.full_name.lower()] = repo

    async def main() -> ForgeSource:
        async with HttpClient() as http:
            forge = GitHub(http, TOKEN)
            found = await forge.repository(repo.full_name)
            return await forge_source.fetch(
                forge, found, destination, include_tests=include_tests, on_event=on_event
            )

    return asyncio.run(main())


def inventory(source: Any) -> dict[str, Any]:
    document = to_dict(engine.inventory(source))
    del document["source"]
    return document


@pytest.mark.parametrize("project", sorted(p.name for p in PROJECTS.iterdir() if p.is_dir()))
def test_a_repository_reads_like_the_same_folder(
    github: FakeGitHubRepos, tmp_path: Path, no_git: None, project: str
) -> None:
    """Le pipeline local, inchangé : mêmes langages, projets, dépendances et remarques."""
    folder = PROJECTS / project
    source = fetch(github, from_directory(f"octo/{project}", folder), tmp_path / "depot")
    assert source.origin == f"octo/{project}"
    assert inventory(source) == inventory(LocalSource(folder))


def test_only_dependency_files_are_downloaded(github: FakeGitHubRepos, tmp_path: Path) -> None:
    repo = from_directory("octo/pip", PROJECTS / "pip")
    repo.files["README.md"] = b"# pip"
    repo.files["src/app.py"] = b"print(1)\n" * 1000
    repo.files["node_modules/left-pad/package.json"] = b"{}"
    source = fetch(github, repo, tmp_path)
    # constraints.txt n'est pas un manifeste : c'est le -c de requirements.txt qui le demande.
    assert sorted(github.contents()) == [
        "octo/pip:constraints.txt",
        "octo/pip:requirements-dev.txt",
        "octo/pip:requirements.txt",
    ]
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.txt")) == [
        "constraints.txt",
        "requirements-dev.txt",
        "requirements.txt",
    ]
    # Les langages viennent de toute l'arborescence, sans les dossiers ignorés.
    paths = [file.path for file in source.files()]
    assert "src/app.py" in paths
    assert not any(path.startswith("node_modules/") for path in paths)
    assert engine.inventory(source).languages[0].name == "Python"


def test_includes_are_followed_from_round_to_round(github: FakeGitHubRepos, tmp_path: Path) -> None:
    repo = FakeRepo(
        full_name="octo/chaine",
        files={
            "requirements.txt": b"-r deps/base.txt\nflask==2.0.1\n",
            "deps/base.txt": b"-r ../commun/socle.txt\nrequests==2.25.0\n",
            "commun/socle.txt": b"-c ../contraintes.txt\njinja2\n",
            "contraintes.txt": b"jinja2==3.0.0\n",
            "deps/absent-ailleurs.txt": b"inutile\n",
        },
    )
    report = engine.inventory(fetch(github, repo, tmp_path))
    found = {d.name: d for p in report.projects for d in p.dependencies}
    assert {"flask", "requests", "jinja2"} <= set(found)
    assert found["jinja2"].installed == "3.0.0"  # du -c, deux inclusions plus loin
    assert "octo/chaine:deps/absent-ailleurs.txt" not in github.contents()


def test_a_parent_pnpm_workspace_is_downloaded(github: FakeGitHubRepos, tmp_path: Path) -> None:
    repo = from_directory("octo/catalogue", PROJECTS / "pnpm-catalog")
    fetch(github, repo, tmp_path)
    assert "octo/catalogue:pnpm-workspace.yaml" in github.contents()


def test_a_missing_file_is_not_an_error(github: FakeGitHubRepos, tmp_path: Path) -> None:
    repo = FakeRepo(full_name="octo/manque", files={"requirements.txt": b"-r absent.txt\nflask\n"})
    report = engine.inventory(fetch(github, repo, tmp_path))
    notices = [n.message for p in report.projects for n in p.notices]
    assert any("introuvable" in message for message in notices)
    assert github.contents() == ["octo/manque:requirements.txt"]


def test_a_file_too_big_is_not_downloaded(github: FakeGitHubRepos, tmp_path: Path) -> None:
    repo = FakeRepo(
        full_name="octo/gros",
        files={
            "package.json": b'{"dependencies": {"lodash": "^4.17.15"}}' + b" " * 2_000_000,
            "api/requirements.txt": b"flask==2.0.1\n",
        },
    )
    report = engine.inventory(fetch(github, repo, tmp_path))
    assert github.contents() == ["octo/gros:api/requirements.txt"]
    notices = {n.file: n.message for p in report.projects for n in p.notices}
    assert notices["package.json"] == "introuvable, illisible ou trop gros : pas lu."


def test_test_folders_follow_the_option(github: FakeGitHubRepos, tmp_path: Path) -> None:
    repo = FakeRepo(
        full_name="octo/tests",
        files={"requirements.txt": b"flask\n", "tests/fixtures/requirements.txt": b"django\n"},
    )
    fetch(github, repo, tmp_path / "sans")
    assert github.contents() == ["octo/tests:requirements.txt"]
    github.requests.clear()
    fetch(github, copy.deepcopy(repo), tmp_path / "avec", include_tests=True)
    assert sorted(github.contents()) == [
        "octo/tests:requirements.txt",
        "octo/tests:tests/fixtures/requirements.txt",
    ]


def test_downloads_are_announced(github: FakeGitHubRepos, tmp_path: Path) -> None:
    events: list[Event] = []
    fetch(github, from_directory("octo/pip", PROJECTS / "pip"), tmp_path, on_event=events.append)
    assert {event.kind for event in events} == {EventKind.DOWNLOADING}
    assert (events[0].done, events[0].total) == (0, 2)
    # Le -c de requirements.txt arrive au second tour : le total grandit.
    assert (events[-1].done, events[-1].total) == (3, 3)


def test_a_truncated_tree_is_kept(github: FakeGitHubRepos, tmp_path: Path) -> None:
    repo = FakeRepo(
        full_name="octo/immense", files={"requirements.txt": b"flask\n"}, truncated=True
    )
    source = fetch(github, repo, tmp_path)
    assert source.truncated is True
    assert source.tree.commit == repo.commit


def test_a_path_out_of_the_repository_is_refused(tmp_path: Path) -> None:
    assert relative("a/./b/../c.txt") == "a/c.txt"
    assert relative("a\\b.txt") == "a/b.txt"
    for path in ("../x", "/etc/passwd", "a/../../x", ".."):
        with pytest.raises(ValueError, match="hors du dépôt"):
            relative(path)


def test_a_path_the_system_refuses_is_skipped(tmp_path: Path) -> None:
    forge_source._write(tmp_path, "a\0b/package.json", b"{}")
    forge_source._write(tmp_path, "ok/package.json", b"{}")
    assert [p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.json")] == [
        "ok/package.json"
    ]


def test_what_the_engine_never_reads_is_not_downloaded(
    github: FakeGitHubRepos, tmp_path: Path
) -> None:
    fetch(github, from_directory("octo/setuptools", PROJECTS / "setuptools"), tmp_path)
    assert sorted(github.contents()) == [
        "octo/setuptools:pyproject.toml",
        "octo/setuptools:setup.cfg",
    ]  # pas setup.py


@pytest.mark.network
def test_a_real_public_repository(tmp_path: Path) -> None:
    """Le vrai GitHub, sans token (60 requêtes par heure) : un petit dépôt public."""

    async def main() -> tuple[ForgeSource, int]:
        async with HttpClient() as http:
            forge = GitHub(http, None)
            repo = await forge.repository("pallets/markupsafe")
            found = await forge_source.fetch(forge, repo, tmp_path)
            return found, forge.requests

    source, requests = asyncio.run(main())
    report = engine.inventory(source)
    assert report.languages[0].name == "Python"
    assert [project.path for project in report.projects] == ["."]
    assert report.projects[0].lockfiles == ["uv.lock"]
    assert report.projects[0].dependencies
    assert not (tmp_path / "setup.py").exists()
    assert requests <= 6
