"""La réécriture des manifestes (E10) : seul le texte des contraintes change, chaque fichier
réécrit est relu par son parseur, et ce qui ne peut pas être réécrit est dit.

Les déclarations viennent de la vraie analyse (``engine.inventory``) de fichiers écrits dans le
dossier du test ; les mises à jour sont faites à la main, comme le planificateur les ferait."""

import os
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from forceupdate import engine
from forceupdate.models import (
    Dependency,
    Edit,
    EditKind,
    Gap,
    Project,
    Update,
    UpdateOption,
    UpdateReason,
)
from forceupdate.sources.local import LocalSource
from forceupdate.update import writers
from forceupdate.update.writers import Changes, Choice, WriteError, unified_diff

PROJECTS = Path(__file__).parent / "projects"
MakeTree = Callable[..., Path]
New = str | Callable[[str], str]


def inventory(root: Path) -> dict[str, Project]:
    return {project.path: project for project in engine.inventory(LocalSource(root)).projects}


def option(*edits: Edit, version: str = "9.9.9", manual: str | None = None) -> UpdateOption:
    return UpdateOption(
        version=version,
        gap=Gap.MINOR,
        reasons=(UpdateReason.LATEST_MINOR,),
        edits=edits,
        manual=manual,
    )


def edit_of(dependency: Dependency, new: str) -> Edit:
    catalog = dependency.resolved_constraint is not None
    return Edit(
        kind=EditKind.CATALOG if catalog else EditKind.DEPENDENCY,
        file=dependency.file,
        location=dependency.location,
        old=dependency.effective_constraint,
        new=new,
    )


def choice(project: Project, name: str, new: New, *, version: str = "9.9.9") -> Choice:
    """La mise à jour de toutes les déclarations directes de ``name`` : chaque contrainte devient
    ``new`` (un texte, ou une fonction de l'ancienne)."""
    found = [d for d in project.dependencies if d.direct and d.name == name]
    assert found, name
    edits = [
        edit_of(d, new if isinstance(new, str) else new(d.effective_constraint)) for d in found
    ]
    update = Update(
        id=f"{project.path}|{name}",
        ecosystem=found[0].ecosystem,
        name=name,
        direct=True,
        dependencies=tuple(found),
        current_version="1.0.0",
    )
    return project, update, option(*edits, version=version)


def forced(project: Project, key: str, new: str) -> Choice:
    """La mise à jour d'une version forcée."""
    override = next(o for o in project.overrides if o.key == key)
    edit = Edit(
        kind=EditKind.OVERRIDE,
        file=override.file,
        location=override.location,
        old=override.constraint,
        new=new,
        override=override,
    )
    update = Update(
        id=f"{project.path}|{key}",
        ecosystem=override.ecosystem,
        name=override.name,
        direct=False,
        dependencies=(),
        current_version="1.0.0",
    )
    return project, update, option(edit)


def written(root: Path, changes: Changes) -> dict[str, str]:
    """Écrit ``changes``, et rend le contenu des fichiers réécrits, lu sur le disque."""
    writers.write(root, changes)
    return {c.path: (root / c.path).read_bytes().decode("utf-8") for c in changes.files}


# ---------------------------------------------------------------------------
# Chaque format : seule la contrainte change
# ---------------------------------------------------------------------------

REQUIREMENTS = """\
# l'application
flask==2.0.1  # web
requests >= 2.25, < 3
uvicorn[standard]>=0.20.0 ; python_version >= "3.9"
ruff
"""

PYPROJECT = """\
[project]
name = "app"
dependencies = [
    "flask>=2.0",  # web
    'requests[socks]>=2.25,<3',
    "click",
]

[project.optional-dependencies]
cli = ["rich>=13"]

[dependency-groups]
dev = ["pytest>=8.0"]

[build-system]
requires = ["hatchling>=1.20"]
"""

POETRY = """\
[tool.poetry]
name = "app"

[tool.poetry.dependencies]
python = "^3.11"
requests = "^2.31"
click = { version = "^8.1", optional = true }

[tool.poetry.group.dev.dependencies]
pytest = "^8.0"
"""

