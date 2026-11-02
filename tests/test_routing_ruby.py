"""La source globale d'un ``Gemfile`` (E33) : un autre serveur que rubygems.org n'est pas encore lu,
et rubygems.org n'est jamais demandé à sa place."""

import asyncio
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import recorded_responses

from forceupdate import engine
from forceupdate.models import FindingKind, Report
from forceupdate.net import Cache, HttpClient
from forceupdate.sources.local import LocalSource

MakeTree = Callable[..., Path]


async def no_sleep(_: float) -> None:
    pass


def analyze(root: Path) -> Report:
    async def main() -> Report:
        async with HttpClient(sleep=no_sleep) as http:
            return await engine.analyze(LocalSource(root), http=http, cache=Cache.disabled())

    return asyncio.run(main())


@pytest.mark.parametrize(
    "source", ['"https://gems.corp.example"', "('https://gems.corp.example/')"]
)
def test_a_private_global_source_is_never_replaced_by_rubygems(
    make_tree: MakeTree, source: str
) -> None:
    gemfile = f"source {source}\n\ngem 'json', '~> 2.0'\n"
    root = make_tree({"Gemfile": gemfile})
    with recorded_responses() as routes:
        report = analyze(root)
    assert routes["rubygems:json"].call_count == 0
    (project,) = report.projects
    ((finding),) = [f for f in project.findings if f.dependency is not None]
    assert finding.kind is FindingKind.UNVERIFIABLE
    assert finding.message == (
        "Non vérifié : la source de Gemfile est gems.corp.example, pas rubygems.org ; forceupdate "
        "ne lit pas encore ce serveur, et ne demande pas rubygems.org à sa place."
    )


def test_rubygems_and_a_source_block(make_tree: MakeTree) -> None:
    gemfile = (
        "source 'https://rubygems.org'\n\n"
        "source 'https://gems.corp.example' do\n  gem 'acme'\nend\n\n"
        "gem 'json', '~> 2.0'\n"
    )
    root = make_tree({"Gemfile": gemfile})
    with recorded_responses() as routes:
        analyze(root)
    assert routes["rubygems:json"].call_count == 1
