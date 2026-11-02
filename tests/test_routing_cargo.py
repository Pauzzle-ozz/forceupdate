"""Les registres de Cargo (E34) : ``registry = "…"``, ``[registries]`` des ``.cargo/config.toml``,
``CARGO_REGISTRIES_<NOM>_INDEX``, les jetons (``credentials.toml``, l'environnement) liés au nom
d'un registre, les sources d'un ``Cargo.lock`` et crates.io remplacé ; de bout en bout par le
moteur, avec un registre « sparse » simulé."""

import asyncio
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import respx
from conftest import UserFiles, recorded_responses

from forceupdate import engine
from forceupdate.models import FindingKind, Report
from forceupdate.net import Cache, HttpClient
from forceupdate.report.json import render
from forceupdate.sources.local import LocalSource

MakeTree = Callable[..., Path]
INDEX = "https://cargo.corp.example/index"
CONFIG = f'[registries.corp]\nindex = "sparse+{INDEX}/"\n'
TOKEN = "cargo-s3cret"


def line(name: str, version: str) -> str:
    entry = {"name": name, "vers": version, "deps": [], "cksum": "00", "features": {}}
    return json.dumps({**entry, "yanked": False, "pubtime": "2026-10-01T00:00:00Z"})


ACME = "\n".join(line("acme-lib", v) for v in ("1.0.0", "1.1.0", "2.0.0")) + "\n"
HELPER = line("acme-helper", "0.3.0") + "\n"
LOG_ON_MIRROR = "\n".join(line("log", v) for v in ("0.4.20", "0.4.99")) + "\n"


async def no_sleep(_: float) -> None:
    pass


@contextmanager
def registry(status: int = 200) -> Iterator[dict[str, respx.Route]]:
    extra: dict[str, respx.Route] = {}

    def add(router: respx.MockRouter) -> None:
        extra["acme"] = router.get(f"{INDEX}/ac/me/acme-lib").respond(status, text=ACME)
        extra["helper"] = router.get(f"{INDEX}/ac/me/acme-helper").respond(status, text=HELPER)
        extra["log"] = router.get(f"{INDEX}/3/l/log").respond(status, text=LOG_ON_MIRROR)
        extra["public-acme"] = router.get("https://index.crates.io/ac/me/acme-lib").respond(
            200, text=line("acme-lib", "9.9.9")
        )

    with recorded_responses(add) as routes:
        yield {**routes, **extra}


def analyze(root: Path) -> Report:
    async def main() -> Report:
        async with HttpClient(sleep=no_sleep) as http:
            return await engine.analyze(LocalSource(root), http=http, cache=Cache.disabled())

    return asyncio.run(main())


def cargo_toml(dependencies: str = 'acme-lib = { version = "1", registry = "corp" }') -> str:
    return (
        '[package]\nname = "demo"\nversion = "0.1.0"\nedition = "2021"\n\n'
        f"[dependencies]\n{dependencies}\n"
    )


def project_files(config: str = CONFIG, **more: str) -> dict[str, str]:
    return {"Cargo.toml": cargo_toml(), "src/lib.rs": "\n", ".cargo/config.toml": config, **more}


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


def auth(route: respx.Route) -> str | None:
    return route.calls.last.request.headers.get("authorization")


def notices(report: Report) -> list[str]:
    return [n.message for project in report.projects for n in project.notices]


def test_a_named_registry_is_asked_with_the_token_of_the_person(
    make_tree: MakeTree, user_files: UserFiles
) -> None:
    root = make_tree(project_files())
    user_files.write(".cargo/config.toml", CONFIG)
    user_files.write(".cargo/credentials.toml", f'[registries.corp]\ntoken = "{TOKEN}"\n')
    with registry() as routes:
        report = analyze(root)
    assert auth(routes["acme"]) == TOKEN  # le jeton seul, comme Cargo
    assert routes["public-acme"].call_count == 0
    ((kind, message),) = findings(report, "acme-lib")
    assert kind is FindingKind.OUTDATED
    assert "2.0.0" in message
    assert "acme-lib" not in osv_names(routes)
    assert any("paquet privé" in n for n in notices(report))
    assert TOKEN not in render(report)