PIPFILE = """\
[packages]
flask = "==2.0"
requests = {version = ">=2.0", extras = ["socks"]}

[dev-packages]
pytest = "*"
"""

SETUP_CFG = """\
[options]
install_requires =
    requests>=2.25
    # commentaire
    click ; python_version >= "3.8"

[options.extras_require]
yaml = PyYAML>=6; toml>=0.10
"""

PACKAGE_JSON = """\
{
  "name": "web",
  "dependencies": {
    "lodash": "^4.17.15",
    "my-ms": "npm:ms@2.0.0",
    "@types/node": " ~20.1.0 "
  },
  "devDependencies": {
    "lodash": "^4.17.0"
  }
}
"""


def _replace(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, old
    return text.replace(old, new)


@pytest.mark.parametrize(
    ("path", "content", "name", "new", "expected"),
    [
        # requirements.txt : le commentaire, les espaces, les extras et le marqueur restent.
        ("requirements.txt", REQUIREMENTS, "flask", "==3.1.3", ("flask==2.0.1", "flask==3.1.3")),
        (
            "requirements.txt",
            REQUIREMENTS,
            "requests",
            ">= 2.34.2, < 3",
            ("requests >= 2.25, < 3", "requests >= 2.34.2, < 3"),
        ),
        ("requirements.txt", REQUIREMENTS, "uvicorn", ">=0.54.0", (">=0.20.0", ">=0.54.0")),
        # Une contrainte absente : insérée après le nom.
        ("requirements.txt", REQUIREMENTS, "ruff", ">=0.15", ("ruff\n", "ruff>=0.15\n")),
        ("requirements-dev.in", "pytest==8.0.0\n", "pytest", "==9.2.0", ("8.0.0", "9.2.0")),
        # pyproject.toml : PEP 621, extras, PEP 735, build-system ; chaîne littérale comprise.
        ("pyproject.toml", PYPROJECT, "flask", ">=3.1", ('"flask>=2.0"', '"flask>=3.1"')),
        (
            "pyproject.toml",
            PYPROJECT,
            "requests",
            ">=2.34.2,<3",
            ("'requests[socks]>=2.25,<3'", "'requests[socks]>=2.34.2,<3'"),
        ),
        ("pyproject.toml", PYPROJECT, "click", ">=8.3", ('"click"', '"click>=8.3"')),
        ("pyproject.toml", PYPROJECT, "rich", ">=14", ('"rich>=13"', '"rich>=14"')),
        ("pyproject.toml", PYPROJECT, "pytest", ">=9.2", ('"pytest>=8.0"', '"pytest>=9.2"')),
        ("pyproject.toml", PYPROJECT, "hatchling", ">=1.29", (">=1.20", ">=1.29")),
        # Poetry : chaîne, et table en ligne.
        ("pyproject.toml", POETRY, "requests", "^2.34", ('"^2.31"', '"^2.34"')),
        ("pyproject.toml", POETRY, "click", "^8.3", ('"^8.1"', '"^8.3"')),
        ("pyproject.toml", POETRY, "pytest", "^9.2", ('"^8.0"', '"^9.2"')),
        # Pipfile : chaîne, et table.
        ("Pipfile", PIPFILE, "flask", "==3.1", ('"==2.0"', '"==3.1"')),
        ("Pipfile", PIPFILE, "requests", ">=2.34", ('">=2.0"', '">=2.34"')),
        ("Pipfile", PIPFILE, "pytest", ">=9", ('"*"', '">=9"')),
        # setup.cfg : une par ligne, une absente, plusieurs sur une ligne.
        ("setup.cfg", SETUP_CFG, "requests", ">=2.34.2", (">=2.25", ">=2.34.2")),
        ("setup.cfg", SETUP_CFG, "click", ">=8", ("click ;", "click>=8 ;")),
        ("setup.cfg", SETUP_CFG, "toml", ">=0.10.2", ("toml>=0.10", "toml>=0.10.2")),
        # package.json : l'alias ne change que sa version, les espaces autour restent.
        ("package.json", PACKAGE_JSON, "ms", "2.1.3", ("npm:ms@2.0.0", "npm:ms@2.1.3")),
        ("package.json", PACKAGE_JSON, "@types/node", "~22.0.0", (" ~20.1.0 ", " ~22.0.0 ")),
    ],
)
def test_only_the_constraint_changes(
    make_tree: MakeTree, path: str, content: str, name: str, new: str, expected: tuple[str, str]
) -> None:
    root = make_tree({path: content})
    changes = writers.prepare(root, [choice(inventory(root)["."], name, new)])
    after = _replace(content, *expected)
    assert changes.skipped == ()
    assert [(c.path, c.before, c.after) for c in changes.files] == [(path, content, after)]
    assert written(root, changes) == {path: after}
    # Relu : la nouvelle contrainte, à son emplacement.
    found = [d for d in inventory(root)["."].dependencies if d.direct and d.name == name]
    assert [d.constraint for d in found] == [new]
    assert found[0].location is not None
    assert found[0].location.extract(after) == new


def test_every_declaration_of_a_package_moves_together(make_tree: MakeTree) -> None:
    """lodash en dependencies et en devDependencies : les deux réécrites, du même coup."""
    root = make_tree({"package.json": PACKAGE_JSON})
    news = {"^4.17.15": "^4.18.1", "^4.17.0": "^4.18.0"}
    changes = writers.prepare(root, [choice(inventory(root)["."], "lodash", news.__getitem__)])
    assert written(root, changes) == {
        "package.json": PACKAGE_JSON.replace('"^4.17.15"', '"^4.18.1"').replace(
            '"^4.17.0"', '"^4.18.0"'
        )
    }


def test_several_rewrites_on_the_same_line(make_tree: MakeTree) -> None:
    """Deux contraintes sur une ligne (setup.cfg, séparées par « ; ») : la seconde a bougé
    quand la première a changé de longueur, et la relecture le sait."""
    root = make_tree({"setup.cfg": SETUP_CFG})
    project = inventory(root)["."]
    changes = writers.prepare(
        root, [choice(project, "pyyaml", ">=6.0.3"), choice(project, "toml", ">=0.10.2")]
    )
    assert changes.skipped == ()
    after = SETUP_CFG.replace("PyYAML>=6; toml>=0.10", "PyYAML>=6.0.3; toml>=0.10.2")
    assert written(root, changes) == {"setup.cfg": after}


def test_overrides(make_tree: MakeTree) -> None:
    content = """\
{
  "dependencies": {"a": "^1.0.0"},
  "overrides": {"dompurify": "^3.4.13", "foo": {".": "1.0.0"}},
  "resolutions": {"**/minimist": "1.2.8"},
  "pnpm": {"overrides": {"debug@<3": "3.2.7"}}
}
"""
    root = make_tree({"package.json": content})
    project = inventory(root)["."]
    changes = writers.prepare(
        root,
        [
            forced(project, "dompurify", "^3.4.17"),
            forced(project, "foo", "1.2.0"),
            forced(project, "**/minimist", "1.2.9"),
            forced(project, "debug@<3", "3.2.8"),
        ],
    )
    assert changes.skipped == ()
    after = (
        content.replace("^3.4.13", "^3.4.17")
        .replace('"1.0.0"', '"1.2.0"')
        .replace("1.2.8", "1.2.9")
        .replace("3.2.7", "3.2.8")
    )
    assert written(root, changes) == {"package.json": after}


# ---------------------------------------------------------------------------
# Catalogues et versions forcées de pnpm-workspace.yaml
# ---------------------------------------------------------------------------

WORKSPACE = """\
packages:
  - packages/*

# Les versions partagées
catalog:
  is-number: ^7.0.0   # commentaire
  'react': '^18.2.0'
  my-ms: "npm:ms@^2.1.0"

catalogs:
  legacy:
    is-odd: ^2.0.0

overrides:
  dompurify: ^3.4.13
"""

CATALOG_FILES = {
    "pnpm-workspace.yaml": WORKSPACE,
    "package.json": (
        '{"dependencies": {"is-number": "catalog:", "react": "catalog:", '
        '"my-ms": "catalog:default"}}\n'
    ),
    "packages/app/package.json": (
        '{"dependencies": {"is-odd": "catalog:legacy", "is-number": "catalog:"}}\n'
    ),
}


@pytest.mark.parametrize(
    ("project", "name", "new", "expected"),
    [
        (".", "is-number", "^7.0.1", "  is-number: ^7.0.1   # commentaire"),
        (".", "react", "^18.3.1", "  'react': '^18.3.1'"),
        (".", "ms", "^2.1.3", '  my-ms: "npm:ms@^2.1.3"'),
        ("packages/app", "is-odd", "^3.0.1", "    is-odd: ^3.0.1"),
    ],
)
def test_catalog_ranges_are_rewritten_in_pnpm_workspace_yaml(
    make_tree: MakeTree, project: str, name: str, new: str, expected: str
) -> None:
    root = make_tree(CATALOG_FILES)
    changes = writers.prepare(root, [choice(inventory(root)[project], name, new)])
    assert changes.skipped == ()
    assert [c.path for c in changes.files] == ["pnpm-workspace.yaml"]
    (after,) = written(root, changes).values()
    changed = [line for line in after.split("\n") if line not in WORKSPACE.split("\n")]
    assert changed == [expected]
    # L'analyse relit la nouvelle plage.
    found = [d for d in inventory(root)[project].dependencies if d.name == name]
    assert [d.resolved_constraint for d in found] == [new]


def test_two_projects_sharing_a_catalog_entry(make_tree: MakeTree) -> None:
    """is-number est au catalogue pour la racine et pour packages/app : réécrit une fois si les
    deux disent la même chose ; sinon la seconde n'est pas appliquée."""
    root = make_tree(CATALOG_FILES)
    projects = inventory(root)
    same = [
        choice(projects["."], "is-number", "^7.0.1"),
        choice(projects["packages/app"], "is-number", "^7.0.1"),
    ]
    changes = writers.prepare(root, same)
    assert changes.skipped == ()
    assert len(changes.applied) == 2
    assert changes.files[0].after.count("^7.0.1") == 1
    other = [same[0], choice(projects["packages/app"], "is-number", "^7.1.0")]
    changes = writers.prepare(root, other)
    assert len(changes.applied) == 1
    (skipped,) = changes.skipped
    assert skipped.reason == (
        "pnpm-workspace.yaml : « ^7.0.0 » est déjà réécrite en « ^7.0.1 » pour is-number 1.0.0 "
        "(projet .)."
    )


def test_pnpm_workspace_overrides(make_tree: MakeTree) -> None:
    root = make_tree(CATALOG_FILES)
    project = inventory(root)["."]
    assert [(o.file, o.section, o.key) for o in project.overrides] == [
        ("pnpm-workspace.yaml", "overrides", "dompurify")
    ]
    changes = writers.prepare(root, [forced(project, "dompurify", "^3.4.17")])
    assert written(root, changes) == {"pnpm-workspace.yaml": WORKSPACE.replace("3.4.13", "3.4.17")}


@pytest.mark.parametrize(
    ("workspace", "reason"),
    [
        (
            "catalog:\n  is-number: ^7.1.0\n",
            "pnpm-workspace.yaml : « ^7.0.0 » (is-number) n'est plus dans le catalogue "
            "« default ».",
        ),
        (
            'catalog:\n  is-number: "^7.0\\u002E0"\n',
            "pnpm-workspace.yaml : la plage « ^7.0.0 » (is-number) est écrite sur plusieurs "
            "lignes ou avec un échappement, à réécrire à la main en « ^7.0.1 ».",
        ),
        ("catalog: [\n", "pnpm-workspace.yaml : YAML invalide"),
        (None, "aucun pnpm-workspace.yaml pour package.json : la plage du catalogue est inconnue."),
    ],
)
def test_a_catalog_range_that_cannot_be_rewritten(
    make_tree: MakeTree, workspace: str | None, reason: str
) -> None:
    """Le pnpm-workspace.yaml a changé depuis l'analyse, ou la plage y est écrite d'une façon
    qu'on ne sait pas réécrire : rien n'est touché, et la raison est dite."""
    root = make_tree({"pnpm-workspace.yaml": "catalog:\n  is-number: ^7.0.0\n"})
    make_tree({"package.json": '{"dependencies": {"is-number": "catalog:"}}\n'})
    project = inventory(root)["."]
    if workspace is None:
        (root / "pnpm-workspace.yaml").unlink()
    else:
        make_tree({"pnpm-workspace.yaml": workspace})
    changes = writers.prepare(root, [choice(project, "is-number", "^7.0.1")])
    assert changes.files == ()
    (skipped,) = changes.skipped
    assert skipped.reason.startswith(reason)


# ---------------------------------------------------------------------------
# Fins de ligne, BOM, et ce qu'on ne réécrit pas
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "content", "name", "new"),
    [
        ("requirements.txt", REQUIREMENTS, "flask", "==3.1.3"),
        ("requirements.txt", REQUIREMENTS, "ruff", ">=0.15"),  # insérée avant le \r
        ("pyproject.toml", PYPROJECT, "requests", ">=2.34.2,<3"),
        ("Pipfile", PIPFILE, "requests", ">=2.34"),
        ("setup.cfg", SETUP_CFG, "click", ">=8"),
        ("package.json", PACKAGE_JSON, "ms", "2.1.3"),
    ],
)
def test_crlf_files_keep_their_line_endings(
    make_tree: MakeTree, path: str, content: str, name: str, new: str
) -> None:
    crlf = content.replace("\n", "\r\n")
    root = make_tree({path: crlf})
    changes = writers.prepare(root, [choice(inventory(root)["."], name, new)])
    assert changes.skipped == ()
    (after,) = written(root, changes).values()
    assert after.count("\r\n") == crlf.count("\r\n")
    assert after.replace("\r\n", "\n").count("\n") == content.count("\n")
    assert "\r\n" in after and "\r\r" not in after
    # Le diff ne montre pas les \r.
    assert "\r" not in changes.files[0].diff


