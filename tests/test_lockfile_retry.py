"""Un lockfile qu'une majeure fait échouer (session 37) : l'outil est relancé sans les majeures,
puis avec chacune en plus ; celles qu'il refuse sont retirées, avec sa raison, et le reste est
fait. Avant, une seule majeure incompatible (``redis`` 8 que ``arq`` refuse) faisait tomber toutes
les mises à jour du lockfile, failles comprises.

Aussi : ce qu'on garde de la sortie d'un outil (``_why``), et les chemins de l'ordinateur qu'on en
retire (``_redact``) : elle va dans la description d'une PR."""

import re
from collections.abc import Callable
from pathlib import Path

from conftest import FakeTools, ToolCall, UserFiles
from rich.console import Console

from forceupdate import engine, userfiles
from forceupdate.forges.base import ForgeKind, Repository
from forceupdate.models import (
    Edit,
    EditKind,
    Gap,
    Project,
    Report,
    Update,
    UpdateOption,
    UpdateReason,
)
from forceupdate.report import terminal
from forceupdate.sources.local import LocalSource
from forceupdate.update import forge, local, lockfiles, writers
from forceupdate.update.lockfiles import LockStatus, Reach, Regenerated, _redact, _why
from forceupdate.update.writers import Choice

MakeTree = Callable[..., Path]
Tools = Callable[..., FakeTools]

PYPROJECT = """\
[project]
name = "demo"
version = "0.1.0"
dependencies = [
    "arq>=0.26",
    "click>=8.1",
    "httpx>=0.27",
    "redis>=5.0",
]
"""

LOCKED = {"arq": "0.28.0", "click": "8.1.0", "httpx": "0.27.0", "redis": "5.0.1"}


def uv_lock(versions: dict[str, str]) -> str:
    """Un ``uv.lock`` : le projet, puis chaque paquet à sa version."""
    lines = [
        "version = 1",
        'requires-python = ">=3.11"',
        "",
        "[[package]]",
        'name = "demo"',
        'version = "0.1.0"',
        'source = { virtual = "." }',
        "dependencies = [" + ", ".join(f'{{ name = "{n}" }}' for n in sorted(versions)) + "]",
    ]
    for name, version in sorted(versions.items()):
        lines += [
            "",
            "[[package]]",
            f'name = "{name}"',
            f'version = "{version}"',
            'source = { registry = "https://pypi.org/simple" }',
        ]
    return "\n".join(lines) + "\n"


REFUSED = f"""\
  {chr(0xD7)} No solution found when resolving dependencies:
  ╰─▶ Because arq==0.28.0 depends on redis<6 and your project depends on
      redis>=8.1.0, we can conclude that your project's requirements are
      unsatisfiable.
"""
"""Ce que dit uv 0.10, habillé de ses signes."""


