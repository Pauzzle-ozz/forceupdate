"""La régénération des lockfiles (E11) : quelle commande pour quel lockfile, la version visée,
ce qu'on relit ensuite, et la remise en état quand l'outil échoue.

Les outils sont simulés (``FakeTools`` de ``tests/conftest.py``) : un faux outil écrit le
lockfile que le vrai aurait écrit. Les vrais npm, uv et pnpm ne sont lancés que dans les tests
``network``, sur des copies des mini-projets."""

import json
import os
import re
import shutil
import subprocess
import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import FakeTools, ToolCall
from fake_bundler import FakeBundler

from forceupdate import engine
from forceupdate.models import (
    Edit,
    EditKind,
    Event,
    EventKind,
    Gap,
    Project,
    Report,
    Update,
    UpdateOption,
    UpdateReason,
)
from forceupdate.parsers import parse_lockfile, ruby
from forceupdate.parsers.go import parse_go_mod
from forceupdate.parsers.lockfiles import dependents
from forceupdate.sources.local import LocalSource
from forceupdate.update import lockfiles, writers
from forceupdate.update.lockfiles import (
    LOCK_TIMEOUT,
    Job,
    LockKind,
    LockStatus,
    Reach,
    Regenerated,
    drop_yarn1_entries,
)
from forceupdate.update.writers import Changes, Choice

PROJECTS = Path(__file__).parent / "projects"
UV_BUILDS = (
    "uv construit les paquets publiés sans wheel dont il lit les dépendances, et le projet si "
    "elles sont dynamiques : leur code de construction s'exécute."
)
MakeTree = Callable[..., Path]
Tools = Callable[..., FakeTools]


def analyse(root: Path) -> tuple[LocalSource, Report]:
    source = LocalSource(root)
    return source, engine.inventory(source)


def project_of(report: Report, path: str = ".") -> Project:
    return next(project for project in report.projects if project.path == path)


def wanted(
    project: Project, name: str, version: str, *, new: str | None = None, direct: bool = True
) -> Choice:
    """La mise à jour de ``name`` vers ``version`` : sa contrainte devient ``new`` (si elle est
    donnée), sinon le lockfile seul. Une indirecte : la version installée la plus basse."""
    found = [d for d in project.dependencies if d.name == name and d.direct == direct]
    assert found, name
    if not direct:
        found = found[:1]
    edits = tuple(
        Edit(
            kind=EditKind.CATALOG if d.resolved_constraint is not None else EditKind.DEPENDENCY,
            file=d.file,
            location=d.location,
            old=d.effective_constraint,
            new=new,
        )
        for d in found
        if new is not None
    )
    lockfile = next((d.lockfile for d in found if d.lockfile), None)
    update = Update(
        id=f"{project.path}|{name}",
        ecosystem=found[0].ecosystem,
        name=name,
        direct=direct,
        dependencies=tuple(found),
        current_version=found[0].installed,
    )
    option = UpdateOption(
        version=version,
        gap=Gap.MINOR,
        reasons=(UpdateReason.LATEST_MINOR,),
        edits=edits,
        lockfile=lockfile,
    )
    return project, update, option


def apply(
    root: Path, choices: list[Choice], report: Report, source: LocalSource
) -> tuple[Changes, tuple[Job, ...], tuple[Regenerated, ...]]:
    """Ce que fait ``forceupdate update`` : réécrire, puis régénérer."""
    changes = writers.prepare(root, choices)
    jobs = lockfiles.plan(source, report, changes)
    writers.write(root, changes)
    return changes, jobs, lockfiles.regenerate(source, report, changes, jobs)


# ---------------------------------------------------------------------------
# Un faux npm : un package-lock.json v3 minimal
# ---------------------------------------------------------------------------

PACKAGE_JSON = """\
{
  "name": "demo",
  "version": "1.0.0",
  "dependencies": {
    "lodash": "^4.17.15",
    "debug": "4.3.1"
  }
}
"""


def package_lock(versions: dict[str, str], requires: dict[str, dict[str, str]]) -> str:
    """Un ``package-lock.json`` v3 : ``versions`` des paquets, et ce qu'ils requièrent."""
    root = json.loads(PACKAGE_JSON)
    packages: dict[str, object] = {"": {"name": "demo", "dependencies": root["dependencies"]}}
    for name, version in versions.items():
        entry: dict[str, object] = {"version": version}
        if name in requires:
            entry["dependencies"] = requires[name]
        packages[f"node_modules/{name}"] = entry
    lock = {"name": "demo", "lockfileVersion": 3, "requires": True, "packages": packages}
    return json.dumps(lock, indent=2) + "\n"


LOCKED = {"lodash": "4.17.15", "debug": "4.3.1", "ms": "2.1.2"}
REQUIRES = {"debug": {"ms": "2.1.2"}}


def npm_project(make_tree: MakeTree) -> Path:
    return make_tree(
        {"package.json": PACKAGE_JSON, "package-lock.json": package_lock(LOCKED, REQUIRES)}
    )


class FakeNpm:
    """``npm install`` fige chaque directe à la version exacte écrite dans le ``package.json``
    (sinon il garde le lockfile) ; ``npm update x`` monte x à ``latest[x]``."""

    def __init__(self, root: Path, latest: dict[str, str] | None = None) -> None:
        self.root = root
        self.latest = latest or {}

    def __call__(self, call: ToolCall) -> None:
        lock_path = self.root / "package-lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        versions = {
            key.removeprefix("node_modules/"): entry["version"]
            for key, entry in lock["packages"].items()
            if key
        }
        manifest = json.loads((self.root / "package.json").read_text(encoding="utf-8"))
        if call.arguments[0] == "install":
            for name, spec in manifest["dependencies"].items():
                if spec[0].isdigit():
                    versions[name] = spec
        else:
            for name in call.arguments[1:]:
                if not name.startswith("-") and name in self.latest:
                    versions[name] = self.latest[name]
        lock_path.write_text(package_lock(versions, REQUIRES), encoding="utf-8")


# ---------------------------------------------------------------------------
# Le plan
# ---------------------------------------------------------------------------


def test_plan_gives_the_command_of_each_update(make_tree: MakeTree, fake_tools: Tools) -> None:
    root = npm_project(make_tree)
    fake_tools("npm")
    source, report = analyse(root)
    project = project_of(report)
    only = wanted(project, "lodash", "4.17.21")
    edited = wanted(project, "debug", "4.3.7", new="4.3.7")

    jobs = lockfiles.plan(source, report, writers.prepare(root, [edited]))
    assert [(j.lockfile, j.kind, j.program, j.command) for j in jobs] == [
        (
            "package-lock.json",
            LockKind.NPM,
            "/outils/npm",
            "npm install --package-lock-only --ignore-scripts",
        )
    ]
    assert jobs[0].inputs == ("package.json",)
    jobs = lockfiles.plan(source, report, writers.prepare(root, [only, edited]))
    assert jobs[0].command == "npm update lodash --package-lock-only --ignore-scripts"
    assert jobs[0].inputs == ("package.json",)
    assert jobs[0].workspace is False


def test_a_missing_tool_has_no_program(make_tree: MakeTree) -> None:
    root = npm_project(make_tree)
    source, report = analyse(root)
    choice = wanted(project_of(report), "lodash", "4.17.21")
    (job,) = lockfiles.plan(source, report, writers.prepare(root, [choice]))
    assert job.program is None
    assert job.program_name == "npm"


YARN_BERRY = """\
__metadata:
  version: 10
  cacheKey: 10c0

"demo@workspace:.":
  version: 0.0.0-use.local
  resolution: "demo@workspace:."
  dependencies:
    lodash: "npm:^4.17.15"
  languageName: unknown
  linkType: soft

"lodash@npm:^4.17.15":
  version: 4.17.15
  resolution: "lodash@npm:4.17.15"
  languageName: node
  linkType: hard
"""

YARN_1 = """\
# THIS IS AN AUTOGENERATED FILE. DO NOT EDIT THIS FILE DIRECTLY.
# yarn lockfile v1


lodash@^4.17.15:
  version "4.17.15"
  resolved "https://registry.yarnpkg.com/lodash/-/lodash-4.17.15.tgz"
"""

PNPM_LOCK = """\
lockfileVersion: '9.0'

importers:

  .:
    dependencies:
      lodash:
        specifier: ^4.17.15
        version: 4.17.15

packages:

  lodash@4.17.15:
    resolution: {integrity: sha512-x}

snapshots:

  lodash@4.17.15: {}
"""

LODASH_ONLY = '{\n  "name": "demo",\n  "dependencies": {\n    "lodash": "^4.17.15"\n  }\n}\n'


@pytest.mark.parametrize(
    ("files", "kind", "command"),
    [
        (
            {"yarn.lock": YARN_1},
            LockKind.YARN_1,
            "yarn upgrade lodash --ignore-scripts",
        ),
        (
            {"yarn.lock": YARN_BERRY},
            LockKind.YARN,
            "yarn up -R lodash --mode=update-lockfile",
        ),
        (
            {"pnpm-lock.yaml": PNPM_LOCK},
            LockKind.PNPM,
            "pnpm update lodash --no-save --lockfile-only --ignore-scripts --ignore-pnpmfile",
        ),
        (
            {"pnpm-lock.yaml": PNPM_LOCK, "pnpm-workspace.yaml": "packages: []\n"},
            LockKind.PNPM,
            "pnpm update -r lodash --no-save --lockfile-only --ignore-scripts --ignore-pnpmfile",
        ),
    ],
)
def test_plan_of_each_npm_lockfile(
    make_tree: MakeTree, files: dict[str, str], kind: LockKind, command: str
) -> None:
    root = make_tree({"package.json": LODASH_ONLY, **files})
    source, report = analyse(root)
    choice = wanted(project_of(report), "lodash", "4.17.21")
    (job,) = lockfiles.plan(source, report, writers.prepare(root, [choice]))
    assert (job.kind, job.command) == (kind, command)


def test_yarn_says_when_it_runs_code_of_the_project(make_tree: MakeTree) -> None:
    root = make_tree(
        {
            "package.json": LODASH_ONLY,
            "yarn.lock": YARN_BERRY,
            ".yarnrc.yml": "yarnPath: .yarn/releases/yarn-4.18.1.cjs\nplugins:\n  - x.cjs\n",
        }
    )
    source, report = analyse(root)
    choice = wanted(project_of(report), "lodash", "4.17.21")
    (job,) = lockfiles.plan(source, report, writers.prepare(root, [choice]))
    assert job.warnings == ("Yarn lance du code du projet : yarnPath, plugins (fichiers .yarnrc).",)


UV_PROJECT = """\
[project]
name = "demo"
version = "0.1.0"
dependencies = ["httpx>=0.27"]
"""

UV_LOCK = """\
version = 1
requires-python = ">=3.11"

[[package]]
name = "demo"
version = "0.1.0"
source = { virtual = "." }
dependencies = [{ name = "httpx" }]

[[package]]
name = "h11"
version = "0.14.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "httpx"
version = "0.27.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "h11" }]
"""

POETRY_PROJECT = """\
[tool.poetry]
name = "demo"
version = "0.1.0"

[tool.poetry.dependencies]
python = "^3.11"
httpx = "^0.27"
"""

POETRY_LOCK = """\
[[package]]
name = "httpx"
version = "0.27.0"
description = ""
optional = false
python-versions = ">=3.8"
files = []

[metadata]
lock-version = "2.0"
python-versions = "^3.11"
content-hash = "x"
"""

PIPFILE = '[packages]\nhttpx = ">=0.27"\n'
PIPFILE_LOCK = json.dumps(
    {"_meta": {}, "default": {"httpx": {"version": "==0.27.0"}}, "develop": {}}, indent=4
)

PDM_PROJECT = UV_PROJECT + "\n[tool.pdm]\ndistribution = false\n"
PDM_LOCK = """\
[metadata]
lock_version = "4.5.0"

[[package]]
name = "httpx"
version = "0.27.0"
"""


@pytest.mark.parametrize(
    ("files", "kind", "only", "edited"),
    [
        (
            {"pyproject.toml": UV_PROJECT, "uv.lock": UV_LOCK},
            LockKind.UV,
            "uv lock -P httpx==0.27.2",
            "uv lock -P httpx==0.28.1",
        ),
        (
            {"pyproject.toml": POETRY_PROJECT, "poetry.lock": POETRY_LOCK},
            LockKind.POETRY,
            "poetry update --lock httpx",
            "poetry lock",
        ),
        (
            {"pyproject.toml": PDM_PROJECT, "pdm.lock": PDM_LOCK},
            LockKind.PDM,
            "pdm update --no-sync --update-reuse httpx",
            "pdm lock --update-reuse",
        ),
        (
            {"Pipfile": PIPFILE, "Pipfile.lock": PIPFILE_LOCK},
            LockKind.PIPENV,
            "pipenv lock",
            "pipenv lock",
        ),
    ],
)
def test_plan_of_each_python_lockfile(
    make_tree: MakeTree, files: dict[str, str], kind: LockKind, only: str, edited: str
) -> None:
    root = make_tree(files)
    source, report = analyse(root)
    project = project_of(report)
    (job,) = lockfiles.plan(
        source, report, writers.prepare(root, [wanted(project, "httpx", "0.27.2")])
    )
    assert (job.kind, job.command) == (kind, only)
    new = "^0.28.1" if kind is LockKind.POETRY else ">=0.28.1"
    (job,) = lockfiles.plan(
        source, report, writers.prepare(root, [wanted(project, "httpx", "0.28.1", new=new)])
    )
    assert job.command == edited
    assert job.inputs == (next(iter(files)),)