def test_a_bom_counts_for_the_columns_of_line_1(make_tree: MakeTree) -> None:
    content = '﻿{"dependencies": {"lodash": "^4.17.15"}}\n'
    root = make_tree({"package.json": content})
    changes = writers.prepare(root, [choice(inventory(root)["."], "lodash", "^4.18.1")])
    assert written(root, changes) == {"package.json": content.replace("4.17.15", "4.18.1")}


def test_a_manual_option_is_not_applied(make_tree: MakeTree) -> None:
    root = make_tree({"requirements.txt": "flask==2.0.1\n"})
    project, update, _ = choice(inventory(root)["."], "flask", "==3.1.3")
    manual = option(manual="Contrainte « * » : style non géré, à réécrire à la main.")
    changes = writers.prepare(root, [(project, update, manual)])
    assert changes.files == ()
    assert changes.applied == ()
    assert [s.reason for s in changes.skipped] == [
        "à faire à la main : Contrainte « * » : style non géré, à réécrire à la main."
    ]


def test_a_lockfile_only_update_is_applied_without_files(make_tree: MakeTree) -> None:
    root = make_tree({"requirements.txt": "flask==2.0.1\n"})
    project, update, _ = choice(inventory(root)["."], "flask", "==3.1.3")
    only = UpdateOption(
        version="2.0.3", gap=Gap.PATCH, reasons=(UpdateReason.LATEST_PATCH,), lockfile="uv.lock"
    )
    changes = writers.prepare(root, [(project, update, only)])
    assert changes.files == ()
    assert changes.applied == ((project, update, only),)
    assert changes.lockfiles == ("uv.lock",)


