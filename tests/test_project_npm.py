"""Le npm qu'attend le projet (E32) : le lire, le comparer à celui de la machine, régénérer le
``package-lock.json`` avec lui (``npx -y npm@10``) et faire relire le lockfile par lui.

Le cas vient d'un essai de l'utilisateur : une PR faite avec npm 11 (Node 24, sur la machine)
dont le lockfile a été refusé par ``npm ci`` de la CI du dépôt (Node 22, npm 10). Les outils sont
simulés (``FakeTools``) ; les deux vrais npm ne tournent que dans le test ``network``."""

import io
import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import FakeTools, ToolCall
from rich.console import Console

from forceupdate import engine
from forceupdate.models import Gap, Report, Runtime, Update, UpdateOption, UpdateReason
from forceupdate.report import terminal
from forceupdate.sources.local import LocalSource
from forceupdate.update import lockfiles, project_npm, writers
from forceupdate.update.lockfiles import ExtraKind, LockStatus, Regenerated
from forceupdate.update.project_npm import NODE_NPM, expected, npm_of_node
from forceupdate.update.writers import Choice

MakeTree = Callable[..., Path]
Tools = Callable[..., FakeTools]


def node(version: str = "24.12.0") -> Callable[[], str | None]:
    return lambda: version


def choice_runtime(version: str, file: str = ".nvmrc") -> Runtime:
    return Runtime(product="nodejs", version=version, file=file, source=f"{file} : {version}")


# ---------------------------------------------------------------------------
# La table Node → npm
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "npm"),
    [
        ("22", 10),
        ("22.23.4", 10),
        ("24", 11),
        ("26", 11),
        ("20", 10),
        ("20.5.1", 9),
        ("20.7.0", 10),
        ("18", 10),
        ("18.13.0", 8),
        ("18.14.0", 9),
        ("16", 8),
        ("16.10", 7),
        ("14", 6),
        ("27", None),
        ("12", None),
    ],
)
def test_the_npm_of_a_node_version(version: str, npm: int | None) -> None:
    """Relevé sur ``nodejs.org/dist/index.json`` le 2026-11-02 : une version partielle vaut la
    dernière de sa ligne (ce que prend ``actions/setup-node``)."""
    assert npm_of_node(version) == npm


def test_the_table_is_ordered() -> None:
    for steps in NODE_NPM.values():
        assert steps[0][0] == 0
        assert [minor for minor, _ in steps] == sorted(minor for minor, _ in steps)


# ---------------------------------------------------------------------------
# Ce que le projet attend
# ---------------------------------------------------------------------------


def test_package_manager_decides() -> None:
    manifest = {"packageManager": "npm@10.9.0+sha512.abc", "engines": {"node": ">=24"}}
    found = expected(manifest, [choice_runtime("24")], "11.6.2", node())
    assert found == project_npm.Expected(
        major=10, installed="11.6.2", source='packageManager = "npm@10.9.0+sha512.abc"'
    )
    assert expected({"packageManager": "npm@11.2.0"}, [], "11.6.2", node()) is None
    # Un autre gestionnaire : le lockfile n'est pas celui de npm, rien à dire.
    assert (
        expected({"packageManager": "pnpm@9.15.9"}, [choice_runtime("22")], "11.6.2", node())
        is None
    )


@pytest.mark.parametrize(
    ("manifest", "major"),
    [
        ({"devEngines": {"packageManager": {"name": "npm", "version": "^10.0.0"}}}, 10),
        (
            {
                "devEngines": {
                    "packageManager": [{"name": "pnpm"}, {"name": "npm", "version": "10.x"}]
                }
            },
            10,
        ),
        ({"engines": {"npm": ">=8 <11"}}, 10),
        ({"engines": {"npm": "^9"}}, 9),
        ({"engines": {"npm": ">=10"}}, None),
        ({"engines": {"npm": "11.x || 12.x"}}, None),
    ],
)
def test_a_range_of_npm(manifest: dict[str, object], major: int | None) -> None:
    """Une plage : le npm installé qui la respecte convient ; sinon la plus haute majeure qu'elle
    accepte."""
    found = expected(manifest, [], "11.6.2", node())
    assert (found.major if found is not None else None) == major


