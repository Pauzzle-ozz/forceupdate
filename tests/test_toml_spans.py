"""Position des chaînes d'un document TOML."""

import tomllib

import pytest

from forceupdate.models import Location
from forceupdate.parsers.toml_spans import StringSpan, decode_basic_string, string_spans


def spans_and_values(text: str) -> dict[tuple[str | int, ...], str]:
    """Pour chaque chaîne repérée, le texte à sa position ; vérifie qu'il redonne la valeur."""
    data = tomllib.loads(text)
    found = {}
    for path, span in string_spans(text).items():
        value = data
        for key in path:
            value = value[key]
        location = span.location(0, len(value))
        assert location is not None, path
        assert location.extract(text) == value, path
        found[path] = value
    return found


def test_tables_arrays_and_inline_tables() -> None:
    text = """\
title = "démo"  # commentaire

[project]
name = 'app'
dependencies = [
    "requests>=2.31",  # client HTTP
    # une ligne de commentaire
    'flask[async] ==3.0',
]

[project.optional-dependencies]
dev = ["pytest"]

[tool.poetry.dependencies]
python = "^3.11"
click = { version = "^8.1", optional = true, extras = ["x"] }
"PyYAML" = "6.0.2"
a.b = "pointée"
"""
    assert spans_and_values(text) == {
        ("title",): "démo",
        ("project", "name"): "app",
        ("project", "dependencies", 0): "requests>=2.31",
        ("project", "dependencies", 1): "flask[async] ==3.0",
        ("project", "optional-dependencies", "dev", 0): "pytest",
        ("tool", "poetry", "dependencies", "python"): "^3.11",
        ("tool", "poetry", "dependencies", "click", "version"): "^8.1",
        ("tool", "poetry", "dependencies", "click", "extras", 0): "x",
        ("tool", "poetry", "dependencies", "PyYAML"): "6.0.2",
        ("tool", "poetry", "dependencies", "a", "b"): "pointée",
    }


def test_arrays_of_tables_are_numbered() -> None:
    text = """\
[[package]]
name = "a"

[package.source]
registry = "https://pypi.org/simple"

[[package]]
name = "b"
dependencies = [{ name = "a", extra = ["x"] }]

[[package.wheels]]
url = "https://example.org/b.whl"
"""
    assert spans_and_values(text) == {
        ("package", 0, "name"): "a",
        ("package", 0, "source", "registry"): "https://pypi.org/simple",
        ("package", 1, "name"): "b",
        ("package", 1, "dependencies", 0, "name"): "a",
        ("package", 1, "dependencies", 0, "extra", 0): "x",
        ("package", 1, "wheels", 0, "url"): "https://example.org/b.whl",
    }


def test_other_values_and_multiline_strings_are_skipped() -> None:
    text = '''\
n = 1
f = 1.5e3
ok = true
when = 1979-05-27 07:32:00Z
nested = [[1, 2], ["x"]]
long = """
plusieurs
lignes ""\"""
raw = \'\'\'brut\'\'\'
after = "après"
'''
    assert spans_and_values(text) == {("nested", 1, 0): "x", ("after",): "après"}


def test_lines_and_columns_follow_location_conventions() -> None:
    text = 'a = 1\r\n[t]\r\n  key   =   "été"\r\n'
    assert string_spans(text)[("t", "key")] == StringSpan(
        line=3, column=13, raw="été", literal=False
    )


def test_escapes_make_their_part_unlocatable() -> None:
    text = 'dep = "foo>=1.0 ; sys_platform == \\"win32\\""\n'
    span = string_spans(text)[("dep",)]
    value = tomllib.loads(text)["dep"]
    assert value == 'foo>=1.0 ; sys_platform == "win32"'
    # Avant l'échappement, le texte écrit est la valeur : on sait le situer.
    assert span.location(3, 8) == Location(line=1, column=10, end_column=15)
    assert span.location(3, 8).extract(text) == ">=1.0"
    # Un morceau qui contient un échappement ne se situe pas.
    assert span.location(0, len(value)) is None


def test_quoted_keys_are_decoded() -> None:
    text = '"a.b" = "x"\n"\\u00e9t\\u00e9" = "y"\n'
    assert set(string_spans(text)) == {("a.b",), ("été",)}


@pytest.mark.parametrize(
    ("raw", "value"),
    [
        ("simple", "simple"),
        ('a\\"b', 'a"b'),
        ("tab\\there", "tab\there"),
        ("\\u00e9\\U0001F600", "é\U0001f600"),
        ("back\\\\slash", "back\\slash"),
    ],
)
def test_decode_basic_string(raw: str, value: str) -> None:
    assert decode_basic_string(raw) == value
    assert tomllib.loads(f'v = "{raw}"')["v"] == value


def test_empty_and_comment_only_documents() -> None:
    assert string_spans("") == {}
    assert string_spans("# rien\n\n") == {}