def test_a_file_changed_since_the_analysis_is_not_touched(make_tree: MakeTree) -> None:
    root = make_tree({"requirements.txt": "flask==2.0.1\n"})
    wanted = choice(inventory(root)["."], "flask", "==3.1.3")
    make_tree({"requirements.txt": "# ajouté\nflask==2.0.1\n"})
    changes = writers.prepare(root, [wanted])
    assert changes.files == ()
    assert [s.reason for s in changes.skipped] == [
        "requirements.txt a changé depuis l'analyse : « ==2.0.1 » n'est plus à la ligne 1."
    ]


def test_an_option_is_applied_whole_or_not_at_all(make_tree: MakeTree) -> None:
    """lodash déclaré deux fois ; la seconde déclaration a changé depuis l'analyse : la
    première n'est pas réécrite non plus."""
    root = make_tree({"package.json": PACKAGE_JSON})
    wanted = choice(inventory(root)["."], "lodash", "^4.18.1")
    make_tree({"package.json": PACKAGE_JSON.replace('"^4.17.0"', '"^4.17.1"')})
    changes = writers.prepare(root, [wanted])
    assert changes.files == ()
    assert len(changes.skipped) == 1


def test_no_location_is_not_rewritten(make_tree: MakeTree) -> None:
    root = make_tree({"requirements.txt": "flask==2.0.1\n"})
    project, update, _ = choice(inventory(root)["."], "flask", "==3.1.3")
    edit = Edit(
        kind=EditKind.DEPENDENCY, file="requirements.txt", location=None, old="==2.0.1", new="=="
    )
    changes = writers.prepare(root, [(project, update, option(edit))])
    assert [s.reason for s in changes.skipped] == [
        "requirements.txt : emplacement de « ==2.0.1 » inconnu, à réécrire à la main en « == »."
    ]