def test_the_oldest_chosen_node() -> None:
    """Le Node choisi le plus ancien (la CI en 22, ``.nvmrc`` en 24) donne npm 10 ; une borne
    basse (``engines.node``) ne compte pas quand une version est choisie."""
    ci = Runtime(
        product="nodejs",
        version="22",
        file=".github/workflows/ci.yml",
        source="actions/setup-node : node-version 22",
    )
    bound = Runtime(
        product="nodejs",
        version="18",
        approximate=True,
        file="package.json",
        source='engines.node = ">=18"',
    )
    found = expected(
        {"engines": {"node": ">=18"}}, [choice_runtime("24"), ci, bound], "11.6.2", node()
    )
    assert found == project_npm.Expected(
        major=10,
        installed="11.6.2",
        source=(
            "Node.js 22, lu dans .github/workflows/ci.yml (actions/setup-node : node-version 22)"
        ),
    )
    assert expected({}, [choice_runtime("24")], "11.6.2", node()) is None
    # Dans l'autre sens : un projet en Node 24 sur une machine en npm 10.
    assert expected({}, [choice_runtime("24.1.0")], "10.9.2", node()).major == 11  # type: ignore[union-attr]
    # Une ligne de Node que la table ne connaît pas : rien.
    assert expected({}, [choice_runtime("40")], "11.6.2", node()) is None


def test_engines_node_against_the_installed_node() -> None:
    """``engines.node`` est une plage : si le Node installé la respecte, rien à dire ; sinon le
    npm de la plus récente ligne qu'elle accepte."""
    asked: list[str] = []

    def running() -> str | None:
        asked.append("node")
        return "24.12.0"

    assert expected({"engines": {"node": ">=18"}}, [], "11.6.2", running) is None
    found = expected({"engines": {"node": "^20 || ^22"}}, [], "11.6.2", running)
    assert found == project_npm.Expected(
        major=10, installed="11.6.2", source='engines.node = "^20 || ^22" (Node.js 24.12.0 ici)'
    )
    assert asked == ["node", "node"]
    assert expected({"engines": {"node": "^22"}}, [], "11.6.2", lambda: None) is None


def test_nothing_declared() -> None:
    assert not project_npm.declared({"name": "x", "dependencies": {}}, [])
    assert not project_npm.declared(
        None, [Runtime(product="python", version="3.12", file="x", source="x")]
    )
    assert project_npm.declared({"engines": {"node": ">=18"}}, [])
    assert project_npm.declared({}, [choice_runtime("22")])
    assert expected({}, [], "11.6.2", node()) is None
    assert expected({"packageManager": "npm@10"}, [], "pas une version", node()) is None


# ---------------------------------------------------------------------------
# Le plan et la régénération
# ---------------------------------------------------------------------------

PACKAGE_JSON = """\
{
  "name": "demo",
  "version": "1.0.0",
  "dependencies": {
    "lodash": "^4.17.15"
  }
}
"""

PACKAGE_LOCK = """\
{
  "name": "demo",
  "version": "1.0.0",
  "lockfileVersion": 3,
  "requires": true,
  "packages": {
    "": {
      "name": "demo",
      "version": "1.0.0",
      "dependencies": {
        "lodash": "^4.17.15"
      }
    },
    "node_modules/lodash": {
      "version": "4.17.15"
    }
  }
}
"""

WORKFLOW = """\
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: npm
      - run: npm ci
"""


def ci_project(
    make_tree: MakeTree, root: Path | None = None, *, workflow: str | None = WORKFLOW
) -> Path:
    files = {"package.json": PACKAGE_JSON, "package-lock.json": PACKAGE_LOCK}
    if workflow is not None:
        files[".github/workflows/ci.yml"] = workflow
    return make_tree(files, root) if root is not None else make_tree(files)


def lodash(root: Path, version: str = "4.17.21") -> tuple[LocalSource, Report, list[Choice]]:
    """La mise à jour de lodash par le lockfile seul (``^4.17.15`` l'accepte)."""
    source = LocalSource(root)
    report = engine.inventory(source)
    project = next(p for p in report.projects if p.path == ".")
    (dependency,) = [d for d in project.dependencies if d.name == "lodash"]
    option = UpdateOption(
        version=version,
        gap=Gap.PATCH,
        reasons=(UpdateReason.LATEST_PATCH,),
        lockfile=dependency.lockfile,
    )
    update = Update(
        id="lodash",
        ecosystem=dependency.ecosystem,
        name=dependency.name,
        direct=True,
        dependencies=(dependency,),
        current_version=dependency.installed,
        options=(option,),
        selected=version,
    )
    return source, report, [(project, update, option)]


