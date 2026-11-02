"""Le bloc PEP 723 d'un script Python (E28) : lu comme uv le lit (vérifié avec uv 0.10 : un bloc
n'importe où, même dans une chaîne ; jusqu'au dernier ``# ///`` ; refusé s'il n'est pas fermé),
placé dans le fichier, réécrivable."""

from pathlib import Path

import pytest

from forceupdate.models import Ecosystem, Project, Scope
from forceupdate.parsers import parse_lockfile, python
from forceupdate.parsers.base import REASON_GIT, ParseError
from forceupdate.update import writers
from forceupdate.update.writers.base import Target

PROJECTS = Path(__file__).parent / "projects"

BASIC = """#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "six>=1.16",
#   "idna",  # un commentaire TOML
#   'rich [jupyter] ==13.*',
# ]
#
# [tool.uv]
# exclude-newer = "2026-01-01T00:00:00Z"
# ///
import six
"""


def test_script_block():
    block = python.script_block(BASIC)
    assert block is not None
    assert block.first_line == 3
    assert block.toml.startswith('requires-python = ">=3.11"\ndependencies = [\n  "six')
    assert block.prefixes[:2] == (2, 2)
    assert block.prefixes[6] == 1  # la ligne « # » seule


def test_parse_script_locations():
    found = python.parse_script("run.py", BASIC)
    assert [(d.name, d.constraint, d.scope) for d in found] == [
        ("six", ">=1.16", Scope.RUNTIME),
        ("idna", "", Scope.RUNTIME),
        ("rich", "==13.*", Scope.RUNTIME),
    ]
    for dependency in found:
        assert dependency.location is not None
        assert dependency.location.extract(BASIC) == dependency.constraint
    assert found[0].location.line == 5
    assert (
        found[1].location.column == found[1].location.end_column
    )  # là où s'ajouterait une version


def test_script_requires_python():
    assert python.script_requires_python(BASIC) == ">=3.11"
    assert python.script_requires_python("import os\n") is None
    assert python.script_requires_python("# /// script\n# x = [\n# ///\n") is None


def test_no_block():
    assert python.script_block("import os\n") is None
    assert python.parse_script("run.py", "import os\n") == []
    assert not python.has_script_block("import os\n")


def test_block_after_the_code_and_in_a_string():
    late = 'import sys\n"""\n# /// script\n# dependencies = ["six"]\n# ///\n"""\n'
    (dependency,) = python.parse_script("run.py", late)
    assert (dependency.name, dependency.location.line) == ("six", 4)


def test_another_block_type_is_not_a_script():
    content = '# /// pyproject\n# [project]\n# dependencies = ["six"]\n# ///\n'
    assert python.script_block(content) is None
    assert not python.has_script_block(content)


def test_crlf():
    content = '# /// script\n# dependencies = ["six"]\n# ///\n'.replace("\n", "\r\n")
    # LocalSource lit en convertissant les fins de ligne, comme writers._parsed.
    (dependency,) = python.parse_script("run.py", content.replace("\r\n", "\n"))
    assert dependency.name == "six"


def test_a_bom_hides_the_block():
    # uv ne le voit pas non plus : la première ligne ne commence pas par « # ».
    assert python.script_block("﻿# /// script\n# dependencies = []\n# ///\n") is None


@pytest.mark.parametrize(
    ("content", "error"),
    [
        ('# /// script\n#dependencies = ["six"]\n# ///\n', "s'ouvre sans se fermer"),
        ('# /// script\n# dependencies = ["six"]\n', "s'ouvre sans se fermer"),
        ('# /// script\n# dependencies = ["six"\n# ///\n', "TOML invalide"),
        # Deux blocs : le premier va jusqu'au dernier « # /// », comme pour uv.
        (
            '# /// script\n# dependencies = ["a"]\n# ///\n# /// script\n# dependencies = ["b"]\n'
            "# ///\n",
            "TOML invalide",
        ),
        ('# /// script\n# dependencies = ["a"]\n# ///\n#\n# ///\n', "TOML invalide"),
        (
            '# /// script\n# dependencies = ["a"]\n# ///\nx = 1\n'
            "# /// script\n# dependencies = []\n# ///\n",
            "plusieurs blocs",
        ),
    ],
)
def test_refused_blocks(content, error):
    with pytest.raises(ParseError, match=error):
        python.parse_script("run.py", content)
    assert python.has_script_block(content)