@pytest.mark.parametrize(("version", "options"), [("1.8.5", ("--no-update",)), ("2.5.1", ())])
def test_poetry_1_needs_no_update(
    make_tree: MakeTree, fake_tools: Tools, version: str, options: tuple[str, ...]
) -> None:
    tools = fake_tools("poetry")
    tools.handlers["poetry"] = lambda call: (0, f"Poetry (version {version})\n", "")
    root = make_tree({"pyproject.toml": POETRY_PROJECT, "poetry.lock": POETRY_LOCK})
    source, report = analyse(root)
    choice = wanted(project_of(report), "httpx", "0.28.1", new="^0.28.1")
    (job,) = lockfiles.plan(source, report, writers.prepare(root, [choice]))
    assert job.options == options
    assert tools.commands() == ["poetry --version"]


# -- pip-tools ----------------------------------------------------------------

PIP_COMPILE_HEADER = """\
#
# This file is autogenerated by pip-compile with Python 3.12
# by the following command:
#
#    {command}
#
"""


def compiled(command: str, pins: str) -> str:
    return PIP_COMPILE_HEADER.format(command=command) + pins


@pytest.mark.parametrize(
    ("header", "command", "warnings"),
    [
        (None, "pip-compile requirements.in -P flask==3.1.3", ()),
        (
            "pip-compile requirements.in",
            "pip-compile requirements.in -P flask==3.1.3",
            (),
        ),
        (
            "pip-compile --generate-hashes --output-file=requirements.txt --pip-args='-q' "
            "--index-url https://pypi.example/simple requirements.in",
            "pip-compile --generate-hashes --index-url https://pypi.example/simple "
            "requirements.in -P flask==3.1.3",
            ("Pas repris de l'en-tête de requirements.txt : --pip-args=-q.",),
        ),
        (
            "pip-compile requirements.in extra.in -o requirements.txt",
            "pip-compile --output-file requirements.txt requirements.in extra.in -P flask==3.1.3",
            (),
        ),
    ],
)
def test_pip_compile_reuses_the_options_of_its_header(
    make_tree: MakeTree, header: str | None, command: str, warnings: tuple[str, ...]
) -> None:
    pins = "flask==2.0.1\n"
    root = make_tree(
        {
            "requirements.in": "flask>=2.0\n",
            "extra.in": "click\n",
            "requirements.txt": pins if header is None else compiled(header, pins),
        }
    )
    source, report = analyse(root)
    choice = wanted(project_of(report), "flask", "3.1.3")
    (job,) = lockfiles.plan(source, report, writers.prepare(root, [choice]))
    assert (job.kind, job.command, job.warnings[:-1]) == (LockKind.PIP_COMPILE, command, warnings)
    assert job.warnings[-1].startswith("pip-compile construit les paquets publiés sans wheel")


def test_uv_pip_compile_without_exclude_newer(make_tree: MakeTree) -> None:
    root = make_tree(
        {
            "requirements.in": "flask==0.12\n",
            "requirements.txt": (
                "# This file was autogenerated by uv via the following command:\n"
                "#    uv pip compile requirements.in -o requirements.txt --python-version 3.7 "
                "--exclude-newer 2019-01-01\nflask==0.12\n"
            ),
        }
    )
    source, report = analyse(root)
    choice = wanted(project_of(report), "flask", "0.12.5", new="==0.12.5")
    (job,) = lockfiles.plan(source, report, writers.prepare(root, [choice]))
    assert job.kind is LockKind.UV_PIP_COMPILE
    assert job.command == (
        "uv pip compile requirements.in -o requirements.txt --python-version 3.7 -P flask==0.12.5"
    )
    assert job.warnings == (
        "Pas repris de l'en-tête de requirements.txt : --exclude-newer 2019-01-01, qui "
        "écarterait les versions choisies.",
        UV_BUILDS,
    )
    assert job.inputs == ("requirements.in",)


PIP_TOOLS = {
    "requirements.in": "flask>=2.0\n",
    "requirements.txt": compiled("pip-compile requirements.in", "flask==2.0.1\nclick==8.0.0\n"),
    "requirements-dev.in": "-c requirements.txt\npytest>=8\n",
    "requirements-dev.txt": compiled("pip-compile requirements-dev.in", "pytest==8.0.0\n"),
}


def test_a_compiled_file_that_cites_a_regenerated_one_follows_it(make_tree: MakeTree) -> None:
    root = make_tree(PIP_TOOLS)
    source, report = analyse(root)
    choice = wanted(project_of(report), "flask", "3.1.3", new=">=3.1.3")
    jobs = lockfiles.plan(source, report, writers.prepare(root, [choice]))
    assert [(j.lockfile, j.command, j.reason, j.inputs) for j in jobs] == [
        (
            "requirements.txt",
            "pip-compile requirements.in -P flask==3.1.3",
            None,
            ("requirements.in",),
        ),
        (
            "requirements-dev.txt",
            "pip-compile requirements-dev.in",
            "requirements.txt a changé",
            ("requirements.txt",),
        ),
    ]


def test_a_mixed_project_keeps_its_ecosystems_apart(make_tree: MakeTree) -> None:
    root = make_tree(
        {
            "package.json": LODASH_ONLY,
            "package-lock.json": package_lock({"lodash": "4.17.15"}, {}),
            "requirements.in": "flask==2.0.1\n",
            "requirements.txt": "flask==2.0.1\n",
        }
    )
    source, report = analyse(root)
    project = project_of(report)
    choices = [
        wanted(project, "lodash", "4.18.1", new="^4.18.1"),
        wanted(project, "flask", "2.0.3", new="==2.0.3"),
    ]
    jobs = lockfiles.plan(source, report, writers.prepare(root, choices))
    assert [(j.lockfile, j.inputs) for j in jobs] == [
        ("package-lock.json", ("package.json",)),
        ("requirements.txt", ("requirements.in",)),
    ]
    assert len(lockfiles._groups(jobs)) == 2


# -- fichier de contraintes de pip -------------------------------------------------


def test_a_constraints_file_is_rewritten_like_a_manifest(tmp_path: Path) -> None:
    root = tmp_path / "pip"
    shutil.copytree(PROJECTS / "pip", root)
    source, report = analyse(root)
    project = project_of(report)
    numpy = wanted(project, "numpy", "1.26.5")
    certifi = wanted(project, "certifi", "2024.7.4", direct=False)
    changes = writers.prepare(root, [numpy, certifi])
    assert [c.path for c in changes.files] == ["constraints.txt"]
    assert changes.files[0].after == "numpy==1.26.5\ncertifi==2024.7.4\n"
    assert changes.lockfiles == ()
    assert lockfiles.plan(source, report, changes) == ()


def test_a_constraints_line_with_hashes_is_not_rewritten(make_tree: MakeTree) -> None:
    root = make_tree(
        {
            "requirements.txt": "-c constraints.txt\nnumpy\n",
            "constraints.txt": "numpy==1.26.4 \\\n    --hash=sha256:abc\n",
        }
    )
    _, report = analyse(root)
    changes = writers.prepare(root, [wanted(project_of(report), "numpy", "1.26.5")])
    assert changes.files == ()
    assert [s.reason for s in changes.skipped] == [
        "constraints.txt : ligne 1, les empreintes (--hash) sont celles de la version actuelle ; "
        "à réécrire à la main, avec celles de la nouvelle."
    ]


# ---------------------------------------------------------------------------
# La régénération
# ---------------------------------------------------------------------------


def test_npm_pins_the_chosen_version_then_puts_the_range_back(
    make_tree: MakeTree, fake_tools: Tools
) -> None:
    root = npm_project(make_tree)
    tools = fake_tools("npm")
    tools.handlers["npm"] = FakeNpm(root)
    tools.watch(root / "package.json")
    source, report = analyse(root)
    choice = wanted(project_of(report), "lodash", "4.17.21")

    _, _, (result,) = apply(root, [choice], report, source)

    install = "npm install --package-lock-only --ignore-scripts --no-audit --no-fund"
    assert tools.commands() == [install, install]
    pinned, synced = (json.loads(c.files["package.json"]) for c in tools.calls)
    assert pinned["dependencies"]["lodash"] == "4.17.21"
    assert synced["dependencies"]["lodash"] == "^4.17.15"
    assert (root / "package.json").read_text(encoding="utf-8") == PACKAGE_JSON
    assert result.status is LockStatus.REGENERATED
    (installed,) = result.installed
    assert (installed.versions, installed.reach) == (("4.17.21",), Reach.EXACT)
    assert result.changed == ()


def test_each_tool_run_is_announced(make_tree: MakeTree, fake_tools: Tools) -> None:
    root = npm_project(make_tree)
    fake_tools("npm").handlers["npm"] = FakeNpm(root)
    source, report = analyse(root)
    changes = writers.prepare(root, [wanted(project_of(report), "lodash", "4.17.21")])
    jobs = lockfiles.plan(source, report, changes)
    events: list[Event] = []
    lockfiles.regenerate(source, report, changes, jobs, on_event=events.append)
    # Un seul événement par lockfile, même si npm est lancé deux fois (épinglé, puis la plage).
    assert events == [Event(kind=EventKind.REGENERATING, name="package-lock.json", done=0, total=1)]


def test_nothing_is_announced_without_the_tool(make_tree: MakeTree) -> None:
    root = npm_project(make_tree)
    source, report = analyse(root)
    changes = writers.prepare(root, [wanted(project_of(report), "lodash", "4.17.21")])
    jobs = lockfiles.plan(source, report, changes)
    events: list[Event] = []
    (result,) = lockfiles.regenerate(source, report, changes, jobs, on_event=events.append)
    assert result.status is LockStatus.TOOL_MISSING
    assert events == []


def test_an_indirect_held_by_its_parent(make_tree: MakeTree, fake_tools: Tools) -> None:
    root = npm_project(make_tree)
    tools = fake_tools("npm")
    tools.handlers["npm"] = FakeNpm(root)  # debug 4.3.1 veut ms 2.1.2 exactement
    source, report = analyse(root)
    choice = wanted(project_of(report), "ms", "2.1.3", direct=False)

    _, _, (result,) = apply(root, [choice], report, source)

    assert tools.commands() == [
        "npm update ms --package-lock-only --ignore-scripts --no-audit --no-fund",
        "npm install --package-lock-only --ignore-scripts --no-audit --no-fund",
    ]
    (installed,) = result.installed
    assert (installed.versions, installed.reach, installed.held_by) == (
        ("2.1.2",),
        Reach.BELOW,
        ("debug 4.3.1",),
    )


def test_an_indirect_that_goes_above_the_target(make_tree: MakeTree, fake_tools: Tools) -> None:
    root = npm_project(make_tree)
    tools = fake_tools("npm")
    tools.handlers["npm"] = FakeNpm(root, latest={"ms": "2.1.4"})
    source, report = analyse(root)
    choice = wanted(project_of(report), "ms", "2.1.3", direct=False)
    _, _, (result,) = apply(root, [choice], report, source)
    (installed,) = result.installed
    assert (installed.versions, installed.reach) == (("2.1.4",), Reach.ABOVE)


def test_a_refused_pin_falls_back_to_npm_update(make_tree: MakeTree, fake_tools: Tools) -> None:
    root = npm_project(make_tree)
    tools = fake_tools("npm")
    fake = FakeNpm(root, latest={"lodash": "4.18.1"})

    def npm(call: ToolCall) -> tuple[int, str, str] | None:
        if '"lodash": "4.17.21"' in (root / "package.json").read_text(encoding="utf-8"):
            return 1, "", "npm error code ERESOLVE\nnpm error could not resolve"
        fake(call)
        return None

    tools.handlers["npm"] = npm
    source, report = analyse(root)
    choice = wanted(project_of(report), "lodash", "4.17.21")
    _, _, (result,) = apply(root, [choice], report, source)

    assert tools.commands()[1:] == [
        "npm update lodash --package-lock-only --ignore-scripts --no-audit --no-fund",
        "npm install --package-lock-only --ignore-scripts --no-audit --no-fund",
    ]
    assert result.status is LockStatus.REGENERATED
    assert result.warnings == (
        "Versions exactes refusées : « npm install --package-lock-only --ignore-scripts "
        "--no-audit --no-fund » a échoué (code 1) :",
    )
    assert result.installed[0].reach is Reach.ABOVE
    assert (root / "package.json").read_text(encoding="utf-8") == PACKAGE_JSON