def regenerated(root: Path, *, declined: bool = False) -> tuple[lockfiles.Job, Regenerated]:
    """Le plan de la mise à jour de lodash, appliqué : réécrire (rien), puis régénérer."""
    source, report, choices = lodash(root)
    changes = writers.prepare(root, choices)
    jobs = lockfiles.plan(source, report, changes)
    if declined:
        jobs = lockfiles.decline(jobs, [job.lockfile for job in jobs])
    writers.write(root, changes)
    (result,) = lockfiles.regenerate(source, report, changes, jobs)
    return jobs[0], result


class FakeNpm:
    """``npm`` (et ``npx -y npm@10``) : ``--version`` donne ``version`` ; ``install`` fige une
    directe à la version exacte écrite dans le ``package.json`` (l'épinglage du premier passage),
    ``update x`` la monte à ``latest`` ; ``ci`` répond ``refuse`` s'il est donné."""

    def __init__(self, version: str = "11.6.2", refuse: str | None = None) -> None:
        self.version = version
        self.refuse = refuse
        self.latest = {"lodash": "4.17.21"}

    def __call__(self, call: ToolCall) -> tuple[int, str, str] | None:
        arguments = call.arguments
        if call.program == "npx":
            assert arguments[:2] == ["-y", "npm@10"], arguments
            arguments = arguments[2:]
        if arguments == ["--version"]:
            return 0, f"{self.version}\n", ""
        if arguments[0] == "ci":
            assert "--dry-run" in arguments and "--ignore-scripts" in arguments
            if self.refuse is not None:
                return 1, "", self.refuse
            return None
        lock = call.cwd / "package-lock.json"
        data = json.loads(lock.read_text(encoding="utf-8"))
        manifest = json.loads((call.cwd / "package.json").read_text(encoding="utf-8"))
        for name, spec in manifest["dependencies"].items():
            if arguments[0] == "install" and spec[:1].isdigit():
                data["packages"][f"node_modules/{name}"]["version"] = spec
            elif arguments[0] == "update" and name in arguments and name in self.latest:
                data["packages"][f"node_modules/{name}"]["version"] = self.latest[name]
        lock.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return None


def npm_tools(fake_tools: Tools, fake: FakeNpm | None = None, *programs: str) -> FakeTools:
    tools = fake_tools("npm", "npx", *programs)
    tools.handlers["npm"] = tools.handlers["npx"] = fake or FakeNpm()
    return tools


def test_the_plan_says_which_npm(make_tree: MakeTree, fake_tools: Tools) -> None:
    """npm 11 sur la machine, une CI en Node 22 : la case « npm 10 », cochée d'office, et la
    commande à lancer avec ``npx``."""
    root = ci_project(make_tree)
    tools = npm_tools(fake_tools)
    source, report, choices = lodash(root)
    (job,) = lockfiles.plan(source, report, writers.prepare(root, choices))
    assert tools.commands() == ["npm --version"]
    assert job.extra is not None and job.accepted
    assert job.extra.kind is ExtraKind.PROJECT_NPM
    assert job.extra.label == "Régénérer avec npm 10, celui du projet"
    assert job.extra.detail == (
        "npm 11.6.2 ici ; le projet attend npm 10 : Node.js 22, lu dans .github/workflows/ci.yml "
        "(actions/setup-node : node-version 22). Un lockfile écrit par un autre npm risque d'être "
        "refusé par « npm ci » de sa CI : forceupdate le régénère avec npm 10, par npx, sans "
        "toucher au npm de cet ordinateur, puis le fait relire par npm 10 (npm ci, à blanc)."
    )
    assert job.launcher == ("/outils/npx", "-y", "npm@10")
    assert job.tool == "npm 10"
    assert job.command == "npx -y npm@10 update lodash --package-lock-only --ignore-scripts"
    (declined,) = lockfiles.decline([job], ["package-lock.json"])
    assert (declined.accepted, declined.launcher, declined.tool) == (False, (), "npm")
    assert declined.command == "npm update lodash --package-lock-only --ignore-scripts"


def test_regenerated_with_the_npm_of_the_project(make_tree: MakeTree, fake_tools: Tools) -> None:
    """Tout passe par ``npx -y npm@10`` (le passage épinglé, puis la contrainte remise) ; puis
    ``npm ci --dry-run`` de ce npm relit le lockfile."""
    root = ci_project(make_tree)
    tools = npm_tools(fake_tools)
    _, result = regenerated(root)

    assert result.status is LockStatus.REGENERATED, result.error
    install = "npx -y npm@10 install --package-lock-only --ignore-scripts --no-audit --no-fund"
    assert tools.commands() == [
        "npm --version",
        install,
        install,
        "npx -y npm@10 ci --dry-run --ignore-scripts --no-audit --no-fund",
    ]
    assert result.verified == lockfiles.Verified(
        command="npx -y npm@10 ci --dry-run --ignore-scripts --no-audit --no-fund"
    )
    reached = [(i.versions, i.reach) for i in result.installed]
    assert reached == [(("4.17.21",), lockfiles.Reach.EXACT)]


