"""Les positions des scalaires d'un document YAML (``parsers.yaml_spans``)."""

import pytest

from forceupdate.parsers.yaml_spans import string_spans

DOCUMENT = """\
packages:
  - packages/*
catalog:
  is-number: ^7.0.0   # commentaire
  'my-ms': "npm:ms@^2.1.0"
  quoted: 'a''b'
  escaped: "a\\tb"
  folded: >
    ^1.0.0
  continued: ^1.0
    || ^2.0
  empty:
base: &base ^1.0.0
copy: *base
catalogs:
  legacy: {is-odd: ^2.0.0, one: "1"}
"""


def test_scalars_on_one_line_have_their_position() -> None:
    spans = string_spans(DOCUMENT)
    found = {path: span.location(0, len(span.raw)) for path, span in spans.items()}
    assert sorted(found, key=str) == sorted(
        [
            ("packages", 0),
            ("catalog", "is-number"),
            ("catalog", "my-ms"),
            ("catalogs", "legacy", "is-odd"),
            ("catalogs", "legacy", "one"),
        ],
        key=str,
    )
    for path, location in found.items():
        assert location is not None
        assert location.extract(DOCUMENT) == spans[path].raw
    assert spans["catalog", "is-number"].raw == "^7.0.0"
    assert spans["catalog", "my-ms"].raw == "npm:ms@^2.1.0"  # sans les guillemets


@pytest.mark.parametrize(
    "path",
    [
        ("catalog", "quoted"),  # '' : le texte n'est pas la valeur
        ("catalog", "escaped"),  # \t
        ("catalog", "folded"),  # bloc >
        ("catalog", "continued"),  # replié sur la ligne suivante
        ("catalog", "empty"),  # pas de valeur
        ("base",),  # cité ailleurs par un alias
        ("copy",),
    ],
)
def test_what_cannot_be_rewritten_safely_is_left_out(path: tuple[str, ...]) -> None:
    assert path not in string_spans(DOCUMENT)


def test_a_bom_counts_for_the_columns_of_line_1() -> None:
    text = "﻿react: ^18.2.0\n"
    (span,) = string_spans(text).values()
    assert (span.line, span.column) == (1, 8)
    location = span.location(0, len(span.raw))
    assert location is not None and location.extract(text) == "^18.2.0"


def test_the_last_document_is_read() -> None:
    """Comme le pnpm-lock.yaml de pnpm 11+ : le dernier document."""
    text = "a: '1'\n---\nb: '2'\n"
    assert list(string_spans(text)) == [("b",)]
    assert string_spans(text)["b",].line == 3


@pytest.mark.parametrize("text", ["", "catalog: [\n", "a: &x [*x]\n"])
def test_invalid_empty_or_recursive_documents(text: str) -> None:
    assert string_spans(text) == {}