class FakeUv:
    """``uv lock -P x==V…`` : refuse ``redis`` 8 (``arq`` demande ``redis<6``), sinon écrit
    chaque version visée dans le ``uv.lock``."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.seen: list[list[str]] = []

    def __call__(self, call: ToolCall) -> tuple[int, str, str] | None:
        pins = [word for word in call.arguments if "==" in word]
        self.seen.append(pins)
        if "redis==8.1.0" in pins:
            return 1, "", REFUSED
        versions = dict(LOCKED)
        versions.update(pin.split("==") for pin in pins)
        (self.root / "uv.lock").write_text(uv_lock(versions), encoding="utf-8")
        return None


def analyse(root: Path) -> tuple[LocalSource, Report]:
    source = LocalSource(root)
    return source, engine.inventory(source)


def wanted(project: Project, name: str, version: str, new: str, gap: Gap) -> Choice:
    """La mise à jour de ``name`` vers ``version``, sa contrainte réécrite en ``new``."""
    (dependency,) = [d for d in project.dependencies if d.name == name and d.direct]
    edit = Edit(
        kind=EditKind.DEPENDENCY,
        file=dependency.file,
        location=dependency.location,
        old=dependency.effective_constraint,
        new=new,
    )
    update = Update(
        id=f"{project.path}|{name}",
        ecosystem=dependency.ecosystem,
        name=name,
        direct=True,
        dependencies=(dependency,),
        current_version=dependency.installed,
    )
    reason = UpdateReason.LATEST_MAJOR if gap is Gap.MAJOR else UpdateReason.LATEST_MINOR
    option = UpdateOption(
        version=version, gap=gap, reasons=(reason,), edits=(edit,), lockfile=dependency.lockfile
    )
    return project, update, option


def run(root: Path, choices: list[Choice]) -> tuple[writers.Changes, Regenerated]:
    source, report = analyse(root)
    changes = writers.prepare(root, choices)
    jobs = lockfiles.plan(source, report, changes)
    writers.write(root, changes)
    (result,) = lockfiles.regenerate(source, report, changes, jobs)
    return changes, result


def project(make_tree: MakeTree) -> tuple[Path, Project]:
    root = make_tree({"pyproject.toml": PYPROJECT, "uv.lock": uv_lock(LOCKED)})
    _, report = analyse(root)
    return root, next(p for p in report.projects if p.path == ".")


def test_the_major_the_tool_refuses_is_dropped_and_the_rest_is_done(
    make_tree: MakeTree, fake_tools: Tools
) -> None:
    root, demo = project(make_tree)
    tools = fake_tools("uv")
    uv = FakeUv(root)
    tools.handlers["uv"] = uv
    httpx = wanted(demo, "httpx", "0.28.1", ">=0.28.1", Gap.MINOR)
    redis = wanted(demo, "redis", "8.1.0", ">=8.1.0", Gap.MAJOR)
    click = wanted(demo, "click", "9.0.0", ">=9.0.0", Gap.MAJOR)

    _, result = run(root, [httpx, redis, click])

    # Toutes, puis sans les majeures, puis chacune en plus.
    assert uv.seen == [
        ["httpx==0.28.1", "redis==8.1.0", "click==9.0.0"],
        ["httpx==0.28.1"],
        ["httpx==0.28.1", "redis==8.1.0"],
        ["httpx==0.28.1", "click==9.0.0"],
    ]
    assert result.status is LockStatus.REGENERATED
    assert [(d.update.name, d.option.version) for d in result.dropped] == [("redis", "8.1.0")]
    assert result.dropped[0].reason == (
        "Because arq==0.28.0 depends on redis<6 and your project depends on redis>=8.1.0, we "
        "can conclude that your project's requirements are unsatisfiable."
    )
    assert result.warnings == ()
    assert [(i.update.name, i.reach) for i in result.installed] == [
        ("httpx", Reach.EXACT),
        ("click", Reach.EXACT),
    ]
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert '"httpx>=0.28.1"' in text
    assert '"click>=9.0.0"' in text
    assert '"redis>=5.0"' in text  # remise comme avant
    lock = (root / "uv.lock").read_text(encoding="utf-8")
    assert 'name = "redis"\nversion = "5.0.1"' in lock
    assert 'name = "httpx"\nversion = "0.28.1"' in lock


def test_a_single_major_is_not_tried_again_alone(make_tree: MakeTree, fake_tools: Tools) -> None:
    root, demo = project(make_tree)
    tools = fake_tools("uv")
    uv = FakeUv(root)
    tools.handlers["uv"] = uv
    httpx = wanted(demo, "httpx", "0.28.1", ">=0.28.1", Gap.MINOR)
    redis = wanted(demo, "redis", "8.1.0", ">=8.1.0", Gap.MAJOR)

    _, result = run(root, [httpx, redis])

    # Elle et les autres : c'est le premier essai, qui a échoué.
    assert uv.seen == [["httpx==0.28.1", "redis==8.1.0"], ["httpx==0.28.1"]]
    assert result.status is LockStatus.REGENERATED
    assert [d.update.name for d in result.dropped] == ["redis"]
    assert result.dropped[0].reason.startswith("Because arq==0.28.0 depends on redis<6")


def test_still_failing_without_the_majors_fails_as_before(
    make_tree: MakeTree, fake_tools: Tools
) -> None:
    root, demo = project(make_tree)
    before = {name: (root / name).read_bytes() for name in ("pyproject.toml", "uv.lock")}
    tools = fake_tools("uv")
    calls: list[list[str]] = []

    def uv(call: ToolCall) -> tuple[int, str, str]:
        calls.append(call.arguments)
        return 2, "", "error: réseau coupé\n"

    tools.handlers["uv"] = uv
    httpx = wanted(demo, "httpx", "0.28.1", ">=0.28.1", Gap.MINOR)
    redis = wanted(demo, "redis", "8.1.0", ">=8.1.0", Gap.MAJOR)

    _, result = run(root, [httpx, redis])

    assert len(calls) == 2
    assert result.status is LockStatus.FAILED
    assert result.error == (
        "« uv lock -P httpx==0.28.1 -P redis==8.1.0 » a échoué (code 2) :\nerror: réseau coupé"
    )
    assert result.dropped == ()
    assert {name: (root / name).read_bytes() for name in before} == before


def test_without_a_major_nothing_is_tried_again(make_tree: MakeTree, fake_tools: Tools) -> None:
    root, demo = project(make_tree)
    tools = fake_tools("uv")
    calls: list[list[str]] = []

    def uv(call: ToolCall) -> tuple[int, str, str]:
        calls.append(call.arguments)
        return 1, "", "error: non\n"

    tools.handlers["uv"] = uv
    httpx = wanted(demo, "httpx", "0.28.1", ">=0.28.1", Gap.MINOR)
    click = wanted(demo, "click", "8.2.0", ">=8.2.0", Gap.MINOR)

    _, result = run(root, [httpx, click])

    assert len(calls) == 1
    assert result.status is LockStatus.FAILED


def test_every_major_refused_leaves_only_the_others(make_tree: MakeTree, fake_tools: Tools) -> None:
    root, demo = project(make_tree)
    tools = fake_tools("uv")
    seen: list[list[str]] = []

    def uv(call: ToolCall) -> tuple[int, str, str] | None:
        pins = [word for word in call.arguments if "==" in word]
        seen.append(pins)
        if any(pin.startswith(("redis==", "click==9")) for pin in pins):
            return 1, "", REFUSED
        versions = dict(LOCKED)
        versions.update(pin.split("==") for pin in pins)
        (root / "uv.lock").write_text(uv_lock(versions), encoding="utf-8")
        return None

    tools.handlers["uv"] = uv
    choices = [
        wanted(demo, "httpx", "0.28.1", ">=0.28.1", Gap.MINOR),
        wanted(demo, "redis", "8.1.0", ">=8.1.0", Gap.MAJOR),
        wanted(demo, "click", "9.0.0", ">=9.0.0", Gap.MAJOR),
    ]

    _, result = run(root, choices)

    assert result.status is LockStatus.REGENERATED
    assert [d.update.name for d in result.dropped] == ["redis", "click"]
    assert [i.update.name for i in result.installed] == ["httpx"]
    assert '"click>=8.1"' in (root / "pyproject.toml").read_text(encoding="utf-8")


def test_the_pr_says_which_major_was_dropped_and_why(
    make_tree: MakeTree, fake_tools: Tools
) -> None:
    root, demo = project(make_tree)
    tools = fake_tools("uv")
    tools.handlers["uv"] = FakeUv(root)
    source, report = analyse(root)
    choices = [
        wanted(demo, "httpx", "0.28.1", ">=0.28.1", Gap.MINOR),
        wanted(demo, "redis", "8.1.0", ">=8.1.0", Gap.MAJOR),
    ]
    changes = writers.prepare(root, choices)
    jobs = lockfiles.plan(source, report, changes)
    writers.write(root, changes)
    results = lockfiles.regenerate(source, report, changes, jobs)
    prepared = local.Prepared(changes=changes, jobs=jobs)

    message = forge.commit_message(prepared, results)
    assert "httpx 0.27.0 → 0.28.1" in message
    assert "redis" not in message
    assert forge.committable(prepared, results) == ["pyproject.toml", "uv.lock"]
    repo = Repository(
        forge=ForgeKind.GITHUB,
        host="github.com",
        full_name="octo/demo",
        default_branch="main",
        private=True,
        archived=False,
        fork=False,
        can_push=True,
        url="https://github.com/octo/demo",
        clone_url="https://github.com/octo/demo.git",
    )
    body = forge.request_body(report, prepared, results, repo=repo, base="abc1234")
    row = next(line for line in body.splitlines() if line.startswith("| `redis`"))
    assert "pas faite : uv la refuse" in row
    assert (
        "  uv échouait avec toutes les mises à jour : régénéré sans redis 8.1.0, qu'il refuse "
        "(le tableau dit pourquoi)." in body
    )
    assert r"Because arq==0.28.0 depends on redis\<6" in row  # échappé pour Markdown


def test_the_commit_message_leaves_out_a_held_version(
    make_tree: MakeTree, fake_tools: Tools
) -> None:
    """Session 36 : le message disait « minimatch 10.2.6 → 11.0.1 », le lockfile gardait 10.2.6."""
    root, demo = project(make_tree)
    tools = fake_tools("uv")

    def uv(call: ToolCall) -> None:
        versions = dict(LOCKED, httpx="0.28.1", click="8.1.0")  # click reste en 8.1.0
        (root / "uv.lock").write_text(uv_lock(versions), encoding="utf-8")

    tools.handlers["uv"] = uv
    source, report = analyse(root)
    choices = [
        wanted(demo, "httpx", "0.28.1", ">=0.28.1", Gap.MINOR),
        wanted(demo, "click", "8.2.0", ">=8.1", Gap.MINOR),
    ]
    changes = writers.prepare(root, choices)
    jobs = lockfiles.plan(source, report, changes)
    writers.write(root, changes)
    results = lockfiles.regenerate(source, report, changes, jobs)
    assert [(i.update.name, i.reach) for i in results[0].installed] == [
        ("httpx", Reach.EXACT),
        ("click", Reach.BELOW),
    ]
    message = forge.commit_message(local.Prepared(changes=changes, jobs=jobs), results)
    assert "httpx 0.27.0 → 0.28.1" in message
    assert "click" not in message


# -- ce qu'on garde de la sortie d'un outil ---------------------------------------


ERESOLVE = """\
npm error code ERESOLVE
npm error ERESOLVE could not resolve
npm error
npm error While resolving: forceupdate-frontend@0.0.0
npm error Found: @vitejs/plugin-react@6.1.2
npm error node_modules/@vitejs/plugin-react
npm error   dev @vitejs/plugin-react@"6.2.1" from the root project
npm error
npm error Could not resolve dependency:
npm error dev @vitejs/plugin-react@"6.2.1" from the root project
npm error
npm error Conflicting peer dependency: @babel/core@8.1.0
npm error node_modules/@babel/core
npm error   peer @babel/core@"^8.0.0" from @babel/plugin-transform-runtime@8.0.6
npm error
npm error Fix the upstream dependency conflict, or retry
npm error this command with --force or --legacy-peer-deps
npm error to accept an incorrect (and potentially broken) dependency resolution.
"""


def test_why_npm_could_not_resolve() -> None:
    assert _why(ERESOLVE.splitlines()) == (
        'Could not resolve dependency: dev @vitejs/plugin-react@"6.2.1" from the root project ; '
        "Conflicting peer dependency: @babel/core@8.1.0."
    )


def test_why_uv_could_not_resolve() -> None:
    assert _why(REFUSED.splitlines()).startswith("Because arq==0.28.0 depends on redis<6 and")


def test_why_otherwise_the_last_lines() -> None:
    assert _why(["un", "deux", "trois", "quatre"]) == "deux ; trois ; quatre."
    assert _why([]) == "l'outil n'a rien dit."
    assert len(_why(["x" * 1000])) == 400


def test_paths_of_the_computer_are_left_out(tmp_path: Path, user_files: UserFiles) -> None:
    home = user_files.home
    root = tmp_path / "depot"
    text = (
        f"Failed to parse {root / 'pyproject.toml'}\n"
        f"see {home / 'AppData' / 'Local' / 'npm-cache' / '_logs' / 'x.log'}"
    )
    redacted = _redact(text, root)
    assert str(home) not in redacted
    assert str(root) not in redacted
    assert re.search(r"Failed to parse \.[\\/]pyproject\.toml", redacted)
    assert re.search(r"see ~[\\/]AppData", redacted)


def test_a_failed_tool_message_has_no_path_of_the_computer(
    make_tree: MakeTree, fake_tools: Tools, user_files: UserFiles
) -> None:
    root, demo = project(make_tree)
    tools = fake_tools("uv")
    log = user_files.home / "AppData" / "Local" / "uv" / "x.log"

    def uv(call: ToolCall) -> tuple[int, str, str]:
        return 1, "", f"error: {root / 'pyproject.toml'} est illisible\nvoir {log}\n"

    tools.handlers["uv"] = uv
    _, result = run(root, [wanted(demo, "httpx", "0.28.1", ">=0.28.1", Gap.MINOR)])

    assert result.status is LockStatus.FAILED
    assert result.error is not None
    assert str(user_files.home) not in result.error
    assert str(root) not in result.error


def test_the_terminal_says_which_major_was_dropped(make_tree: MakeTree, fake_tools: Tools) -> None:
    root, demo = project(make_tree)
    tools = fake_tools("uv")
    tools.handlers["uv"] = FakeUv(root)
    choices = [
        wanted(demo, "httpx", "0.28.1", ">=0.28.1", Gap.MINOR),
        wanted(demo, "redis", "8.1.0", ">=8.1.0", Gap.MAJOR),
    ]
    changes, result = run(root, choices)
    console = Console(width=200, record=True, color_system=None)
    terminal.render_outcome(changes, [result], console)
    text = console.export_text()
    assert "uv.lock : régénéré (uv)." in text
    assert "redis" in text
    assert "pas faite, uv refuse 8.1.0 : Because arq==0.28.0 depends on redis<6" in text


def test_tilde_writes_the_home_folder_as_a_tilde(user_files: UserFiles) -> None:
    """La même règle pour la sortie de git (``forges.git``) : son clone est sous le dossier
    personnel (session 37 : « Cloning into 'C:/Users/<nom>/…' » à l'écran)."""
    home = user_files.home
    text = f"Cloning into '{home / 'AppData' / 'depot'}'... fatal: unable to access"
    assert userfiles.tilde(text).startswith("Cloning into '~")
    assert str(home) not in userfiles.tilde(text)
