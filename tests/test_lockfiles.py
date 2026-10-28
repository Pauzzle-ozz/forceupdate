"""La régénération des lockfiles (E11) : quelle commande pour quel lockfile, la version visée,
ce qu'on relit ensuite, et la remise en état quand l'outil échoue.

Les outils sont simulés (``FakeTools`` de ``tests/conftest.py``) : un faux outil écrit le
lockfile que le vrai aurait écrit. Les vrais npm, uv et pnpm ne sont lancés que dans les tests
``network``, sur des copies des mini-projets."""

import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import FakeTools, ToolCall

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
from forceupdate.parsers import parse_lockfile
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
    lockfile = next(d.lockfile for d in found if d.lockfile)
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
        parse_lockfile("Cargo.lock", "")


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