MISSING = """\
npm error code EUSAGE
npm error
npm error `npm ci` can only install packages when your package.json and package-lock.json or npm-shrinkwrap.json are in sync. Please update your lock file with `npm install` before continuing.
npm error
npm error Missing: zod@3.25.76 from lock file
npm error Missing: ws@8.18.3 from lock file
npm error
npm error Clean install a project
npm error
npm error Usage:
npm error npm ci
npm error
npm error Options:
npm error [--install-strategy <hoisted|nested|shallow|linked>] [--legacy-bundling]
npm error [--global-style] [--omit <dev|optional|peer> [--omit <dev|optional|peer> ...]]
npm error [--include <prod|dev|optional|peer> [--include <prod|dev|optional|peer> ...]]
npm error [--strict-peer-deps] [--foreground-scripts] [--ignore-scripts] [--no-audit]
npm error
npm error aliases: clean-install, ic, install-clean, isntall-clean
npm error
npm error Run "npm help ci" for more info
npm error A complete log of this run can be found in: C:\\npm-cache\\_logs\\debug-0.log
"""  # noqa: E501 : la sortie de npm 10.9, telle quelle


def test_a_refusal_of_npm_ci_is_said(make_tree: MakeTree, fake_tools: Tools) -> None:
    """``npm ci`` de npm 10 refuse : le lockfile reste régénéré, le résultat le dit, avec la
    commande qui le reproduit (les lignes « Missing », même après l'aide de la commande)."""
    root = ci_project(make_tree)
    npm_tools(fake_tools, FakeNpm(refuse=MISSING))
    _, result = regenerated(root)
    assert result.status is LockStatus.REGENERATED
    command = "npx -y npm@10 ci --dry-run --ignore-scripts --no-audit --no-fund"
    assert result.verified == lockfiles.Verified(
        command=command,
        error="Missing: zod@3.25.76 from lock file ; Missing: ws@8.18.3 from lock file.",
    )
    assert result.warnings == ()  # dit par ``verified``, une fois
    console = Console(file=io.StringIO(), width=200, highlight=False)
    terminal.render_outcome(writers.Changes(), (result,), console)
    said = " ".join(console.file.getvalue().split())  # type: ignore[attr-defined]
    assert (
        f"{command} refuse le lockfile : Missing: zod@3.25.76 from lock file ; Missing: "
        f"ws@8.18.3 from lock file. Pour le reproduire : {command}, dans .."
    ) in said
    assert (
        json.loads((root / "package-lock.json").read_text(encoding="utf-8"))["packages"][
            "node_modules/lodash"
        ]["version"]
        == "4.17.21"
    )


def test_declined_the_npm_of_the_machine(make_tree: MakeTree, fake_tools: Tools) -> None:
    root = ci_project(make_tree)
    tools = npm_tools(fake_tools)
    _, result = regenerated(root, declined=True)
    assert result.status is LockStatus.REGENERATED
    assert {call.program for call in tools.calls} == {"npm"}
    # Relu quand même, par le npm de l'ordinateur (session 36) : pas par npx.
    assert result.verified == lockfiles.Verified(
        command="npm ci --dry-run --ignore-scripts --no-audit --no-fund"
    )


def plan_of(root: Path) -> lockfiles.Job:
    source, report, choices = lodash(root)
    (job,) = lockfiles.plan(source, report, writers.prepare(root, choices))
    return job


def test_nothing_asked_without_an_expectation(make_tree: MakeTree, fake_tools: Tools) -> None:
    """Sans rien de déclaré (ni CI, ni ``engines``…), pas même ``npm --version``."""
    root = ci_project(make_tree, workflow=None)
    tools = npm_tools(fake_tools)
    job = plan_of(root)
    assert tools.commands() == []
    assert job.extra is None and job.launcher == ()


def test_the_same_major_says_nothing(make_tree: MakeTree, fake_tools: Tools) -> None:
    root = ci_project(make_tree)
    npm_tools(fake_tools, FakeNpm(version="10.9.2"))
    job = plan_of(root)
    assert job.extra is None and job.warnings == ()