def test_the_token_never_goes_to_an_address_only_the_project_gives(
    make_tree: MakeTree, user_files: UserFiles
) -> None:
    root = make_tree(project_files())
    user_files.write(".cargo/credentials.toml", f'[registries.corp]\ntoken = "{TOKEN}"\n')
    with registry(status=401) as routes:
        report = analyze(root)
    assert auth(routes["acme"]) is None
    assert routes["public-acme"].call_count == 0
    assert findings(report, "acme-lib") == [
        (
            FindingKind.UNVERIFIABLE,
            "Registre privé : non vérifié : cargo.corp.example refuse l'accès à acme-lib (HTTP "
            "401) : identifiants absents ou refusés.",
        )
    ]
    assert any("Le jeton du registre « corp » ne part que vers" in n for n in notices(report))


def test_a_project_address_that_differs_from_the_person(
    make_tree: MakeTree, user_files: UserFiles
) -> None:
    root = make_tree(project_files())
    user_files.write(
        ".cargo/config.toml", '[registries.corp]\nindex = "sparse+https://other.example/"\n'
    )
    user_files.write(".cargo/credentials.toml", f'[registries.corp]\ntoken = "{TOKEN}"\n')
    with registry() as routes:
        report = analyze(root)
    assert auth(routes["acme"]) is None  # le plus proche, celui du projet, est demandé sans jeton
    assert any("Le jeton du registre « corp »" in n for n in notices(report))


def test_the_environment(make_tree: MakeTree, user_files: UserFiles) -> None:
    root = make_tree({"Cargo.toml": cargo_toml(), "src/lib.rs": "\n"})
    user_files.env["CARGO_REGISTRIES_CORP_INDEX"] = f"sparse+{INDEX}/"
    user_files.env["CARGO_REGISTRIES_CORP_TOKEN"] = TOKEN
    with registry() as routes:
        analyze(root)
    assert auth(routes["acme"]) == TOKEN


def test_cargo_home(make_tree: MakeTree, user_files: UserFiles) -> None:
    root = make_tree(project_files())
    home = user_files.write("cargo/credentials.toml", f'[registries.corp]\ntoken = "{TOKEN}"\n')
    user_files.write("cargo/config.toml", CONFIG)
    user_files.env["CARGO_HOME"] = str(home.parent)
    with registry() as routes:
        analyze(root)
    assert auth(routes["acme"]) == TOKEN


def test_a_token_written_in_the_project(make_tree: MakeTree) -> None:
    root = make_tree(project_files(CONFIG + f'token = "{TOKEN}"\n'))
    with registry() as routes:
        analyze(root)
    assert auth(routes["acme"]) == TOKEN


def test_a_dashed_registry_name(make_tree: MakeTree, user_files: UserFiles) -> None:
    dependency = 'acme-lib = { version = "1", registry = "my-corp" }'
    root = make_tree({"Cargo.toml": cargo_toml(dependency), "src/lib.rs": "\n"})
    user_files.env["CARGO_REGISTRIES_MY_CORP_INDEX"] = f"sparse+{INDEX}/"
    user_files.env["CARGO_REGISTRIES_MY_CORP_TOKEN"] = TOKEN
    with registry() as routes:
        analyze(root)
    assert auth(routes["acme"]) == TOKEN


def test_a_git_index_is_not_read(make_tree: MakeTree) -> None:
    root = make_tree(project_files('[registries.corp]\nindex = "https://git.corp.example/index"\n'))
    with registry() as routes:
        report = analyze(root)
    assert routes["acme"].call_count == 0
    assert routes["public-acme"].call_count == 0
    ((kind, message),) = findings(report, "acme-lib")
    assert kind is FindingKind.UNVERIFIABLE
    assert message.startswith("Privé : non vérifié : l'index du registre « corp »")


def test_an_undeclared_registry(make_tree: MakeTree) -> None:
    root = make_tree({"Cargo.toml": cargo_toml(), "src/lib.rs": "\n"})
    with registry() as routes:
        report = analyze(root)
    assert routes["public-acme"].call_count == 0
    ((kind, message),) = findings(report, "acme-lib")
    assert kind is FindingKind.UNVERIFIABLE
    assert "le registre « corp » n'est déclaré dans aucun .cargo/config.toml" in message