@pytest.mark.parametrize(
    ("path", "content", "name", "new", "reason"),
    [
        # Le JSON ne se lit plus.
        (
            "package.json",
            PACKAGE_JSON,
            "@types/node",
            '1"',
            "package.json : une fois réécrit, il ne se lit plus (JSON invalide",
        ),
        # Une ligne de plus : ce ne sont plus les mêmes dépendances.
        (
            "requirements.txt",
            "flask==2.0.1\n",
            "flask",
            "==3.1.3\nevil==1.0",
            "requirements.txt : une fois réécrit, il ne redonne pas les mêmes dépendances.",
        ),
        # Le texte écrit n'est pas lu comme la contrainte voulue.
        (
            "requirements.txt",
            "flask==2.0.1\n",
            "flask",
            "==3.1.3  # !",
            "requirements.txt : une fois réécrit, il ne redonne pas « ==3.1.3  # ! » ligne 1.",
        ),
    ],
)
def test_a_rewrite_that_does_not_read_back_is_refused(
    make_tree: MakeTree, path: str, content: str, name: str, new: str, reason: str
) -> None:
    root = make_tree({path: content})
    changes = writers.prepare(root, [choice(inventory(root)["."], name, new)])
    assert changes.files == ()
    assert changes.applied == ()
    (skipped,) = changes.skipped
    assert skipped.reason.startswith(reason)


