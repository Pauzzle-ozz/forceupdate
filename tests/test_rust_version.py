"""Le ``rust-version`` d'un projet (E34) : les versions d'un crate qu'il ne fait pas tourner (le
``rust_version`` de l'index) ne sont pas proposées, et la version permise suit le résolveur 3 de
Cargo (la plus haute qui convient, sinon la plus haute) ; Rust n'a pas de constat de fin de vie."""

import asyncio
from collections.abc import Callable
from pathlib import Path

import respx

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


def cargo_toml(dependencies: str, package: str = 'rust-version = "1.68"') -> str:
    return (
        f'[package]\nname = "demo"\nversion = "0.1.0"\nedition = "2021"\n{package}\n\n'
        f"[dependencies]\n{dependencies}\n"
    )


def outdated(report: Report, name: str) -> str:
    (project,) = report.projects
    (finding,) = [
        f
        for f in project.findings
        if f.dependency is not None and f.dependency.name == name and f.kind is FindingKind.OUTDATED
    ]
    return finding.message


def test_a_version_that_needs_a_newer_rust_is_not_proposed(
    make_tree: MakeTree, recorded: dict[str, respx.Route]
) -> None:
    # log 0.4.30 et suivantes demandent Rust 1.71.0 (l'index enregistré).
    root = make_tree({"Cargo.toml": cargo_toml('log = "0.4.20"'), "src/lib.rs": "\n"})
    report = analyze(root)
    (project,) = report.projects
    (log,) = [f for f in project.findings if f.dependency is not None]
    assert log.kind is FindingKind.OUTDATED
    assert log.target_version == "0.4.29"
    assert log.wanted_version == "0.4.29"
    assert log.message.endswith(
        "La 0.4.34 n'est pas proposée : elle demande Rust 1.71.0 ; le projet : 1.68 et plus "
        "(Cargo.toml)."
    )
    (runtime,) = project.runtimes
    assert (runtime.product, runtime.version, runtime.approximate) == ("rust", "1.68", True)
    # Rust n'a pas de constat de fin de vie (une version n'est suivie que six semaines) : pas
    # même un « non concluant ».
    assert [f.dependency is not None for f in project.findings] == [True]


def test_the_resolver_falls_back_on_the_highest(make_tree: MakeTree, recorded: object) -> None:
    # time 0.3.46 et suivantes demandent Rust 1.88.0 : aucune version de la contrainte ne
    # convient, cargo prend la plus haute (vérifié avec cargo 1.99, résolveur 3).
    root = make_tree({"Cargo.toml": cargo_toml('time = ">=0.3.46"'), "src/lib.rs": "\n"})
    report = analyze(root)
    (project,) = report.projects
    (finding,) = [f for f in project.findings if f.dependency is not None]
    assert finding.wanted_version == "0.3.55"


def test_a_workspace_rust_version(make_tree: MakeTree, recorded: object) -> None:
    root_toml = (
        '[workspace]\nmembers = ["app"]\nresolver = "3"\n\n'
        '[workspace.package]\nrust-version = "1.68"\n'
    )
    member = cargo_toml('log = "0.4.20"', package="rust-version.workspace = true")
    root = make_tree({"Cargo.toml": root_toml, "app/Cargo.toml": member, "app/src/lib.rs": "\n"})
    report = analyze(root)
    app = next(p for p in report.projects if p.path == "app")
    (runtime,) = app.runtimes
    assert (runtime.version, runtime.file) == ("1.68", "Cargo.toml")
    assert any("1.71.0" in f.message for f in app.findings)


def test_a_pinned_toolchain(make_tree: MakeTree, recorded: object) -> None:
    # rand 0.10 demande Rust 1.85 : une chaîne d'outils figée en 1.80 ne la fait pas tourner.
    root = make_tree(
        {
            "Cargo.toml": cargo_toml('rand = "0.9.0"', package=""),
            "rust-toolchain.toml": '[toolchain]\nchannel = "1.80.0"\n',
            "src/lib.rs": "\n",
        }
    )
    report = analyze(root)
    assert "La 0.10.3 n'est pas proposée : elle demande Rust 1.85" in outdated(report, "rand")


def test_a_channel_is_not_a_version(make_tree: MakeTree, recorded: object) -> None:
    root = make_tree(
        {
            "Cargo.toml": cargo_toml('rand = "0.9.0"', package=""),
            "rust-toolchain": "stable\n",
            "src/lib.rs": "\n",
        }
    )
    report = analyze(root)
    (project,) = report.projects
    assert project.runtimes == []
    assert "0.10.3" in outdated(report, "rand")
