"""Position des chaînes d'un document JSON."""

import json

from forceupdate.parsers.json_spans import BOM, string_spans


def spans_and_values(text: str) -> dict[tuple[str | int, ...], str]:
    """Pour chaque chaîne repérée, le texte à sa position ; vérifie qu'il redonne la valeur."""
    data = json.loads(text.removeprefix(BOM))
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


def test_objects_arrays_and_scalars() -> None:
    text = """\
{
  "name": "démo",
  "version": "1.0.0",
  "private": true,
  "dependencies": {
    "lodash": "^4.17.21",
    "@types/node": ">=18 <21"
  },
  "workspaces": ["packages/*", "apps/*"],
  "count": 3, "nothing": null,
  "nested": [{"a": "x"}, ["y", 1.5e3]]
}
"""
    assert spans_and_values(text) == {
        ("name",): "démo",
        ("version",): "1.0.0",
        ("dependencies", "lodash"): "^4.17.21",
        ("dependencies", "@types/node"): ">=18 <21",
        ("workspaces", 0): "packages/*",
        ("workspaces", 1): "apps/*",
        ("nested", 0, "a"): "x",
        ("nested", 1, 0): "y",
    }


def test_minified_document() -> None:
    text = '{"dependencies":{"a":"1.0.0","b":"^2"},"x":[]}'
    spans = string_spans(text)
    assert spans[("dependencies", "b")].line == 1
    assert spans_and_values(text) == {("dependencies", "a"): "1.0.0", ("dependencies", "b"): "^2"}


def test_escaped_keys_are_decoded() -> None:
    text = '{"dependencies": {"a\\"b": "1", "\\u00e9t\\u00e9": "2"}}'
    assert spans_and_values(text) == {("dependencies", 'a"b'): "1", ("dependencies", "été"): "2"}


def test_escapes_in_values() -> None:
    text = '{"a": "x\\"y", "b": "\\u00e9^1.0", "c": "\\ud83d\\ude00 ^2", "d": "\\ud83d\\u0041"}'
    spans = string_spans(text)
    # Un morceau sans échappement garde son emplacement, même après une paire de substituts.
    assert spans[("c",)].location(2, 4).extract(text) == "^2"
    assert spans[("b",)].location(1, 5).extract(text) == "^1.0"
    # Un morceau qui contient un échappement n'en a pas : le texte écrit n'est pas la valeur.
    assert spans[("a",)].location(0, 3) is None
    # Un substitut seul compte pour un caractère, comme pour json.loads.
    assert json.loads(text)["d"] == "\ud83d" + "A"
    assert spans[("d",)].location(0, 2) is None


def test_crlf_and_bom() -> None:
    text = BOM + '{\r\n  "dependencies": {\r\n    "lodash": "^4.17.21"\r\n  }\r\n}\r\n'
    span = string_spans(text)[("dependencies", "lodash")]
    location = span.location(0, len("^4.17.21"))
    assert (location.line, location.column) == (3, 15)
    assert location.extract(text) == "^4.17.21"


def test_duplicate_keys_keep_the_last_value() -> None:
    text = '{"a": "first", "a": "second"}'
    assert spans_and_values(text) == {("a",): "second"}


def test_scalar_document() -> None:
    assert spans_and_values('"seul"') == {(): "seul"}
    assert string_spans("42") == {}
