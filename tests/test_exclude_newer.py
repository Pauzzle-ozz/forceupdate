"""``[tool.uv] exclude-newer`` (E34) : uv n'installe pas une version publiée après cette date ;
forceupdate ne la propose pas, et le dit. Avec les réponses enregistrées de PyPI (requests :
2.34.0 le 11/05/2026, 2.34.1 le 13/05, 2.34.2 le 14/05)."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from forceupdate import engine
from forceupdate.models import FindingKind, Report
from forceupdate.net import Cache, HttpClient
from forceupdate.parsers.python import exclude_newer_cutoff
from forceupdate.sources.local import LocalSource

MakeTree = Callable[..., Path]
NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


def analyze(root: Path) -> Report:
    async def main() -> Report:
        async with HttpClient() as http:
            return await engine.analyze(LocalSource(root), http=http, cache=Cache.disabled())

    return asyncio.run(main())


def pyproject(exclude_newer: str | None) -> str:
    text = '[project]\nname = "demo"\nversion = "1"\ndependencies = ["requests>=2.30"]\n'
    if exclude_newer is not None:
        text += f'\n[tool.uv]\nexclude-newer = "{exclude_newer}"\n'
    return text


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-05-12T00:00:00Z", datetime(2026, 5, 12, tzinfo=UTC)),
        ("2026-05-12", datetime(2026, 5, 12, tzinfo=UTC)),
        ("1 week", datetime(2026, 10, 27, 12, 0, tzinfo=UTC)),
        ("30 days", datetime(2026, 10, 4, 12, 0, tzinfo=UTC)),
        ("24 hours", datetime(2026, 11, 2, 12, 0, tzinfo=UTC)),
        ("P7D", datetime(2026, 10, 27, 12, 0, tzinfo=UTC)),
        ("PT24H", datetime(2026, 11, 2, 12, 0, tzinfo=UTC)),
        ("1 month", None),
        ("demain", None),
    ],
)
def test_the_forms_uv_accepts(value: str, expected: datetime | None) -> None:
    assert exclude_newer_cutoff(value, NOW) == expected


def test_versions_published_after_are_not_proposed(make_tree: MakeTree, recorded: object) -> None:
    root = make_tree({"pyproject.toml": pyproject("2026-05-12T00:00:00Z")})
    report = analyze(root)
    (project,) = report.projects
    assert project.resolution == {"exclude-newer": "2026-05-12T00:00:00Z"}
    (outdated,) = [f for f in project.findings if f.kind is FindingKind.OUTDATED]
    assert outdated.target_version == "2.34.0"
    assert any(
        n.message.startswith("exclude-newer = « 2026-05-12T00:00:00Z » (uv) : les versions")
        for n in project.notices
    )


def test_without_the_setting(make_tree: MakeTree, recorded: object) -> None:
    root = make_tree({"pyproject.toml": pyproject(None)})
    (project,) = analyze(root).projects
    (outdated,) = [f for f in project.findings if f.kind is FindingKind.OUTDATED]
    assert outdated.target_version == "2.34.2"


def test_in_the_block_of_a_script(make_tree: MakeTree, recorded: object) -> None:
    script = (
        "# /// script\n"
        '# dependencies = ["requests>=2.30"]\n'
        "# [tool.uv]\n"
        '# exclude-newer = "2026-05-12T00:00:00Z"\n'
        "# ///\n"
        "import requests\n"
    )
    root = make_tree({"tool.py": script})
    (project,) = analyze(root / "tool.py").projects
    assert project.resolution == {"exclude-newer": "2026-05-12T00:00:00Z"}


def test_an_unreadable_setting(make_tree: MakeTree, recorded: object) -> None:
    root = make_tree({"pyproject.toml": pyproject("1 month")})
    (project,) = analyze(root).projects
    assert any("illisible, rien n'est écarté" in n.message for n in project.notices)