def test_an_option_whose_other_file_does_not_read_back(make_tree: MakeTree) -> None:
    """flask est déclaré dans pyproject.toml et dans requirements.txt : le second ne se relit
    pas, le premier n'est pas réécrit non plus."""
    root = make_tree({"requirements.txt": "flask==2.0.1\n", "pyproject.toml": PYPROJECT})
    news = {"==2.0.1": "==3.1.3\nevil==1.0", ">=2.0": ">=3.1"}
    changes = writers.prepare(root, [choice(inventory(root)["."], "flask", news.__getitem__)])
    assert changes.files == ()
    (skipped,) = changes.skipped
    assert skipped.reason.startswith("requirements.txt : une fois réécrit")


def test_one_refused_file_does_not_stop_the_others(make_tree: MakeTree) -> None:
    root = make_tree({"package.json": PACKAGE_JSON, "requirements.txt": "flask==2.0.1\n"})
    project = inventory(root)["."]
    changes = writers.prepare(
        root, [choice(project, "@types/node", '1"'), choice(project, "flask", "==3.1.3")]
    )
    assert [c.path for c in changes.files] == ["requirements.txt"]
    assert [u.name for _, u, _ in changes.applied] == ["flask"]
    assert [s.update.name for s in changes.skipped] == ["@types/node"]