LOCK = f"""# This file is automatically @generated by Cargo.
version = 4

[[package]]
name = "acme-helper"
version = "0.3.0"
source = "sparse+{INDEX}/"
checksum = "00"

[[package]]
name = "acme-lib"
version = "1.0.0"
source = "sparse+{INDEX}/"
checksum = "00"
dependencies = [
 "acme-helper",
]

[[package]]
name = "demo"
version = "0.1.0"
dependencies = [
 "acme-lib",
 "log",
]

[[package]]
name = "log"
version = "0.4.20"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "00"
"""


def test_an_indirect_crate_of_a_private_registry(
    make_tree: MakeTree, user_files: UserFiles
) -> None:
    dependencies = 'acme-lib = { version = "1", registry = "corp" }\nlog = "0.4"'
    root = make_tree(project_files(**{"Cargo.toml": cargo_toml(dependencies), "Cargo.lock": LOCK}))
    user_files.write(".cargo/config.toml", CONFIG)
    user_files.write(".cargo/credentials.toml", f'[registries.corp]\ntoken = "{TOKEN}"\n')
    with registry() as routes:
        report = analyze(root)
    assert osv_names(routes) == {"log"}  # ni acme-lib, ni acme-helper qu'elle tire
    (project,) = report.projects
    helper = next(d for d in project.dependencies if d.name == "acme-helper")
    assert helper.unverifiable_reason is None
    acme = next(d for d in project.dependencies if d.name == "acme-lib")
    assert acme.installed == "1.0.0"


def test_crates_io_replaced_by_a_registry(make_tree: MakeTree, user_files: UserFiles) -> None:
    config = '[source.crates-io]\nreplace-with = "corp"\n\n' + CONFIG
    root = make_tree(project_files(config, **{"Cargo.toml": cargo_toml('log = "0.4"')}))
    user_files.write(".cargo/config.toml", CONFIG)
    user_files.write(".cargo/credentials.toml", f'[registries.corp]\ntoken = "{TOKEN}"\n')
    with registry() as routes:
        report = analyze(root)
    assert routes["crates:log"].call_count == 0
    assert auth(routes["log"]) == TOKEN
    assert "0.4.99" in findings(report, "log")[0][1]


def test_crates_io_replaced_by_another_source(make_tree: MakeTree) -> None:
    config = (
        '[source.crates-io]\nreplace-with = "mirror"\n\n'
        f'[source.mirror]\nregistry = "sparse+{INDEX}/"\n'
    )
    root = make_tree(project_files(config, **{"Cargo.toml": cargo_toml('log = "0.4"')}))
    with registry() as routes:
        analyze(root)
    assert routes["crates:log"].call_count == 0
    assert routes["log"].call_count == 1


def test_vendored_sources_are_copies_of_crates_io(make_tree: MakeTree) -> None:
    config = (
        '[source.crates-io]\nreplace-with = "vendored-sources"\n\n'
        '[source.vendored-sources]\ndirectory = "vendor"\n'
    )
    root = make_tree(project_files(config, **{"Cargo.toml": cargo_toml('log = "0.4"')}))
    with registry() as routes:
        analyze(root)
    assert routes["crates:log"].call_count == 1


def test_a_git_mirror_of_crates_io_is_never_replaced_by_crates_io(make_tree: MakeTree) -> None:
    config = (
        '[source.crates-io]\nreplace-with = "mirror"\n\n'
        '[source.mirror]\nregistry = "https://git.corp.example/crates-io-index"\n'
    )
    root = make_tree(project_files(config, **{"Cargo.toml": cargo_toml('log = "0.4"')}))
    with registry() as routes:
        report = analyze(root)
    assert routes["crates:log"].call_count == 0
    ((kind, message),) = findings(report, "log")
    assert kind is FindingKind.UNVERIFIABLE
    assert message.startswith("Non vérifié : crates.io est remplacé par « mirror »")