def test_without_npx_or_too_old(make_tree: MakeTree, fake_tools: Tools, tmp_path: Path) -> None:
    """Sans ``npx``, ou un npm attendu trop ancien (npm 6 réécrirait le lockfile au format 1) :
    un avertissement, sans case."""
    root = ci_project(make_tree, tmp_path / "sans-npx")
    tools = fake_tools("npm")
    tools.handlers["npm"] = FakeNpm()
    job = plan_of(root)
    assert job.extra is None
    assert job.warnings[-1].endswith(", et npx n'est pas là pour lancer npm 10.")

    workflow = WORKFLOW.replace("node-version: 22", "node-version: 14")
    old = ci_project(make_tree, tmp_path / "ancien", workflow=workflow)
    npm_tools(fake_tools)
    job = plan_of(old)
    assert job.extra is None
    assert job.warnings[-1].startswith("npm 11.6.2 ici ; le projet attend npm 6 : Node.js 14,")
    assert job.warnings[-1].endswith(
        "forceupdate ne lance pas un npm si ancien : il réécrirait le lockfile dans un format plus "
        "ancien."
    )


# ---------------------------------------------------------------------------
# Les deux vrais npm
# ---------------------------------------------------------------------------

TAILWIND = """\
{
  "name": "demo-ci",
  "version": "1.0.0",
  "private": true,
  "devDependencies": {
    "@tailwindcss/vite": "^4.1.3",
    "tailwindcss": "^4.1.3",
    "vite": "^6.3.0"
  }
}
"""


@pytest.mark.network
def test_the_real_npm_of_the_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Le critère de E32 : npm 11 sur la machine, une CI en Node 22 ; la mise à jour donne un
    lockfile que le vrai ``npm@10 ci`` accepte. Avec ``--no-extras``, c'est npm 11 qui l'écrit
    (il y ajoute des ``"peer": true`` que npm 10 retire). Le cache de npm et de npx est celui du
    test."""
    npm, npx = shutil.which("npm"), shutil.which("npx")
    if npm is None or npx is None:
        pytest.skip("npm n'est pas installé")
    version = subprocess.run([npm, "--version"], capture_output=True, text=True, timeout=60)
    if not version.stdout.strip().startswith("11."):
        pytest.skip("le test vise npm 11 sur la machine")
    monkeypatch.setenv("npm_config_cache", str(tmp_path / "npm-cache"))
    monkeypatch.setenv("npm_config_update_notifier", "false")
    root = tmp_path / "projet"
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / "package.json").write_text(TAILWIND, encoding="utf-8")
    (root / ".github" / "workflows" / "ci.yml").write_text(WORKFLOW, encoding="utf-8")
    first = subprocess.run(
        [npm, "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"],
        cwd=root,
        capture_output=True,
        timeout=600,
    )
    assert first.returncode == 0, first.stderr
    source = LocalSource(root)
    report = engine.inventory(source)
    project = next(p for p in report.projects if p.path == ".")
    (dependency,) = [d for d in project.dependencies if d.name == "vite" and d.direct]
    option = UpdateOption(
        version="6.4.1",
        gap=Gap.MINOR,
        reasons=(UpdateReason.LATEST_MINOR,),
        lockfile=dependency.lockfile,
    )
    update = Update(
        id="vite",
        ecosystem=dependency.ecosystem,
        name="vite",
        direct=True,
        dependencies=(dependency,),
        current_version=dependency.installed,
        options=(option,),
    )
    changes = writers.prepare(root, [(project, update, option)])
    (job,) = lockfiles.plan(source, report, changes)
    assert job.extra is not None and job.extra.kind is ExtraKind.PROJECT_NPM
    assert job.tool == "npm 10"
    writers.write(root, changes)
    (result,) = lockfiles.regenerate(source, report, changes, (job,))
    assert result.status is LockStatus.REGENERATED, result.error
    assert result.verified is not None and result.verified.error is None, result.verified
    lock = (root / "package-lock.json").read_text(encoding="utf-8")
    assert '"peer": true' not in lock
    check = subprocess.run(
        [npx, "-y", "npm@10", "ci", "--dry-run", "--ignore-scripts", "--no-audit", "--no-fund"],
        cwd=root,
        capture_output=True,
        timeout=600,
    )
    assert check.returncode == 0, check.stderr

    # La case décochée : npm 11 réécrit le lockfile à sa façon.
    (declined,) = lockfiles.decline([job], [job.lockfile])
    (again,) = lockfiles.regenerate(
        source, engine.inventory(source), writers.Changes(), (declined,)
    )
    assert again.status is LockStatus.REGENERATED, again.error
    assert again.verified is None
    assert '"peer": true' in (root / "package-lock.json").read_text(encoding="utf-8")