def test_requirements_with_hashes_are_not_rewritten(make_tree: MakeTree) -> None:
    content = "flask==2.0.1 \\\n    --hash=sha256:abc\nrequests==2.25.0  # --hash ailleurs\n"
    root = make_tree({"requirements.txt": content})
    project = inventory(root)["."]
    changes = writers.prepare(
        root, [choice(project, "flask", "==3.1.3"), choice(project, "requests", "==2.34.2")]
    )
    assert [u.name for _, u, _ in changes.applied] == ["requests"]
    assert [s.reason for s in changes.skipped] == [
        "requirements.txt : ligne 1, les empreintes (--hash) sont celles de la version actuelle ; "
        "à réécrire à la main, avec celles de la nouvelle."
    ]


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"flask==2.0.1  # \xe9\n", "requirements.txt : pas en UTF-8, pas réécrit."),
        (b"# old mac\rflask==2.0.1\n", "requirements.txt : fins de ligne « \\r » seules"),
    ],
)
def test_files_whose_locations_would_be_wrong(tmp_path: Path, data: bytes, reason: str) -> None:
    (tmp_path / "requirements.txt").write_bytes(data)
    changes = writers.prepare(tmp_path, [choice(inventory(tmp_path)["."], "flask", "==3.1.3")])
    assert changes.files == ()
    assert changes.skipped[0].reason.startswith(reason)
    assert (tmp_path / "requirements.txt").read_bytes() == data


# ---------------------------------------------------------------------------
# Le diff
# ---------------------------------------------------------------------------


def test_the_diff_is_unified(make_tree: MakeTree) -> None:
    content = "a==1.0\nb==1.0\nc==1.0\nd==1.0\ne==1.0\nflask==2.0.1\n"
    root = make_tree({"requirements.txt": content})
    changes = writers.prepare(root, [choice(inventory(root)["."], "flask", "==3.1.3")])
    assert changes.diff == (
        "--- a/requirements.txt\n"
        "+++ b/requirements.txt\n"
        "@@ -3,4 +3,4 @@\n"
        " c==1.0\n"
        " d==1.0\n"
        " e==1.0\n"
        "-flask==2.0.1\n"
        "+flask==3.1.3\n"
    )


def test_unified_diff() -> None:
    assert unified_diff("x", "a\n", "a\n") == ""
    assert (
        unified_diff("x", "a\r\nb", "a\r\nc") == "--- a/x\n+++ b/x\n@@ -1,2 +1,2 @@\n a\n-b\n+c\n"
    )


# ---------------------------------------------------------------------------
# L'écriture
# ---------------------------------------------------------------------------


def test_nothing_is_written_if_a_file_changed_since_prepare(make_tree: MakeTree) -> None:
    root = make_tree({"package.json": PACKAGE_JSON, "requirements.txt": "flask==2.0.1\n"})
    project = inventory(root)["."]
    changes = writers.prepare(
        root, [choice(project, "ms", "2.1.3"), choice(project, "flask", "==3.1.3")]
    )
    make_tree({"requirements.txt": "flask==2.0.1\n# édité entre-temps\n"})
    with pytest.raises(WriteError, match=r"requirements\.txt a changé depuis le calcul du diff"):
        writers.write(root, changes)
    assert (root / "package.json").read_text(encoding="utf-8") == PACKAGE_JSON