def test_a_failure_puts_every_file_back(make_tree: MakeTree, fake_tools: Tools) -> None:
    root = npm_project(make_tree)
    lock = (root / "package-lock.json").read_bytes()
    tools = fake_tools("npm")

    def npm(call: ToolCall) -> tuple[int, str, str]:
        (root / "package-lock.json").write_text("{ à moitié écrit", encoding="utf-8")
        return 1, "", "\x1b[31mnpm error\x1b[0m code ERESOLVE\nnpm error conflit de versions\n"

    tools.handlers["npm"] = npm
    source, report = analyse(root)
    choice = wanted(project_of(report), "debug", "4.3.7", new="4.3.7")
    changes, _, (result,) = apply(root, [choice], report, source)

    assert changes.files[0].path == "package.json"
    assert result.status is LockStatus.FAILED
    assert result.error == (
        "« npm install --package-lock-only --ignore-scripts --no-audit --no-fund » a échoué "
        "(code 1) :\nnpm error code ERESOLVE\nnpm error conflit de versions"
    )
    assert result.restored == ("package-lock.json", "package.json")
    assert (root / "package.json").read_text(encoding="utf-8") == PACKAGE_JSON
    assert (root / "package-lock.json").read_bytes() == lock


def test_a_missing_tool_leaves_the_manifest_rewritten(make_tree: MakeTree) -> None:
    root = npm_project(make_tree)
    lock = (root / "package-lock.json").read_bytes()
    source, report = analyse(root)
    choice = wanted(project_of(report), "debug", "4.3.7", new="4.3.7")
    _, _, (result,) = apply(root, [choice], report, source)
    assert result.status is LockStatus.TOOL_MISSING
    assert result.job.command == "npm install --package-lock-only --ignore-scripts"
    assert '"debug": "4.3.7"' in (root / "package.json").read_text(encoding="utf-8")
    assert (root / "package-lock.json").read_bytes() == lock