def test_unknown_fields_are_accepted():
    content = '# /// script\n# dependencies = ["six"]\n# foo = 1\n# ///\n'
    assert [d.name for d in python.parse_script("run.py", content)] == ["six"]


def test_uv_sources_make_a_dependency_unverifiable():
    content = (
        "# /// script\n"
        '# dependencies = ["mine", "six"]\n'
        "# [tool.uv.sources]\n"
        '# mine = { git = "https://example.com/mine.git" }\n'
        "# ///\n"
    )
    mine, six = python.parse_script("run.py", content)
    assert mine.unverifiable_reason == REASON_GIT
    assert six.verifiable


def test_invalid_dependency_is_a_notice():
    content = '# /// script\n# dependencies = ["six", "pas valide !"]\n# ///\n'
    project = Project(path=".", ecosystems=[Ecosystem.PYPI], manifests=["run.py"])
    python.parse_project(project, {"run.py": content}.get)
    assert [d.name for d in project.dependencies] == ["six"]
    assert project.notices[0].message == "« pas valide ! » n'est pas une dépendance valide."


def test_is_script():
    assert python.is_script("scripts/run.py")
    assert python.is_script("tool.PYW")
    assert not python.is_script("setup.py")
    assert not python.is_script("index.ts")


# -- Le lockfile d'un script (uv lock --script) ----------------------------------------------


def test_script_lock_gives_installed_versions():
    folder = PROJECTS / "scripts"
    project = Project(
        path=".",
        ecosystems=[Ecosystem.PYPI],
        manifests=["locked.py"],
        lockfiles=["locked.py.lock"],
    )

    def read(path: str) -> str | None:
        file = folder / path
        return file.read_text(encoding="utf-8") if file.is_file() else None

    python.parse_project(project, read)
    directs = [(d.name, d.constraint, d.installed) for d in project.dependencies if d.direct]
    assert directs == [("flask", ">=2.3,<3", "2.3.0")]
    indirect = {d.name for d in project.dependencies if not d.direct}
    assert {"werkzeug", "jinja2", "click", "itsdangerous", "blinker", "markupsafe"} <= indirect
    assert all(d.lockfile == "locked.py.lock" for d in project.dependencies)


def test_parse_lockfile_of_a_script():
    content = (PROJECTS / "scripts" / "locked.py.lock").read_text(encoding="utf-8")
    lock = parse_lockfile("locked.py.lock", content)
    assert {p.name for p in lock.packages} >= {"flask", "werkzeug"}
    with pytest.raises(ValueError):
        parse_lockfile("notes.lock", content)


# -- La réécriture : seulement le bloc -------------------------------------------------------


def test_rewrite_the_block_only(tmp_path):
    script = tmp_path / "run.py"
    script.write_text(BASIC, encoding="utf-8", newline="")
    (six, *_) = python.parse_script("run.py", BASIC)
    assert six.location is not None
    target = Target(path="run.py", location=six.location, old=">=1.16", new=">=1.17")
    (change,) = writers.rewrite(tmp_path, [target])
    assert change.after == BASIC.replace('"six>=1.16"', '"six>=1.17"')
    assert '+#   "six>=1.17",' in change.diff


def test_rewrite_refused_when_the_block_changed(tmp_path):
    script = tmp_path / "run.py"
    script.write_text(BASIC, encoding="utf-8", newline="")
    (six, *_) = python.parse_script("run.py", BASIC)
    assert six.location is not None
    target = Target(path="run.py", location=six.location, old=">=1.15", new=">=1.17")
    with pytest.raises(writers.Refused):
        writers.rewrite(tmp_path, [target])