def test_a_failed_write_restores_the_files_already_written(
    make_tree: MakeTree, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_tree({"package.json": PACKAGE_JSON, "requirements.txt": "flask==2.0.1\n"})
    project = inventory(root)["."]
    changes = writers.prepare(
        root, [choice(project, "ms", "2.1.3"), choice(project, "flask", "==3.1.3")]
    )
    replace = writers._replace

    def failing(path: Path, text: str) -> None:
        if path.name == "requirements.txt":
            raise PermissionError(13, "Permission refusée")
        replace(path, text)

    monkeypatch.setattr(writers, "_replace", failing)
    with pytest.raises(WriteError) as raised:
        writers.write(root, changes)
    assert str(raised.value) == (
        "requirements.txt : écriture impossible (Permission refusée) ; les fichiers déjà écrits "
        "sont remis comme avant."
    )
    assert (root / "package.json").read_text(encoding="utf-8") == PACKAGE_JSON


def test_writing_leaves_no_temporary_file(make_tree: MakeTree) -> None:
    root = make_tree({"requirements.txt": "flask==2.0.1\n"})
    changes = writers.prepare(root, [choice(inventory(root)["."], "flask", "==3.1.3")])
    writers.write(root, changes)
    assert sorted(p.name for p in root.iterdir()) == ["requirements.txt"]


@pytest.mark.skipif(os.name == "nt", reason="pas de droits POSIX sous Windows")
def test_writing_keeps_the_file_mode(make_tree: MakeTree) -> None:
    root = make_tree({"requirements.txt": "flask==2.0.1\n"})
    (root / "requirements.txt").chmod(0o640)
    changes = writers.prepare(root, [choice(inventory(root)["."], "flask", "==3.1.3")])
    writers.write(root, changes)
    assert (root / "requirements.txt").stat().st_mode & 0o777 == 0o640


# ---------------------------------------------------------------------------
# Les mini-projets : le diff ne touche que les contraintes (critère de fin de E10)
# ---------------------------------------------------------------------------


def _bumped(ecosystem_is_npm: bool) -> Callable[[str], str]:
    """Une nouvelle contrainte pour chaque ancienne : ses nombres passent à 99 ; une contrainte
    sans nombre (absente, ``*``) devient une borne basse."""

    def new(old: str) -> str:
        if any(char.isdigit() for char in old):
            return "".join("99" if part.isdigit() else part for part in _split_digits(old))
        return "^99.0.0" if ecosystem_is_npm else ">=99.0"

    return new


def _split_digits(text: str) -> list[str]:
    parts: list[str] = []
    for char in text:
        if parts and char.isdigit() == parts[-1][-1].isdigit():
            parts[-1] += char
        else:
            parts.append(char)
    return parts


@pytest.mark.parametrize("name", sorted(p.name for p in PROJECTS.iterdir() if p.is_dir()))
def test_on_the_mini_projects_only_constraints_change(name: str, tmp_path: Path) -> None:
    root = tmp_path / name
    shutil.copytree(PROJECTS / name, root)
    choices = []
    for project in inventory(root).values():
        names = dict.fromkeys(
            d.name
            for d in project.dependencies
            if d.direct and d.verifiable and (d.location is not None or d.resolved_constraint)
        )
        for package in names:
            npm = project.dependencies[0].ecosystem.value == "npm"
            choices.append(choice(project, package, _bumped(npm)))
        for override in project.overrides:
            if override.location is not None:
                choices.append(forced(project, override.key, "99.0.0"))
    assert choices
    changes = writers.prepare(root, choices)
    # Seule exception : la ligne à empreintes de pip/requirements-dev.txt.
    assert all("--hash" in s.reason for s in changes.skipped), changes.skipped
    assert changes.files
    writers.write(root, changes)
    for change in changes.files:
        reader = writers._reader(change.path)
        assert reader is not None
        was = reader(change.path, change.before.replace("\r\n", "\n"))
        now = reader(change.path, change.after.replace("\r\n", "\n"))
        # Remettre les anciennes contraintes aux nouveaux emplacements redonne le fichier
        # d'origine, à l'octet près : rien d'autre n'a changé.
        text = change.after
        lines = text.split("\n")
        for before, after in reversed(list(zip(was, now, strict=True))):
            assert before.identity == after.identity
            if before.constraint == after.constraint:
                continue
            assert after.location is not None
            line = lines[after.location.line - 1]
            start, end = after.location.column, after.location.end_column
            assert line[start:end] == after.constraint
            lines[after.location.line - 1] = line[:start] + before.constraint + line[end:]
        assert "\n".join(lines) == change.before
        assert (root / change.path).read_bytes().decode("utf-8") == change.after