def test_tools_run_without_shell_input_or_activated_virtualenv(
    make_tree: MakeTree, fake_tools: Tools, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_tree({"pyproject.toml": UV_PROJECT, "uv.lock": UV_LOCK})
    monkeypatch.setenv("VIRTUAL_ENV", str(root / ".venv"))
    monkeypatch.setenv("UV_LOCKED", "1")
    tools = fake_tools("uv")
    source, report = analyse(root)
    choice = wanted(project_of(report), "httpx", "0.28.1")
    apply(root, [choice], report, source)

    (call,) = tools.calls
    assert call.arguments == ["lock", "-P", "httpx==0.28.1"]
    assert call.cwd == root
    assert "VIRTUAL_ENV" not in call.env and "UV_LOCKED" not in call.env
    assert call.env["NO_COLOR"] == "1"
    options = {key: value for key, value in call.options.items() if key not in ("cwd", "env")}
    assert options == {
        "stdin": subprocess.DEVNULL,
        "capture_output": True,
        "timeout": LOCK_TIMEOUT,
        "check": False,
    }


def test_the_real_spawn_never_uses_a_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.undo()  # retire le garde-fou de conftest, qui remplace lockfiles._spawn
    seen: dict[str, object] = {}
    monkeypatch.setattr(subprocess, "run", lambda command, **options: seen.update(options))
    lockfiles._spawn(["uv", "lock"], timeout=1)
    assert seen == {"shell": False, "timeout": 1}


def test_a_workspace_lockfile_is_regenerated_once_from_its_root(
    tmp_path: Path, fake_tools: Tools
) -> None:
    root = tmp_path / "uv"
    shutil.copytree(PROJECTS / "uv", root)
    tools = fake_tools("uv")
    source, report = analyse(root)
    choices = [
        wanted(project_of(report), "httpx", "0.28.1"),
        wanted(project_of(report, "packages/lib"), "packaging", "26.3"),
    ]
    _, jobs, _ = apply(root, choices, report, source)
    assert [job.lockfile for job in jobs] == ["uv.lock"]
    assert [(c.cwd, c.arguments) for c in tools.calls] == [
        (root, ["lock", "-P", "httpx==0.28.1", "-P", "packaging==26.3"])
    ]


def test_a_batch_file_gets_no_argument_cmd_would_interpret(
    make_tree: MakeTree, fake_tools: Tools, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = npm_project(make_tree)
    tools = fake_tools("npm")
    monkeypatch.setattr(lockfiles, "_which", lambda program: "C:/nodejs/npm.CMD")
    source, report = analyse(root)
    project, update, option = wanted(project_of(report), "ms", "2.1.3", direct=False)
    odd = Update(**{**update.__dict__, "name": "ms&calc"})
    _, _, (result,) = apply(root, [(project, odd, option)], report, source)
    assert result.status is LockStatus.FAILED
    assert result.error is not None and "argument refusé (ms&calc)" in result.error
    assert tools.calls == []


def test_a_tool_that_does_not_finish(make_tree: MakeTree, fake_tools: Tools) -> None:
    root = npm_project(make_tree)
    tools = fake_tools("npm")

    def npm(call: ToolCall) -> None:
        raise subprocess.TimeoutExpired(call.program, LOCK_TIMEOUT)

    tools.handlers["npm"] = npm
    source, report = analyse(root)
    choice = wanted(project_of(report), "debug", "4.3.7", new="4.3.7")
    _, _, (result,) = apply(root, [choice], report, source)
    assert result.status is LockStatus.FAILED
    assert result.error is not None and result.error.endswith("n'a pas fini en 600 s.")
    assert (root / "package.json").read_text(encoding="utf-8") == PACKAGE_JSON


def test_the_delay_of_the_tools_comes_from_the_settings(
    make_tree: MakeTree, fake_tools: Tools
) -> None:
    root = npm_project(make_tree)
    tools = fake_tools("npm")

    def npm(call: ToolCall) -> None:
        raise subprocess.TimeoutExpired(call.program, call.options["timeout"])

    tools.handlers["npm"] = npm
    source, report = analyse(root)
    choice = wanted(project_of(report), "debug", "4.3.7", new="4.3.7")
    changes = writers.prepare(root, [choice])
    (job,) = lockfiles.plan(source, report, changes, lockfiles.Tools(timeout=45))
    assert job.timeout == 45
    writers.write(root, changes)
    (result,) = lockfiles.regenerate(source, report, changes, [job])
    assert tools.calls[0].options["timeout"] == 45
    assert result.error is not None and result.error.endswith("n'a pas fini en 45 s.")


def test_an_interruption_puts_every_file_back(make_tree: MakeTree, fake_tools: Tools) -> None:
    root = npm_project(make_tree)
    tools = fake_tools("npm")

    def npm(call: ToolCall) -> None:
        (root / "package-lock.json").write_text("{}", encoding="utf-8")
        raise KeyboardInterrupt

    tools.handlers["npm"] = npm
    source, report = analyse(root)
    lock = (root / "package-lock.json").read_bytes()
    choice = wanted(project_of(report), "lodash", "4.17.21")
    with pytest.raises(KeyboardInterrupt):
        apply(root, [choice], report, source)
    assert (root / "package.json").read_text(encoding="utf-8") == PACKAGE_JSON
    assert (root / "package-lock.json").read_bytes() == lock


def test_other_versions_the_lockfile_changed_are_told(
    make_tree: MakeTree, fake_tools: Tools
) -> None:
    root = make_tree({"pyproject.toml": UV_PROJECT, "uv.lock": UV_LOCK})
    tools = fake_tools("uv")

    def uv(call: ToolCall) -> None:
        text = UV_LOCK.replace('version = "0.27.0"', 'version = "0.28.1"')
        (root / "uv.lock").write_text(text.replace('"0.14.0"', '"0.16.0"'), encoding="utf-8")

    tools.handlers["uv"] = uv
    source, report = analyse(root)
    _, _, (result,) = apply(root, [wanted(project_of(report), "httpx", "0.28.1")], report, source)
    assert result.installed[0].reach is Reach.EXACT
    assert result.changed == ("h11 0.14.0 → 0.16.0",)


def test_a_failed_compiled_file_undoes_the_ones_it_follows(
    make_tree: MakeTree, fake_tools: Tools
) -> None:
    root = make_tree(PIP_TOOLS)
    before = {name: (root / name).read_bytes() for name in PIP_TOOLS}
    tools = fake_tools("pip-compile")

    def pip_compile(call: ToolCall) -> tuple[int, str, str] | None:
        if "requirements-dev.in" in call.arguments:
            return 2, "", "Could not find a version that matches pytest>=8,<7"
        (root / "requirements.txt").write_text(
            compiled("pip-compile requirements.in", "flask==3.1.3\nclick==8.1.0\n"),
            encoding="utf-8",
        )
        return None

    tools.handlers["pip-compile"] = pip_compile
    source, report = analyse(root)
    choice = wanted(project_of(report), "flask", "3.1.3", new=">=3.1.3")
    _, _, results = apply(root, [choice], report, source)

    assert tools.commands() == [
        "pip-compile --quiet requirements.in -P flask==3.1.3",
        "pip-compile --quiet requirements-dev.in",
    ]
    assert [(r.job.lockfile, r.status, r.error) for r in results] == [
        ("requirements.txt", LockStatus.UNDONE, "requirements-dev.txt a échoué"),
        (
            "requirements-dev.txt",
            LockStatus.FAILED,
            "« pip-compile --quiet requirements-dev.in » a échoué (code 2) :\n"
            "Could not find a version that matches pytest>=8,<7",
        ),
    ]
    assert results[0].restored == ("requirements.in", "requirements.txt")
    assert {name: (root / name).read_bytes() for name in PIP_TOOLS} == before


def test_yarn_1_resolves_the_package_again_outside_the_project(
    make_tree: MakeTree, fake_tools: Tools
) -> None:
    root = make_tree({"package.json": LODASH_ONLY, "yarn.lock": YARN_1})
    tools = fake_tools("yarn")
    tools.watch(root / "yarn.lock")
    source, report = analyse(root)
    choice = wanted(project_of(report), "lodash", "4.17.21")
    apply(root, [choice], report, source)

    (call,) = tools.calls
    folder = Path(call.arguments[call.arguments.index("--modules-folder") + 1])
    assert call.arguments[:5] == [
        "install",
        "--ignore-scripts",
        "--ignore-engines",
        "--non-interactive",
        "--no-progress",
    ]
    assert not folder.is_relative_to(root)
    assert "lodash@" not in call.files["yarn.lock"]


def test_yarn_berry_targets_the_package(make_tree: MakeTree, fake_tools: Tools) -> None:
    root = make_tree({"package.json": LODASH_ONLY, "yarn.lock": YARN_BERRY})
    tools = fake_tools("yarn")
    source, report = analyse(root)
    apply(root, [wanted(project_of(report), "lodash", "4.17.21")], report, source)
    assert tools.commands() == ["yarn up -R lodash --mode=update-lockfile"]
    assert tools.calls[0].env["YARN_ENABLE_IMMUTABLE_INSTALLS"] == "false"


def test_pnpm_pins_a_catalog_range(tmp_path: Path, fake_tools: Tools) -> None:
    root = tmp_path / "pnpm-catalog"
    shutil.copytree(PROJECTS / "pnpm-catalog", root)
    tools = fake_tools("pnpm")
    tools.watch(root / "pnpm-workspace.yaml")
    source, report = analyse(root)
    choice = wanted(project_of(report, "packages/app"), "is-odd", "3.0.0", new="^3.0.0")
    _, _, (result,) = apply(root, [choice], report, source)

    base = "pnpm install --lockfile-only --ignore-scripts --ignore-pnpmfile --no-frozen-lockfile"
    assert tools.commands() == [base, base]
    assert "is-odd: 3.0.0\n" in tools.calls[0].files["pnpm-workspace.yaml"]
    assert "is-odd: ^3.0.0\n" in tools.calls[1].files["pnpm-workspace.yaml"]
    assert "is-odd: ^3.0.0\n" in (root / "pnpm-workspace.yaml").read_text(encoding="utf-8")
    assert result.installed[0].reach is Reach.BELOW  # le faux pnpm n'a rien changé


def test_poetry_pins_with_double_equals(make_tree: MakeTree, fake_tools: Tools) -> None:
    root = make_tree({"pyproject.toml": POETRY_PROJECT, "poetry.lock": POETRY_LOCK})
    tools = fake_tools("poetry")
    tools.watch(root / "pyproject.toml")
    tools.handlers["poetry"] = lambda call: (0, "Poetry (version 2.5.1)\n", "")
    source, report = analyse(root)
    apply(root, [wanted(project_of(report), "httpx", "0.27.2")], report, source)
    assert tools.commands() == [
        "poetry --version",
        "poetry lock --no-interaction",
        "poetry lock --no-interaction",
    ]
    assert 'httpx = "==0.27.2"' in tools.calls[1].files["pyproject.toml"]
    assert (root / "pyproject.toml").read_text(encoding="utf-8") == POETRY_PROJECT


# ---------------------------------------------------------------------------
# Les morceaux
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_drop_yarn1_entries(newline: str) -> None:
    text = (
        "# yarn lockfile v1\n\n\n"
        '"@babel/core@^7.0.0", "@babel/core@^7.1.0":\n  version "7.1.0"\n  resolved "x"\n\n'
        'lodash@^4.17.15:\n  version "4.17.15"\n  dependencies:\n    x "1"\n\n'
        'ms@2.1.2:\n  version "2.1.2"\n'
    ).replace("\n", newline)
    dropped = drop_yarn1_entries(text, {("lodash", "4.17.15"), ("@babel/core", "7.1.0")})
    assert dropped == ('# yarn lockfile v1\n\n\nms@2.1.2:\n  version "2.1.2"\n').replace(
        "\n", newline
    )
    assert drop_yarn1_entries(text, {("lodash", "4.18.1")}) == text


def test_dependents_say_what_holds_a_version() -> None:
    lock = parse_lockfile("package-lock.json", package_lock(LOCKED, REQUIRES))
    assert [(p.name, p.version) for p in dependents(lock, "ms", "2.1.2")] == [("debug", "4.3.1")]
    assert dependents(lock, "ms", "2.1.3") == []
    lock = parse_lockfile("uv.lock", UV_LOCK)
    assert [p.name for p in dependents(lock, "h11", "0.14.0")] == ["httpx"]


def test_parse_lockfile_reads_a_compiled_requirements_file() -> None:
    lock = parse_lockfile("requirements.txt", "flask==3.1.3\nclick>=8\n")
    assert [(p.name, p.version) for p in lock.packages] == [("flask", "3.1.3"), ("click", "")]
    with pytest.raises(ValueError, match="pas un lockfile connu"):
        parse_lockfile("go.work.sum", "")


# ---------------------------------------------------------------------------
# Cargo
# ---------------------------------------------------------------------------


class FakeCargo:
    """``cargo update --workspace`` fige chaque crate épinglé (``=V``) dans un ``Cargo.toml`` à
    ``V`` ; ``cargo update -p x@actuelle --precise V`` passe x de l'actuelle à V. Avec
    ``refuse_pins``, un épinglage échoue, comme quand un autre crate exige autre chose."""

    def __init__(self, root: Path, *, refuse_pins: bool = False) -> None:
        self.root = root
        self.refuse_pins = refuse_pins
        self.written = self._pins()
        """Les ``=V`` écrits dans le projet (``regex = "=1.5.4"``) : pas des épinglages."""

    def __call__(self, call: ToolCall) -> tuple[int, str, str] | None:
        lock_path = self.root / "Cargo.lock"
        text = lock_path.read_text(encoding="utf-8")
        args = call.arguments
        if "--precise" in args:
            name, _, current = args[args.index("-p") + 1].partition("@")
            target = args[args.index("--precise") + 1]
            if f'name = "{name}"\nversion = "{current}"' not in text:
                return 101, "", f"error: package ID specification `{name}@{current}` did not match"
            text = text.replace(
                f'name = "{name}"\nversion = "{current}"', f'name = "{name}"\nversion = "{target}"'
            ).replace(f'"{name} {current}"', f'"{name} {target}"')
        else:
            pins = self._pins()
            if pins != self.written and self.refuse_pins:
                return 101, "", "error: failed to select a version for the requirement"
            for name, version in pins.items():
                text = re.sub(
                    rf'(name = "{re.escape(name)}"\nversion = ")[^"]+"', rf'\g<1>{version}"', text
                )
        lock_path.write_text(text, encoding="utf-8")
        return None

    def _pins(self) -> dict[str, str]:
        found = {}
        for manifest in self.root.rglob("Cargo.toml"):
            data = tomllib.loads(manifest.read_text(encoding="utf-8"))
            tables = [
                data.get("dependencies", {}),
                data.get("workspace", {}).get("dependencies", {}),
            ]
            for table in tables:
                for key, spec in table.items():
                    name = spec.get("package", key) if isinstance(spec, dict) else key
                    version = spec.get("version") if isinstance(spec, dict) else spec
                    if isinstance(version, str) and version.startswith("="):
                        found[name] = version[1:]
        return found


def cargo_copy(tmp_path: Path, name: str = "cargo") -> Path:
    root = tmp_path / name
    shutil.copytree(PROJECTS / name, root)
    return root


def locked(root: Path, name: str) -> list[str]:
    lock = parse_lockfile("Cargo.lock", (root / "Cargo.lock").read_text(encoding="utf-8"))
    return [p.version for p in lock.packages if p.name == name]


def test_plan_of_a_cargo_lockfile(tmp_path: Path, fake_tools: Tools) -> None:
    root = cargo_copy(tmp_path)
    fake_tools("cargo")
    source, report = analyse(root)
    project = project_of(report)
    lockfile_only = wanted(project, "anyhow", "1.0.104")
    edited = wanted(project, "regex", "1.13.1", new="=1.13.1")

    (job,) = lockfiles.plan(source, report, writers.prepare(root, [lockfile_only]))
    assert (job.lockfile, job.kind, job.program, job.tool) == (
        "Cargo.lock",
        LockKind.CARGO,
        "/outils/cargo",
        "Cargo",
    )
    assert job.command == "cargo update -p anyhow@1.0.75 --precise 1.0.104"
    assert job.warnings == ()
    (job,) = lockfiles.plan(source, report, writers.prepare(root, [edited]))
    # La contrainte réécrite n'accepte plus 1.5.4 : cargo ignorerait --precise.
    assert job.command == "cargo update -p regex@1.5.4"
    assert job.inputs == ("Cargo.toml",)
    (job,) = lockfiles.plan(source, report, writers.prepare(root, [lockfile_only, edited]))
    assert job.command == "cargo update -p anyhow@1.0.75 -p regex@1.5.4"


def test_cargo_pins_the_chosen_versions_then_puts_the_constraints_back(
    tmp_path: Path, fake_tools: Tools
) -> None:
    root = cargo_copy(tmp_path)
    tools = fake_tools("cargo")
    tools.handlers["cargo"] = FakeCargo(root)
    tools.watch(root / "Cargo.toml")
    source, report = analyse(root)
    project = project_of(report)
    choices = [
        wanted(project, "regex", "1.13.1", new="=1.13.1"),
        wanted(project, "anyhow", "1.0.104"),
        wanted(project, "rand_core", "0.6.3", direct=False),
    ]

    _, _, (result,) = apply(root, choices, report, source)

    assert tools.commands() == [
        "cargo update --workspace",
        "cargo update -p rand_core@0.6.4 --precise 0.6.3",
        "cargo update --workspace",
    ]
    pinned = tools.calls[0].files["Cargo.toml"]
    assert 'regex = "=1.13.1"' in pinned
    assert '[dependencies.anyhow]\nversion = "=1.0.104"' in pinned
    manifest = (root / "Cargo.toml").read_text(encoding="utf-8")
    assert 'regex = "=1.13.1"' in manifest and 'version = "1.0"' in manifest
    assert result.status is LockStatus.REGENERATED, result.error
    assert [(i.update.name, i.versions, i.reach) for i in result.installed] == [
        ("regex", ("1.13.1",), Reach.EXACT),
        ("anyhow", ("1.0.104",), Reach.EXACT),
        ("rand_core", ("0.6.3",), Reach.EXACT),
    ]
    assert locked(root, "anyhow") == ["1.0.104"]


def test_cargo_runs_without_the_rustc_of_the_project(tmp_path: Path, fake_tools: Tools) -> None:
    """``cargo update`` lance ``rustc -vV`` pour le résolveur 3 : le ``rustc`` installé, et
    aucun « wrapper », quoi que dise ``.cargo/config.toml``."""
    root = cargo_copy(tmp_path)
    tools = fake_tools("cargo", "rustc")
    tools.handlers["cargo"] = FakeCargo(root)
    source, report = analyse(root)
    apply(root, [wanted(project_of(report), "anyhow", "1.0.104")], report, source)
    for call in tools.calls:
        assert call.env["RUSTC"] == "/outils/rustc"
        assert call.env["RUSTC_WRAPPER"] == "" and call.env["RUSTC_WORKSPACE_WRAPPER"] == ""
        assert call.env["CARGO_TERM_COLOR"] == "never"
        assert call.cwd == root


def test_without_rustc_cargo_gets_its_bare_name(tmp_path: Path, fake_tools: Tools) -> None:
    root = cargo_copy(tmp_path)
    tools = fake_tools("cargo")
    tools.handlers["cargo"] = FakeCargo(root)
    source, report = analyse(root)
    apply(root, [wanted(project_of(report), "anyhow", "1.0.104")], report, source)
    assert {call.env["RUSTC"] for call in tools.calls} == {"rustc"}


def test_a_refused_cargo_pin_falls_back_to_precise(tmp_path: Path, fake_tools: Tools) -> None:
    root = cargo_copy(tmp_path)
    tools = fake_tools("cargo")
    tools.handlers["cargo"] = FakeCargo(root, refuse_pins=True)
    source, report = analyse(root)
    choice = wanted(project_of(report), "anyhow", "1.0.104")

    _, _, (result,) = apply(root, [choice], report, source)

    assert tools.commands() == [
        "cargo update --workspace",
        "cargo update -p anyhow@1.0.75 --precise 1.0.104",
        "cargo update --workspace",
    ]
    assert result.status is LockStatus.REGENERATED, result.error
    assert result.warnings == (
        "Versions exactes refusées : « cargo update --workspace » a échoué (code 101) :",
    )
    assert result.installed[0].reach is Reach.EXACT


def test_a_cargo_workspace_pins_its_root_and_skips_what_moved(
    tmp_path: Path, fake_tools: Tools
) -> None:
    """smallvec est reprise de [workspace.dependencies] : épinglée à la racine. itoa est une
    indirecte de app (par core-lib) et une directe de core : épinglée pour core, puis plus rien
    à viser pour app."""
    root = cargo_copy(tmp_path, "cargo-workspace")
    tools = fake_tools("cargo")
    tools.handlers["cargo"] = FakeCargo(root)
    tools.watch(root / "Cargo.toml")
    source, report = analyse(root)
    app, core = project_of(report, "crates/app"), project_of(report, "crates/core")
    choices = [
        wanted(app, "smallvec", "1.16.4", new="=1.16.4"),
        wanted(core, "itoa", "1.0.15", new="1.0.15"),
        wanted(app, "itoa", "1.0.15", direct=False),
    ]

    _, (job,), (result,) = apply(root, choices, report, source)

    assert job.inputs == ("Cargo.toml", "crates/core/Cargo.toml")
    assert tools.commands() == ["cargo update --workspace", "cargo update --workspace"]
    assert 'smallvec = "=1.16.4"' in tools.calls[0].files["Cargo.toml"]
    assert result.status is LockStatus.REGENERATED, result.error
    assert locked(root, "smallvec") == ["1.16.4"] and locked(root, "itoa") == ["1.0.15"]
    assert [i.reach for i in result.installed] == [Reach.EXACT] * 3


def test_cargo_says_what_it_takes_from_the_project(tmp_path: Path, fake_tools: Tools) -> None:
    root = cargo_copy(tmp_path, "cargo-workspace")
    (root / ".cargo").mkdir()
    (root / ".cargo" / "config.toml").write_text("[net]\nretry = 3\n", encoding="utf-8")
    (root / "rust-toolchain.toml").write_text('[toolchain]\nchannel = "1.80"\n', encoding="utf-8")
    fake_tools("cargo")
    source, report = analyse(root)
    choice = wanted(project_of(report, "crates/app"), "anyhow", "1.0.104")
    (job,) = lockfiles.plan(source, report, writers.prepare(root, [choice]))
    assert job.warnings == (
        "rustup lit rust-toolchain.toml : il installe s'il le faut, puis lance, la chaîne "
        "d'outils qu'il désigne, même un dossier du projet.",
        "cargo lit .cargo/config.toml : les registres et les sources qu'il désigne, et les "
        "programmes d'identification (credential-provider) qu'il lance pour un registre privé.",
    )


def test_cargo_with_the_default_toolchain_of_the_person(tmp_path: Path, fake_tools: Tools) -> None:
    """Le réglage « chaîne d'outils Rust » : ``RUSTUP_TOOLCHAIN`` passe devant le
    ``rust-toolchain.toml`` du projet (vérifié avec rustup 1.29), sans rien installer."""
    root = cargo_copy(tmp_path)
    (root / "rust-toolchain.toml").write_text('[toolchain]\nchannel = "1.70"\n', encoding="utf-8")
    tools = fake_tools("cargo", "rustup")
    tools.handlers["cargo"] = FakeCargo(root)
    tools.handlers["rustup"] = lambda call: (0, "stable-x86_64-pc-windows-msvc (default)\n", "")
    source, report = analyse(root)
    choice = wanted(project_of(report), "anyhow", "1.0.104")
    changes = writers.prepare(root, [choice])
    asked = lockfiles.Tools(rust_default_toolchain=True)
    (job,) = lockfiles.plan(source, report, changes, asked)
    assert job.toolchain == "stable-x86_64-pc-windows-msvc"
    assert job.warnings == (
        "rust-toolchain.toml n'est pas suivi : cargo tourne avec la chaîne d'outils par défaut, "
        "stable-x86_64-pc-windows-msvc (réglage « chaîne d'outils Rust ») ; plus ancienne que ce "
        "que demande le projet, la régénération peut échouer.",
    )
    writers.write(root, changes)
    (result,) = lockfiles.regenerate(source, report, changes, [job])
    assert result.status is LockStatus.REGENERATED, result.error
    cargo = [call for call in tools.calls if call.program == "cargo"]
    assert cargo and all(
        c.env["RUSTUP_TOOLCHAIN"] == "stable-x86_64-pc-windows-msvc" for c in cargo
    )
    assert [c.arguments for c in tools.calls if c.program == "rustup"] == [["default"]]


def test_without_a_default_toolchain_rustup_chooses(tmp_path: Path, fake_tools: Tools) -> None:
    root = cargo_copy(tmp_path)
    (root / "rust-toolchain.toml").write_text('[toolchain]\nchannel = "1.70"\n', encoding="utf-8")
    tools = fake_tools("cargo", "rustup")
    tools.handlers["rustup"] = lambda call: (1, "", "error: no default toolchain configured\n")
    source, report = analyse(root)
    changes = writers.prepare(root, [wanted(project_of(report), "anyhow", "1.0.104")])
    (job,) = lockfiles.plan(source, report, changes, lockfiles.Tools(rust_default_toolchain=True))
    assert job.toolchain is None
    assert job.warnings[0].endswith(
        "même un dossier du projet (réglage « chaîne d'outils Rust » : rustup n'en a pas par "
        "défaut)."
    )
    # Sans le réglage, rustup n'est même pas lancé.
    tools.calls.clear()
    (job,) = lockfiles.plan(source, report, changes)
    assert job.toolchain is None and tools.calls == []


def test_a_cargo_failure_puts_every_file_back(tmp_path: Path, fake_tools: Tools) -> None:
    root = cargo_copy(tmp_path)
    tools = fake_tools("cargo")
    tools.handlers["cargo"] = lambda call: (101, "", "error: failed to get `itoa` as a dependency")
    before = {name: (root / name).read_bytes() for name in ("Cargo.toml", "Cargo.lock")}
    source, report = analyse(root)
    choice = wanted(project_of(report), "regex", "1.13.1", new="=1.13.1")

    _, _, (result,) = apply(root, [choice], report, source)

    assert result.status is LockStatus.FAILED
    assert result.error is not None and "failed to get `itoa`" in result.error
    assert result.restored == ("Cargo.toml",)
    assert {name: (root / name).read_bytes() for name in before} == before


# ---------------------------------------------------------------------------
# Go
# ---------------------------------------------------------------------------


class FakeGoTidy:
    """``go mod tidy`` : il garde les versions de ``go.mod`` (``raise_to`` en fait monter
    d'autres, comme la sélection minimale ; ``go_line`` réécrit la directive ``go``) et refait
    ``go.sum`` pour elles."""

    def __init__(
        self, root: Path, *, raise_to: dict[str, str] | None = None, go_line: str | None = None
    ) -> None:
        self.root = root
        self.raise_to = raise_to or {}
        self.go_line = go_line

    def __call__(self, call: ToolCall) -> tuple[int, str, str] | None:
        assert call.arguments == ["mod", "tidy"]
        go_mod = call.cwd / "go.mod"
        text = go_mod.read_text(encoding="utf-8")
        for name, version in self.raise_to.items():
            text = re.sub(rf"(\t{re.escape(name)} )v\S+", rf"\g<1>{version}", text)
        if self.go_line is not None:
            text = re.sub(r"^go \S+$", f"go {self.go_line}", text, flags=re.MULTILINE)
        go_mod.write_text(text, encoding="utf-8")
        sums = [
            f"{d.name} {d.installed} h1:faux="
            for d in parse_go_mod("go.mod", text)
            if d.installed is not None
        ]
        (call.cwd / "go.sum").write_text("\n".join(sorted(sums)) + "\n", encoding="utf-8")
        return None


def go_copy(tmp_path: Path, name: str = "go") -> Path:
    root = tmp_path / name
    shutil.copytree(PROJECTS / name, root)
    return root


def test_plan_of_a_go_sum(tmp_path: Path, fake_tools: Tools) -> None:
    root = go_copy(tmp_path)
    fake_tools("go")
    source, report = analyse(root)
    choice = wanted(project_of(report), "github.com/golang-jwt/jwt/v4", "v4.5.2", new="v4.5.2")
    (job,) = lockfiles.plan(source, report, writers.prepare(root, [choice]))
    assert (job.lockfile, job.kind, job.program, job.tool, job.command) == (
        "go.sum",
        LockKind.GO,
        "/outils/go",
        "Go",
        "go mod tidy",
    )
    assert (job.inputs, job.warnings) == (("go.mod",), ())


def test_go_tidy_keeps_the_written_versions(tmp_path: Path, fake_tools: Tools) -> None:
    """Une directe et une indirecte (``// indirect``), réécrites dans ``go.mod`` ; ``go mod
    tidy`` refait ``go.sum``, sans chaîne d'outils téléchargée ni ``GOFLAGS`` de la personne."""
    root = go_copy(tmp_path)
    tools = fake_tools("go")
    tools.handlers["go"] = FakeGoTidy(root)
    source, report = analyse(root)
    project = project_of(report)
    yaml = "gopkg.in/yaml.v3"
    choices = [
        wanted(project, "github.com/golang-jwt/jwt/v4", "v4.5.2", new="v4.5.2"),
        wanted(project, yaml, "v3.0.1", new="v3.0.1", direct=False),
    ]

    _, _, (result,) = apply(root, choices, report, source)

    assert tools.commands() == ["go mod tidy"]
    (call,) = tools.calls
    assert (call.env["GOTOOLCHAIN"], call.env["GOFLAGS"], call.env["GOWORK"]) == (
        "local",
        "-mod=mod",
        "off",
    )
    assert result.status is LockStatus.REGENERATED, result.error
    assert [(i.update.name, i.versions, i.reach) for i in result.installed] == [
        ("github.com/golang-jwt/jwt/v4", ("v4.5.2",), Reach.EXACT),
        (yaml, ("v3.0.1",), Reach.EXACT),
    ]
    assert (result.changed, result.warnings) == ((), ())
    assert "gopkg.in/yaml.v3 v3.0.1 h1:faux=" in (root / "go.sum").read_text(encoding="utf-8")


def test_go_says_what_tidy_raised(tmp_path: Path, fake_tools: Tools) -> None:
    """La nouvelle version en demande d'autres : la sélection minimale les fait monter, et la
    directive ``go`` avec (vérifié avec Go 1.27 : x/text v0.30.0 demande go 1.24.0)."""
    root = go_copy(tmp_path)
    tools = fake_tools("go")
    tools.handlers["go"] = FakeGoTidy(
        root, raise_to={"github.com/davecgh/go-spew": "v1.1.1"}, go_line="1.24.0"
    )
    source, report = analyse(root)
    choice = wanted(project_of(report), "golang.org/x/text", "v0.30.0", new="v0.30.0")

    _, _, (result,) = apply(root, [choice], report, source)

    assert result.status is LockStatus.REGENERATED, result.error
    assert result.changed == ("github.com/davecgh/go-spew v1.1.0 → v1.1.1",)
    assert result.warnings == ("go mod tidy a changé la directive go : 1.21 → 1.24.0.",)


def test_go_says_when_tidy_writes_the_installed_go(tmp_path: Path, fake_tools: Tools) -> None:
    """Sans directive ``go``, tidy écrit celle du go installé (vérifié avec Go 1.27)."""
    root = go_copy(tmp_path)
    go_mod = root / "go.mod"
    go_mod.write_text(go_mod.read_text(encoding="utf-8").replace("go 1.21\n", ""), encoding="utf-8")
    tools = fake_tools("go")

    def tidy(call: ToolCall) -> None:
        go_mod.write_text(
            go_mod.read_text(encoding="utf-8").replace("module", "go 1.27.3\n\nmodule", 1),
            encoding="utf-8",
        )

    tools.handlers["go"] = tidy
    source, report = analyse(root)
    choice = wanted(project_of(report), "golang.org/x/text", "v0.3.8", new="v0.3.8")
    _, _, (result,) = apply(root, [choice], report, source)
    assert result.warnings == (
        "go mod tidy a changé la directive go : absente → 1.27.3 (le go installé).",
    )


def test_go_without_go_sum(tmp_path: Path, fake_tools: Tools) -> None:
    """Un module qui n'a pas encore de ``go.sum`` : tidy le crée ; s'il échoue, il n'en reste
    rien, et ``go.mod`` est remis."""
    root = go_copy(tmp_path)
    (root / "go.sum").unlink()
    before = (root / "go.mod").read_bytes()
    tools = fake_tools("go")
    tools.handlers["go"] = lambda call: (1, "", "go: github.com/a@v1: reading …: 404 Not Found")
    source, report = analyse(root)
    assert project_of(report).lockfiles == []
    choice = wanted(project_of(report), "golang.org/x/text", "v0.3.8", new="v0.3.8")

    _, (job,), (result,) = apply(root, [choice], report, source)

    assert job.lockfile == "go.sum"
    assert result.status is LockStatus.FAILED
    assert result.error is not None and "404 Not Found" in result.error
    assert result.restored == ("go.mod",)
    assert (root / "go.mod").read_bytes() == before and not (root / "go.sum").exists()

    tools.handlers["go"] = FakeGoTidy(root)
    _, _, (result,) = apply(root, [choice], report, source)
    assert result.status is LockStatus.REGENERATED, result.error
    assert (root / "go.sum").exists()


def test_go_says_what_it_does_not_do(tmp_path: Path, fake_tools: Tools) -> None:
    """``toolchain`` : le go installé est lancé ; ``vendor/`` : à refaire à la main."""
    root = go_copy(tmp_path, "go-workspace")
    (root / "tools" / "vendor").mkdir()
    (root / "tools" / "vendor" / "modules.txt").write_text("# github.com/google/uuid v1.2.0\n")
    fake_tools("go")
    source, report = analyse(root)
    choice = wanted(project_of(report, "tools"), "github.com/google/uuid", "v1.6.0", new="v1.6.0")
    (job,) = lockfiles.plan(source, report, writers.prepare(root, [choice]))
    assert job.lockfile == "tools/go.sum"
    assert job.warnings == (
        "go.mod demande go1.21.13 : forceupdate lance le go installé, sans en télécharger un "
        "autre (GOTOOLCHAIN=local) ; plus ancien que la directive go, il échoue, et rien ne "
        "change.",
        "vendor/ n'est pas refait : lancer go mod vendor après la mise à jour (go build refuse "
        "un vendor/modules.txt périmé).",
    )


def test_a_go_work_replace_needs_no_regeneration(tmp_path: Path, fake_tools: Tools) -> None:
    root = go_copy(tmp_path, "go-workspace")
    tools = fake_tools("go")
    source, report = analyse(root)
    choice = wanted(project_of(report, "lib"), "golang.org/x/text", "v0.4.0", new="v0.4.0")
    assert choice[2].lockfile is None
    changes, jobs, results = apply(root, [choice], report, source)
    assert [change.path for change in changes.files] == ["go.work"]
    assert (jobs, results, tools.calls) == ((), (), [])
    assert "golang.org/x/text v0.4.0\n" in (root / "go.work").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Composer
# ---------------------------------------------------------------------------

UNBLOCKED = (
    "Composer ne refuse pas, le temps de la régénération, une version qui a encore une faille "
    "connue (COMPOSER_POLICY_ADVISORIES_BLOCK=0, Composer 2.10 et plus) : forceupdate montre "
    "celles qui restent. Les logiciels malveillants restent bloqués."
)


class FakeComposerUpdate:
    """``composer update x:V…`` : chaque paquet nommé passe à sa version dans ``composer.lock``
    (``also`` en fait bouger d'autres, comme ``-W``)."""

    def __init__(self, also: dict[str, str] | None = None) -> None:
        self.also = also or {}

    def __call__(self, call: ToolCall) -> tuple[int, str, str] | None:
        assert call.arguments[0] == "update"
        lock = call.cwd / "composer.lock"
        data = json.loads(lock.read_text(encoding="utf-8"))
        wanted = dict(a.split(":", 1) for a in call.arguments[1:] if not a.startswith("-"))
        for entry in data["packages"] + data["packages-dev"]:
            entry["version"] = wanted.get(
                entry["name"], self.also.get(entry["name"], entry["version"])
            )
        data["content-hash"] = "nouveau"
        lock.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")
        return None


def composer_copy(tmp_path: Path) -> Path:
    root = tmp_path / "composer"
    shutil.copytree(PROJECTS / "composer", root)
    return root


def test_plan_of_a_composer_lock(tmp_path: Path, fake_tools: Tools) -> None:
    root = composer_copy(tmp_path)
    fake_tools("composer")
    source, report = analyse(root)
    project = project_of(report)
    choices = [
        wanted(project, "guzzlehttp/guzzle", "7.16.1", new="7.16.1"),
        wanted(project, "guzzlehttp/psr7", "2.13.2", direct=False),
    ]
    (job,) = lockfiles.plan(source, report, writers.prepare(root, choices))
    assert (job.lockfile, job.kind, job.program, job.tool) == (
        "composer.lock",
        LockKind.COMPOSER,
        "/outils/composer",
        "Composer",
    )
    assert job.command == (
        "composer update guzzlehttp/guzzle:7.16.1 guzzlehttp/psr7:2.13.2 -W -m --no-install "
        "--no-scripts --no-plugins"
    )
    # config.platform.php est dans le composer.json du mini-projet, vendor/ n'y est pas.
    assert (job.inputs, job.warnings) == (("composer.json",), (UNBLOCKED,))


def test_composer_targets_each_version(
    tmp_path: Path, fake_tools: Tools, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Une directe réécrite, une directe par le lockfile seul, une indirecte : un seul ``composer
    update``, chaque paquet à sa version, ce que la nouvelle version exige monté avec (``-W``).
    Les variables héritées qui changeraient le fichier lu ou les versions choisies sont
    retirées (vérifié avec Composer 2.11 : ``COMPOSER_PREFER_LOWEST`` fait descendre)."""
    for name, value in (("COMPOSER", "autre.json"), ("COMPOSER_PREFER_LOWEST", "1")):
        monkeypatch.setenv(name, value)
    root = composer_copy(tmp_path)
    tools = fake_tools("composer")
    tools.handlers["composer"] = FakeComposerUpdate(also={"guzzlehttp/promises": "2.6.0"})
    source, report = analyse(root)
    project = project_of(report)
    choices = [
        wanted(project, "guzzlehttp/guzzle", "7.16.1", new="7.16.1"),
        wanted(project, "twig/twig", "v3.4.3"),
        wanted(project, "guzzlehttp/psr7", "2.13.2", direct=False),
    ]

    _, _, (result,) = apply(root, choices, report, source)

    assert tools.commands() == [
        "composer update guzzlehttp/guzzle:7.16.1 twig/twig:v3.4.3 guzzlehttp/psr7:2.13.2 "
        "--with-all-dependencies --no-install --no-scripts --no-plugins --no-interaction "
        "--no-progress --no-ansi --ignore-platform-req=ext-* --ignore-platform-req=lib-*"
    ]
    (call,) = tools.calls
    assert call.cwd == root
    assert {key: call.env.get(key) for key in ("COMPOSER", "COMPOSER_PREFER_LOWEST")} == {
        "COMPOSER": None,
        "COMPOSER_PREFER_LOWEST": None,
    }
    assert [call.env[key] for key in ("COMPOSER_MINIMAL_CHANGES", "COMPOSER_NO_AUDIT")] == [
        "1",
        "1",
    ]
    assert call.env["COMPOSER_POLICY_ADVISORIES_BLOCK"] == "0"
    assert result.status is LockStatus.REGENERATED, result.error
    assert [(i.update.name, i.versions, i.reach) for i in result.installed] == [
        ("guzzlehttp/guzzle", ("7.16.1",), Reach.EXACT),
        ("twig/twig", ("v3.4.3",), Reach.EXACT),
        ("guzzlehttp/psr7", ("2.13.2",), Reach.EXACT),
    ]
    assert result.changed == ("guzzlehttp/promises 1.5.1 → 2.6.0",)


@pytest.mark.parametrize(
    ("config", "environment"),
    [
        ({"policy": {"advisories": {"block": True}}}, None),
        ({"policy": False}, None),
        ({"audit": {"block-insecure": True}}, None),
        ({}, "1"),
    ],
)
def test_the_advisory_blocking_of_the_project_or_the_person_is_kept(
    tmp_path: Path,
    fake_tools: Tools,
    monkeypatch: pytest.MonkeyPatch,
    config: dict[str, object],
    environment: str | None,
) -> None:
    root = composer_copy(tmp_path)
    manifest = root / "composer.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["config"].update(config)
    manifest.write_text(json.dumps(data, indent=4), encoding="utf-8")
    if environment is not None:
        monkeypatch.setenv("COMPOSER_POLICY_ADVISORIES_BLOCK", environment)
    tools = fake_tools("composer")
    tools.handlers["composer"] = FakeComposerUpdate()
    source, report = analyse(root)
    choice = wanted(project_of(report), "twig/twig", "v3.4.3")
    _, (job,), (result,) = apply(root, [choice], report, source)
    assert result.status is LockStatus.REGENERATED, result.error
    (call,) = tools.calls
    assert call.env.get("COMPOSER_POLICY_ADVISORIES_BLOCK") == environment
    assert UNBLOCKED not in job.warnings


def test_composer_says_what_it_does_not_do(tmp_path: Path, fake_tools: Tools) -> None:
    """Sans ``config.platform.php``, le PHP de la machine ; ``vendor/`` laissé tel quel."""
    root = composer_copy(tmp_path)
    manifest = root / "composer.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    del data["config"]["platform"]
    manifest.write_text(json.dumps(data, indent=4), encoding="utf-8")
    (root / "vendor" / "composer").mkdir(parents=True)
    (root / "vendor" / "composer" / "installed.json").write_text('{"packages": []}')
    fake_tools("composer")
    source, report = analyse(root)
    choice = wanted(project_of(report), "twig/twig", "v3.4.3")
    (job,) = lockfiles.plan(source, report, writers.prepare(root, [choice]))
    assert job.warnings == (
        UNBLOCKED,
        "Sans config.platform.php dans composer.json, Composer choisit les versions pour le PHP "
        "de cette machine.",
        "vendor/ n'est pas mis à jour : lancer composer install après la mise à jour.",
    )


def test_a_composer_failure_puts_every_file_back(tmp_path: Path, fake_tools: Tools) -> None:
    root = composer_copy(tmp_path)
    before = {name: (root / name).read_bytes() for name in ("composer.json", "composer.lock")}
    tools = fake_tools("composer")
    tools.handlers["composer"] = lambda call: (
        2,
        "",
        "Your requirements could not be resolved to an installable set of packages.",
    )
    source, report = analyse(root)
    choice = wanted(project_of(report), "monolog/monolog", "3.12.1", new="^3.12.1")

    _, _, (result,) = apply(root, [choice], report, source)

    assert result.status is LockStatus.FAILED
    assert result.error is not None and "could not be resolved" in result.error
    assert result.restored == ("composer.json",)
    assert {name: (root / name).read_bytes() for name in before} == before


# ---------------------------------------------------------------------------
# Bundler
# ---------------------------------------------------------------------------

BUNDLER_RUNS_CODE = (
    "Bundler exécute le Gemfile (c'est du Ruby), ce qu'il charge (eval_gemfile) et les .gemspec "
    "du projet, de ses gems path: et git: ; aucune option ne l'en empêche."
)


def bundler_copy(tmp_path: Path) -> Path:
    root = tmp_path / "bundler"
    shutil.copytree(PROJECTS / "bundler", root)
    return root


def locked_gems(root: Path) -> dict[str, str]:
    lock = parse_lockfile("Gemfile.lock", (root / "Gemfile.lock").read_text(encoding="utf-8"))
    return {p.name: p.version for p in lock.packages}


def test_plan_of_a_gemfile_lock(tmp_path: Path, fake_tools: Tools) -> None:
    root = bundler_copy(tmp_path)
    fake_tools("bundle")
    source, report = analyse(root)
    project = project_of(report)
    rewritten = [wanted(project, "puma", "5.6.9", new="5.6.9")]
    (job,) = lockfiles.plan(source, report, writers.prepare(root, rewritten))
    assert (job.lockfile, job.kind, job.program, job.tool) == (
        "Gemfile.lock",
        LockKind.BUNDLER,
        "/outils/bundle",
        "Bundler",
    )
    assert job.command == "bundle lock"
    assert (job.inputs, job.warnings) == (("Gemfile",), (BUNDLER_RUNS_CODE,))
    assert job.workspace  # la gem locale helper partage le lockfile
    others = [
        wanted(project, "rack", "2.2.8.1"),
        wanted(project, "nio4r", "2.5.9", direct=False),
    ]
    (job,) = lockfiles.plan(source, report, writers.prepare(root, rewritten + others))
    assert job.command == "bundle lock --update rack nio4r --conservative"


def test_bundler_targets_each_version(
    tmp_path: Path, fake_tools: Tools, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Une directe réécrite, une directe par le lockfile seul (sous la plus haute que permet sa
    contrainte), une du ``.gemspec``, une indirecte : épinglées (``= V``, une ligne ``gem`` pour
    l'indirecte) le temps d'un ``bundle lock``, puis le ``Gemfile`` remis et ``bundle lock``
    relancé, qui garde tout (vérifié avec Bundler 4.0.20). ``BUNDLE_GEMFILE`` et
    ``BUNDLE_LOCKFILE`` hérités lui feraient lire et écrire d'autres fichiers."""
    for name in ("BUNDLE_GEMFILE", "BUNDLE_LOCKFILE", "BUNDLE_FORCE_RUBY_PLATFORM"):
        monkeypatch.setenv(name, "autre")
    root = bundler_copy(tmp_path)
    tools = fake_tools("bundle")
    tools.handlers["bundle"] = FakeBundler()
    tools.watch(root / "Gemfile", root / "demo.gemspec")
    source, report = analyse(root)
    project = project_of(report)
    choices = [
        wanted(project, "puma", "5.6.9", new="5.6.9"),
        wanted(project, "rack", "2.2.8.1"),
        wanted(project, "mustermann", "2.0.2"),
        wanted(project, "nio4r", "2.5.9", direct=False),
    ]

    _, _, (result,) = apply(root, choices, report, source)

    assert tools.commands() == ["bundle lock", "bundle lock"]
    pinned, final = tools.calls
    assert pinned.files["Gemfile"].endswith('gem "minitest", "~> 5.15", group: :test\n'
                                            'gem "nio4r", "= 2.5.9"\n')  # fmt: skip
    assert 'gem "rack", "= 2.2.8.1"' in pinned.files["Gemfile"]
    assert 'gem "puma", "= 5.6.9"' in pinned.files["Gemfile"]
    assert 'add_dependency "mustermann", "= 2.0.2"' in pinned.files["demo.gemspec"]
    assert final.files["Gemfile"] == (PROJECTS / "bundler" / "Gemfile").read_text(
        encoding="utf-8"
    ).replace('"5.6.4"', '"5.6.9"')
    assert final.files["demo.gemspec"] == (PROJECTS / "bundler" / "demo.gemspec").read_text(
        encoding="utf-8"
    )
    assert pinned.cwd == root
    assert pinned.env["BUNDLE_GEMFILE"] == str(root / "Gemfile")
    assert pinned.env["BUNDLE_LOCKFILE"] == str(root / "Gemfile.lock")
    assert "BUNDLE_FORCE_RUBY_PLATFORM" not in pinned.env
    assert result.status is LockStatus.REGENERATED, result.error
    assert [(i.update.name, i.versions, i.reach) for i in result.installed] == [
        ("puma", ("5.6.9",), Reach.EXACT),
        ("rack", ("2.2.8.1",), Reach.EXACT),
        ("mustermann", ("2.0.2",), Reach.EXACT),
        ("nio4r", ("2.5.9",), Reach.EXACT),
    ]
    assert result.changed == () and result.warnings == ()
    gems = locked_gems(root)
    assert (gems["rack"], gems["sinatra"], gems["nokogiri"]) == ("2.2.8.1", "2.2.2", "1.19.0")


def test_a_refused_pin_falls_back_to_the_highest_allowed(tmp_path: Path, fake_tools: Tools) -> None:
    """Une version qu'une autre gem empêche (rack-protection = 2.2.4, quand sinatra 2.2.2 exige
    = 2.2.2) : Bundler refuse l'épinglage ; forceupdate le dit, puis ``bundle lock --update``,
    qui monte rack aussi haut que permis et laisse rack-protection, retenue par sinatra."""
    root = bundler_copy(tmp_path)
    tools = fake_tools("bundle")
    tools.handlers["bundle"] = FakeBundler(refuse=("rack-protection",))
    source, report = analyse(root)
    project = project_of(report)
    choices = [
        wanted(project, "rack", "2.2.8.1"),
        wanted(project, "rack-protection", "2.2.4", direct=False),
    ]

    _, _, (result,) = apply(root, choices, report, source)

    assert tools.commands() == [
        "bundle lock",
        "bundle lock --update rack rack-protection --conservative",
        "bundle lock",
    ]
    assert result.status is LockStatus.REGENERATED, result.error
    assert result.warnings == ("Versions exactes refusées : « bundle lock » a échoué (code 6) :",)
    assert [(i.update.name, i.versions, i.reach, i.held_by) for i in result.installed] == [
        ("rack", ("2.2.25",), Reach.ABOVE, ()),
        ("rack-protection", ("2.2.2",), Reach.BELOW, ("sinatra 2.2.2",)),
    ]


def test_the_platform_bundler_adds_is_removed(tmp_path: Path, fake_tools: Tools) -> None:
    """Sous Windows, Bundler ajoute sa plateforme au lockfile d'un projet Linux : elle est
    retirée ensuite (vérifié avec Bundler 4.0.20 : ``--remove-platform`` ne change aucune
    version). Sa version, écrite dans BUNDLED WITH, est dite."""
    root = bundler_copy(tmp_path)
    lock = root / "Gemfile.lock"
    lock.write_text(lock.read_text(encoding="utf-8").replace("  x64-mingw-ucrt\n", ""), "utf-8")
    tools = fake_tools("bundle")
    tools.handlers["bundle"] = FakeBundler(local="x64-mingw-ucrt", bundled_with="4.1.0")
    source, report = analyse(root)
    choice = wanted(project_of(report), "rack", "2.2.8.1")

    _, _, (result,) = apply(root, [choice], report, source)

    assert tools.commands() == [
        "bundle lock",
        "bundle lock",
        "bundle lock --remove-platform x64-mingw-ucrt",
    ]
    assert result.status is LockStatus.REGENERATED, result.error
    assert "PLATFORMS\n  x86_64-linux\n\nDEPENDENCIES" in lock.read_text(encoding="utf-8")
    assert result.warnings == ("Bundler a changé BUNDLED WITH dans le lockfile : 4.0.20 → 4.1.0.",)


def test_an_indirect_without_room_at_the_end_of_the_gemfile(
    tmp_path: Path, fake_tools: Tools
) -> None:
    """Après ``__END__``, une ligne ajoutée ne serait pas lue : l'indirecte passe par
    ``--update``."""
    root = bundler_copy(tmp_path)
    gemfile = root / "Gemfile"
    gemfile.write_text(gemfile.read_text(encoding="utf-8") + "__END__\nnotes\n", "utf-8")
    tools = fake_tools("bundle")
    tools.handlers["bundle"] = FakeBundler()
    source, report = analyse(root)
    project = project_of(report)
    choices = [
        wanted(project, "rack", "2.2.8.1"),
        wanted(project, "nio4r", "2.5.9", direct=False),
    ]
    _, _, (result,) = apply(root, choices, report, source)
    assert tools.commands() == [
        "bundle lock",
        "bundle lock --update nio4r --conservative",
        "bundle lock",
    ]
    assert [(i.update.name, i.reach) for i in result.installed] == [
        ("rack", Reach.EXACT),
        ("nio4r", Reach.ABOVE),
    ]


def test_a_strange_gem_name_is_never_written_in_the_gemfile(
    tmp_path: Path, fake_tools: Tools
) -> None:
    """Le nom d'une indirecte vient du lockfile : un nom qui n'est pas celui d'une gem (un
    guillemet ferait du Ruby dans le ``Gemfile``) passe par ``--update``."""
    root = bundler_copy(tmp_path)
    lock = root / "Gemfile.lock"
    text = lock.read_text(encoding="utf-8")
    text = text.replace("      nio4r (~> 2.0)\n", '      nio4r (~> 2.0)\n      x"; y\n')
    lock.write_text(text.replace("    racc (1.6.0)\n", '    racc (1.6.0)\n    x"; y (1.0)\n'))
    tools = fake_tools("bundle")
    tools.handlers["bundle"] = FakeBundler()
    tools.watch(root / "Gemfile")
    source, report = analyse(root)
    choice = wanted(project_of(report), 'x"; y', "1.1", direct=False)
    apply(root, [choice], report, source)
    assert tools.commands() == ['bundle lock --update x"; y --conservative', "bundle lock"]
    assert all('x"; y' not in call.files["Gemfile"] for call in tools.calls)


@pytest.mark.parametrize(
    "where", ["environment", ".bundle/config", "Gemfile", "nowhere", "environment=0"]
)
def test_the_cooldown_is_said(
    tmp_path: Path, fake_tools: Tools, monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    root = bundler_copy(tmp_path)
    if where.startswith("environment"):
        monkeypatch.setenv("BUNDLE_COOLDOWN", "0" if where.endswith("=0") else "7")
    elif where == ".bundle/config":
        (root / ".bundle").mkdir()
        (root / ".bundle" / "config").write_text('---\nBUNDLE_COOLDOWN: "7"\n', "utf-8")
    elif where == "Gemfile":
        gemfile = root / "Gemfile"
        text = gemfile.read_text(encoding="utf-8")
        gemfile.write_text(text.replace('rubygems.org"', 'rubygems.org", cooldown: 7'), "utf-8")
    fake_tools("bundle")
    source, report = analyse(root)
    choice = wanted(project_of(report), "rack", "2.2.8.1")
    (job,) = lockfiles.plan(source, report, writers.prepare(root, [choice]))
    cooldown = (
        "Bundler écarte les versions publiées depuis peu (cooldown) : une version visée trop "
        "récente n'est pas prise, la plus haute permise plus ancienne l'est à sa place."
    )
    said = where not in ("nowhere", "environment=0")
    assert job.warnings == ((BUNDLER_RUNS_CODE, cooldown) if said else (BUNDLER_RUNS_CODE,))


def test_a_bundler_failure_puts_every_file_back(tmp_path: Path, fake_tools: Tools) -> None:
    root = bundler_copy(tmp_path)
    before = {name: (root / name).read_bytes() for name in ("Gemfile", "Gemfile.lock")}
    tools = fake_tools("bundle")
    tools.handlers["bundle"] = lambda call: (6, "", "Could not find compatible versions")
    source, report = analyse(root)
    choice = wanted(project_of(report), "puma", "7.2.1", new="7.2.1")

    _, _, (result,) = apply(root, [choice], report, source)

    assert result.status is LockStatus.FAILED
    assert result.error is not None and "Could not find compatible versions" in result.error
    assert result.restored == ("Gemfile",)
    assert {name: (root / name).read_bytes() for name in before} == before


# ---------------------------------------------------------------------------
# Les vrais outils (réseau), sur des copies
# ---------------------------------------------------------------------------


def _need(program: str) -> None:
    if shutil.which(program) is None:
        pytest.skip(f"{program} n'est pas installé")


@pytest.mark.network
def test_the_real_npm(tmp_path: Path) -> None:
    _need("npm")
    root = tmp_path / "vulnerable"
    shutil.copytree(PROJECTS / "vulnerable", root)
    (root / "requirements.in").unlink()
    (root / "requirements.txt").unlink()
    source, report = analyse(root)
    choice = wanted(project_of(report), "lodash", "4.18.1", new="4.18.1")
    _, _, (result,) = apply(root, [choice], report, source)
    assert result.status is LockStatus.REGENERATED, result.error
    assert result.installed[0].reach is Reach.EXACT
    lock = json.loads((root / "package-lock.json").read_text(encoding="utf-8"))
    assert lock["packages"][""]["dependencies"] == {"lodash": "4.18.1"}
    assert lock["packages"]["node_modules/lodash"]["version"] == "4.18.1"


@pytest.mark.network
def test_the_real_npm_reaches_a_version_below_the_highest(tmp_path: Path) -> None:
    """``^4.17.15`` accepte 4.18.1 ; on demande 4.17.21, et la contrainte ne change pas."""
    _need("npm")
    root = tmp_path / "vulnerable"
    shutil.copytree(PROJECTS / "vulnerable", root)
    manifest = root / "package.json"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace('"4.17.15"', '"^4.17.15"'), encoding="utf-8"
    )
    before = manifest.read_bytes()
    source, report = analyse(root)
    choice = wanted(project_of(report), "lodash", "4.17.21")
    _, _, results = apply(root, [choice], report, source)
    npm = next(r for r in results if r.job.kind is LockKind.NPM)
    assert npm.status is LockStatus.REGENERATED, npm.error
    assert npm.installed[0].reach is Reach.EXACT
    assert manifest.read_bytes() == before
    lock = json.loads((root / "package-lock.json").read_text(encoding="utf-8"))
    assert lock["packages"][""]["dependencies"] == {"lodash": "^4.17.15"}


@pytest.mark.network
def test_the_real_uv(tmp_path: Path) -> None:
    _need("uv")
    root = tmp_path / "uv"
    shutil.copytree(PROJECTS / "uv", root)
    source, report = analyse(root)
    choice = wanted(project_of(report), "pytest", "9.2.0")
    _, _, (result,) = apply(root, [choice], report, source)
    assert result.status is LockStatus.REGENERATED, result.error
    assert result.installed[0].reach is Reach.EXACT
    check = subprocess.run(
        ["uv", "lock", "--check", "--offline"], cwd=root, capture_output=True, timeout=120
    )
    assert check.returncode == 0, check.stderr


@pytest.mark.network
def test_the_real_pnpm_keeps_a_pinned_catalog_version(tmp_path: Path) -> None:
    _need("pnpm")
    root = tmp_path / "pnpm-catalog"
    shutil.copytree(PROJECTS / "pnpm-catalog", root)
    source, report = analyse(root)
    choice = wanted(project_of(report, "packages/app"), "is-odd", "3.0.0", new="^3.0.0")
    _, _, (result,) = apply(root, [choice], report, source)
    assert result.status is LockStatus.REGENERATED, result.error
    # ^3.0.0 accepte 3.0.1, mais c'est 3.0.0 qui était choisie.
    assert (result.installed[0].versions, result.installed[0].reach) == (("3.0.0",), Reach.EXACT)


@pytest.mark.network
def test_the_real_cargo(tmp_path: Path) -> None:
    """Une directe réécrite, une directe par le lockfile seul (sous la plus haute que permet sa
    contrainte), une indirecte : chacune à la version choisie ; le lockfile n'a plus rien à
    résoudre."""
    _need("cargo")
    root = cargo_copy(tmp_path)
    source, report = analyse(root)
    project = project_of(report)
    choices = [
        wanted(project, "regex", "1.6.0", new="=1.6.0"),
        wanted(project, "anyhow", "1.0.90"),
        wanted(project, "rand_core", "0.6.3", direct=False),
    ]
    _, _, (result,) = apply(root, choices, report, source)
    assert result.status is LockStatus.REGENERATED, result.error
    assert [(i.update.name, i.versions, i.reach) for i in result.installed] == [
        ("regex", ("1.6.0",), Reach.EXACT),
        ("anyhow", ("1.0.90",), Reach.EXACT),
        ("rand_core", ("0.6.3",), Reach.EXACT),
    ]
    check = subprocess.run(
        ["cargo", "update", "--workspace", "--locked"], cwd=root, capture_output=True, timeout=300
    )
    assert check.returncode == 0, check.stderr


@pytest.mark.network
def test_the_real_go(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Une directe et une indirecte réécrites dans ``go.mod`` : ``go mod tidy`` les garde, refait
    ``go.sum``, et n'a plus rien à changer ensuite (``go mod tidy -diff``). Les modules et les
    caches de ``go`` vont dans le dossier du test, pas dans ceux de la personne."""
    _need("go")
    for name in ("GOPATH", "GOMODCACHE", "GOCACHE"):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))
    root = go_copy(tmp_path)
    source, report = analyse(root)
    project = project_of(report)
    choices = [
        wanted(project, "github.com/golang-jwt/jwt/v4", "v4.5.2", new="v4.5.2"),
        wanted(project, "gopkg.in/yaml.v3", "v3.0.1", new="v3.0.1", direct=False),
    ]
    _, _, (result,) = apply(root, choices, report, source)
    assert result.status is LockStatus.REGENERATED, result.error
    assert [(i.update.name, i.versions, i.reach) for i in result.installed] == [
        ("github.com/golang-jwt/jwt/v4", ("v4.5.2",), Reach.EXACT),
        ("gopkg.in/yaml.v3", ("v3.0.1",), Reach.EXACT),
    ]
    go_sum = (root / "go.sum").read_text(encoding="utf-8")
    assert "github.com/golang-jwt/jwt/v4 v4.5.2 h1:" in go_sum
    assert "github.com/golang-jwt/jwt/v4 v4.4.0 h1:" not in go_sum
    check = subprocess.run(
        ["go", "mod", "tidy", "-diff"],
        cwd=root,
        capture_output=True,
        timeout=300,
        env={**os.environ, "GOTOOLCHAIN": "local", "GOFLAGS": "-mod=mod"},
    )
    assert check.returncode == 0, check.stdout + check.stderr


@pytest.mark.network
def test_the_real_composer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Une directe réécrite, deux directes par le lockfile seul (monolog sous son ``conflict``),
    une indirecte : chacune à la version choisie, même guzzle 7.4.5, twig 3.4.3 et psr7 2.4.5, qui
    ont encore des failles (Composer les refuserait sans COMPOSER_POLICY_ADVISORIES_BLOCK=0) ; le
    script du projet ne tourne pas, et Composer tient ensuite le lockfile pour à jour. Son cache
    et sa configuration vont dans le dossier du test."""
    _need("composer")
    for name in ("COMPOSER_HOME", "COMPOSER_CACHE_DIR"):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))
    root = composer_copy(tmp_path)
    source, report = analyse(root)
    project = project_of(report)
    choices = [
        wanted(project, "guzzlehttp/guzzle", "7.4.5", new="7.4.5"),
        wanted(project, "twig/twig", "v3.4.3"),
        wanted(project, "monolog/monolog", "2.10.0"),
        wanted(project, "guzzlehttp/psr7", "2.4.5", direct=False),
    ]
    _, _, (result,) = apply(root, choices, report, source)
    assert result.status is LockStatus.REGENERATED, result.error
    assert [(i.update.name, i.versions, i.reach) for i in result.installed] == [
        ("guzzlehttp/guzzle", ("7.4.5",), Reach.EXACT),
        ("twig/twig", ("v3.4.3",), Reach.EXACT),
        ("monolog/monolog", ("2.10.0",), Reach.EXACT),
        ("guzzlehttp/psr7", ("2.4.5",), Reach.EXACT),
    ]
    assert result.changed == ()  # COMPOSER_MINIMAL_CHANGES : rien d'autre ne bouge
    assert not (root / "script-ran.txt").exists() and not (root / "vendor").exists()
    check = subprocess.run(
        [shutil.which("composer") or "composer", "validate", "--no-check-publish", "--no-ansi"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert "not up to date" not in check.stdout + check.stderr


@pytest.mark.network
def test_the_real_bundler(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Une directe réécrite, une directe par le lockfile seul, une du ``.gemspec``, celle de la
    gem locale (helper), une indirecte : chacune à la version choisie, rien d'autre ne bouge, le
    ``Gemfile`` et les ``.gemspec`` sont remis. Le lockfile n'a pas la plateforme de la machine
    (retirée d'abord par Bundler) : Bundler l'ajoute, forceupdate la retire. Le cache et les gems
    de Bundler vont dans le dossier du test."""
    _need("bundle")
    for name in ("BUNDLE_USER_HOME", "GEM_HOME", "GEM_SPEC_CACHE"):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))
    root = bundler_copy(tmp_path)
    bundle = shutil.which("bundle") or "bundle"
    ruby_program = shutil.which("ruby") or "ruby"
    local = subprocess.run(
        [ruby_program, "-e", "print Gem::Platform.local"], capture_output=True, text=True
    ).stdout.strip()
    lock = root / "Gemfile.lock"
    if f"\n  {local}\n" in lock.read_text(encoding="utf-8"):
        removed = subprocess.run(
            [bundle, "lock", "--remove-platform", local],
            cwd=root,
            capture_output=True,
            timeout=300,
            env={**os.environ, "BUNDLE_GEMFILE": str(root / "Gemfile")},
        )
        assert removed.returncode == 0, removed.stderr
    platforms = ruby.parse_gemfile_lock("Gemfile.lock", lock.read_text("utf-8")).platforms
    assert local not in platforms
    before = {p: (root / p).read_text("utf-8") for p in ("demo.gemspec", "helper/helper.gemspec")}
    source, report = analyse(root)
    project = project_of(report)
    choices = [
        wanted(project, "puma", "5.6.9", new="5.6.9"),
        wanted(project, "rack", "2.2.8.1"),
        wanted(project, "mustermann", "2.0.2"),
        wanted(project_of(report, "helper"), "json", "2.10.2"),
        wanted(project, "nio4r", "2.5.9", direct=False),
    ]
    _, _, (result,) = apply(root, choices, report, source)
    assert result.status is LockStatus.REGENERATED, result.error
    assert [(i.update.name, i.versions, i.reach) for i in result.installed] == [
        ("puma", ("5.6.9",), Reach.EXACT),
        ("rack", ("2.2.8.1",), Reach.EXACT),
        ("mustermann", ("2.0.2",), Reach.EXACT),
        ("json", ("2.10.2",), Reach.EXACT),
        ("nio4r", ("2.5.9",), Reach.EXACT),
    ]
    assert result.changed == ()
    parsed = ruby.parse_gemfile_lock("Gemfile.lock", lock.read_text("utf-8"))
    assert parsed.platforms == platforms
    assert parsed.requirements["puma"] == "= 5.6.9" and "nio4r" not in parsed.requirements
    gemfile = (PROJECTS / "bundler" / "Gemfile").read_text("utf-8").replace('"5.6.4"', '"5.6.9"')
    assert (root / "Gemfile").read_text("utf-8") == gemfile
    assert {p: (root / p).read_text("utf-8") for p in before} == before


# ---------------------------------------------------------------------------
# NuGet
# ---------------------------------------------------------------------------

DOTNET_RUNS_CODE = (
    "dotnet restore évalue le projet avec MSBuild : une cible du projet ou de ses "
    "Directory.Build.targets accrochée à la restauration s'exécute, comme un SDK de projet venu de "
    "NuGet ; il écrit aussi le dossier obj/ du projet."
)
RESTORE = "--force-evaluate -noAutoResponse -p:RestoreLockedMode=false"


class FakeDotnet:
    """``dotnet --list-sdks`` (un SDK installé, sauf ``sdk=False``), et ``dotnet restore`` : le
    ``packages.lock.json`` du dossier prend les versions de ``versions`` (``requested`` aussi pour
    une directe), comme NuGet, qui prend la borne basse réécrite."""

    def __init__(self, versions: dict[str, str] | None = None, *, sdk: bool = True) -> None:
        self.versions = versions or {}
        self.sdk = sdk

    def __call__(self, call: ToolCall) -> tuple[int, str, str] | None:
        if call.arguments == ["--list-sdks"]:
            listed = "10.0.403 [C:\\Program Files\\dotnet\\sdk]\n" if self.sdk else ""
            return 0, listed, ""
        assert call.arguments[0] == "restore"
        lock = call.cwd / "packages.lock.json"
        data = json.loads(lock.read_text(encoding="utf-8"))
        for packages in data["dependencies"].values():
            for name, entry in packages.items():
                if name in self.versions:
                    entry["resolved"] = self.versions[name]
                    if "requested" in entry:
                        entry["requested"] = f"[{self.versions[name]}, )"
        lock.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return None


def nuget_copy(tmp_path: Path) -> Path:
    root = tmp_path / "nuget"
    shutil.copytree(PROJECTS / "nuget", root)
    return root


def test_plan_of_a_nuget_lock(tmp_path: Path, fake_tools: Tools) -> None:
    """Une version centrale réécrite : le lockfile de la mise à jour, et celui de l'autre projet
    qui la lit (une ``CentralTransitive``), avec la raison."""
    root = nuget_copy(tmp_path)
    tools = fake_tools("dotnet")
    tools.handlers["dotnet"] = FakeDotnet()
    source, report = analyse(root)
    choice = wanted(
        project_of(report, "src/App"), "Microsoft.AspNetCore.Http", "2.1.22", new="2.1.22"
    )
    app, tests = lockfiles.plan(source, report, writers.prepare(root, [choice]))
    assert (app.lockfile, app.kind, app.program, app.tool) == (
        "src/App/packages.lock.json",
        LockKind.NUGET,
        "/outils/dotnet",
        "dotnet",
    )
    assert app.command == "dotnet restore App.csproj --force-evaluate"
    assert (app.inputs, app.warnings, app.reason) == (
        ("Directory.Packages.props",),
        (DOTNET_RUNS_CODE,),
        None,
    )
    assert (tests.lockfile, tests.choices, tests.reason, tests.inputs) == (
        "src/App.Tests/packages.lock.json",
        (),
        "Directory.Packages.props a changé",
        ("Directory.Packages.props",),
    )
    assert tests.command == "dotnet restore App.Tests.csproj --force-evaluate"


def test_dotnet_without_an_sdk_is_missing(tmp_path: Path, fake_tools: Tools) -> None:
    """Le ``dotnet`` des runtimes seuls ne sait pas restaurer : la commande est à lancer à la
    main, les manifestes restent réécrits."""
    root = nuget_copy(tmp_path)
    tools = fake_tools("dotnet")
    tools.handlers["dotnet"] = FakeDotnet(sdk=False)
    source, report = analyse(root)
    choice = wanted(project_of(report, "src/App.Tests"), "Newtonsoft.Json", "13.0.3", new="13.0.3")
    _, (job,), (result,) = apply(root, [choice], report, source)
    assert job.program is None
    assert result.status is LockStatus.TOOL_MISSING
    manifest = root / "src" / "App.Tests" / "App.Tests.csproj"
    assert 'VersionOverride="13.0.3"' in manifest.read_text(encoding="utf-8")
    assert tools.commands() == ["dotnet --list-sdks"]


def test_dotnet_restore_regenerates_both_lockfiles(
    tmp_path: Path, fake_tools: Tools, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RestoreLockedMode", "true")
    root = nuget_copy(tmp_path)
    tools = fake_tools("dotnet")
    tools.handlers["dotnet"] = FakeDotnet({"Microsoft.AspNetCore.Http": "2.1.22"})
    source, report = analyse(root)
    choice = wanted(
        project_of(report, "src/App"), "Microsoft.AspNetCore.Http", "2.1.22", new="2.1.22"
    )

    _, _, (app, tests) = apply(root, [choice], report, source)

    assert tools.commands() == [
        "dotnet --list-sdks",
        "dotnet --list-sdks",
        f"dotnet restore App.csproj {RESTORE}",
        f"dotnet restore App.Tests.csproj {RESTORE}",
    ]
    restore = tools.calls[2]
    assert restore.cwd == root / "src" / "App"
    assert {k: restore.env[k] for k in ("DOTNET_NOLOGO", "DOTNET_CLI_TELEMETRY_OPTOUT")} == {
        "DOTNET_NOLOGO": "1",
        "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
    }
    assert restore.env["MSBUILDDISABLENODEREUSE"] == "1"
    assert (app.status, tests.status) == (LockStatus.REGENERATED, LockStatus.REGENERATED)
    assert [(i.update.name, i.versions, i.reach) for i in app.installed] == [
        ("Microsoft.AspNetCore.Http", ("2.1.22",), Reach.EXACT)
    ]
    assert tests.installed == ()
    assert tests.changed == ("Microsoft.AspNetCore.Http 2.1.0 → 2.1.22",)


def test_a_nuget_failure_puts_every_file_back(tmp_path: Path, fake_tools: Tools) -> None:
    root = nuget_copy(tmp_path)
    names = ("Directory.Packages.props", "src/App/packages.lock.json")
    before = {name: (root / name).read_bytes() for name in names}
    tools = fake_tools("dotnet")
    fake = FakeDotnet()
    tools.handlers["dotnet"] = lambda call: (
        fake(call)
        if call.arguments == ["--list-sdks"]
        else (1, "error NU1102: Unable to find package", "")
    )
    source, report = analyse(root)
    choice = wanted(project_of(report, "src/App"), "Newtonsoft.Json", "13.0.1", new="13.0.1")

    _, _, (result,) = apply(root, [choice], report, source)

    assert result.status is LockStatus.FAILED
    assert result.error is not None and "NU1102" in result.error
    assert result.restored == ("Directory.Packages.props",)
    assert {name: (root / name).read_bytes() for name in names} == before


def test_dotnet_says_what_it_does_not_do(tmp_path: Path, fake_tools: Tools) -> None:
    """Le SDK que demande ``global.json`` ; les sources de paquets de ``nuget.config``."""
    root = nuget_copy(tmp_path)
    (root / "global.json").write_text('{ "sdk": { "version": "9.0.100" } }', encoding="utf-8")
    (root / "src" / "nuget.config").write_text("<configuration />", encoding="utf-8")
    tools = fake_tools("dotnet")
    tools.handlers["dotnet"] = FakeDotnet()
    source, report = analyse(root)
    choice = wanted(project_of(report, "src/App.Tests"), "Newtonsoft.Json", "13.0.3", new="13.0.3")
    (job,) = lockfiles.plan(source, report, writers.prepare(root, [choice]))
    assert job.warnings == (
        DOTNET_RUNS_CODE,
        "global.json demande le SDK .NET 9.0.100 : dotnet échoue s'il n'est pas installé (rien "
        "ne change alors).",
        "src/nuget.config : ses sources de paquets servent à la restauration ; forceupdate a "
        "cherché les versions sur nuget.org.",
    )


@pytest.mark.network
def test_the_real_dotnet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Une version centrale, une propriété de ``Directory.Build.props`` et une ``VersionOverride``
    réécrites : ``dotnet restore`` prend chaque borne basse (la plus basse qui convient), dans les
    deux lockfiles ; rien d'autre ne bouge que ce que tirent ces versions. Les paquets et la
    configuration de dotnet vont dans le dossier du test."""
    _need("dotnet")
    if not lockfiles._dotnet_sdk(shutil.which("dotnet") or "dotnet"):
        pytest.skip("dotnet n'a pas de SDK")
    monkeypatch.setenv("NUGET_PACKAGES", str(tmp_path / "packages"))
    monkeypatch.setenv("DOTNET_CLI_HOME", str(tmp_path / "home"))
    root = nuget_copy(tmp_path)
    source, report = analyse(root)
    app = project_of(report, "src/App")
    tests = project_of(report, "src/App.Tests")
    choices = [
        wanted(app, "Microsoft.AspNetCore.Http", "2.1.22", new="2.1.22"),
        wanted(app, "Serilog", "2.12.0", new="2.12.0"),
        wanted(tests, "Newtonsoft.Json", "13.0.3", new="13.0.3"),
    ]
    _, _, results = apply(root, choices, report, source)
    assert [r.status for r in results] == [LockStatus.REGENERATED] * 2, [r.error for r in results]
    installed = sorted((i.update.name, i.versions, i.reach) for r in results for i in r.installed)
    assert installed == [
        ("Microsoft.AspNetCore.Http", ("2.1.22",), Reach.EXACT),
        ("Newtonsoft.Json", ("13.0.3",), Reach.EXACT),
        ("Serilog", ("2.12.0",), Reach.EXACT),
    ]
    assert (root / "src" / "App" / "obj").is_dir()
