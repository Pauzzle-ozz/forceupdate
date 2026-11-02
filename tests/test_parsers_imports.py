"""Les imports d'un fichier de code (E28) : Python par ``ast``, JavaScript et TypeScript, Go par
un lexer. Jamais exécutés."""

import pytest

from forceupdate.parsers.base import ParseError
from forceupdate.parsers.imports import go_imports, js_imports, python_imports

# -- Python ----------------------------------------------------------------------------------


def test_python_imports_in_order():
    content = (
        "import os, sys\n"
        "import yaml\n"
        "import google.cloud.storage as gcs\n"
        "from google.cloud import bigquery, storage\n"
        "from PIL import Image\n"
        "def f():\n"
        "    import numpy as np\n"
    )
    found = [(i.module, i.line, i.names) for i in python_imports(content)]
    assert found == [
        ("os", 1, ()),
        ("sys", 1, ()),
        ("yaml", 2, ()),
        ("google.cloud.storage", 3, ()),
        ("google.cloud", 4, ("bigquery", "storage")),
        ("PIL", 5, ("Image",)),
        ("numpy", 7, ()),
    ]


def test_python_relative_imports_are_skipped():
    found = python_imports("from . import local\nfrom .mod import thing\nfrom ..up import x\n")
    assert found == []


def test_python_star_import_keeps_the_module():
    (item,) = python_imports("from os.path import *\n")
    assert (item.module, item.names) == ("os.path", ())


@pytest.mark.parametrize(
    "handler", ["ImportError", "ModuleNotFoundError", "(ImportError, OSError)", "Exception", ""]
)
def test_python_guarded_imports_are_optional(handler):
    content = (
        f"try:\n    import ujson as json\nexcept {handler}:\n    import json\nimport requests\n"
    )
    found = {i.module: i.optional for i in python_imports(content)}
    assert found == {"ujson": True, "json": True, "requests": False}


def test_python_try_without_import_error_is_not_optional():
    content = "try:\n    import requests\nexcept KeyError:\n    pass\n"
    (item,) = python_imports(content)
    assert not item.optional


def test_python_else_and_finally_are_not_optional():
    content = (
        "try:\n    pass\nexcept ImportError:\n    pass\n"
        "else:\n    import a\nfinally:\n    import b\n"
    )
    assert [i.optional for i in python_imports(content)] == [False, False]


def test_python_type_checking_imports_are_types_only():
    content = (
        "import typing\n"
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from pandas import DataFrame\n"
        "if typing.TYPE_CHECKING:\n"
        "    import numpy\n"
        "else:\n"
        "    import attrs\n"
    )
    found = {i.module: i.types_only for i in python_imports(content)}
    assert found["pandas"] and found["numpy"]
    assert not found["attrs"] and not found["typing"]


def test_python_syntax_error():
    with pytest.raises(ParseError, match="ligne 1"):
        python_imports("print 'python 2'\n")


def test_python_null_byte():
    with pytest.raises(ParseError, match="Python"):
        python_imports("import os\0\n")


def test_python_is_never_run(tmp_path):
    marker = tmp_path / "ran"
    content = f"open({str(marker)!r}, 'w').write('x')\nimport requests\n"
    assert [i.module for i in python_imports(content)] == ["requests"]
    assert not marker.exists()


# -- JavaScript, TypeScript ------------------------------------------------------------------

JS = r"""#!/usr/bin/env node
// import fake from 'commentaire'
/* require('aussi-commentaire') */
import React, { useState } from 'react'
import * as fs from "node:fs"
import type { Foo } from '@scope/types-only'
import type from 'type-package'
import { from } from 'from-pkg'
import './side-effect.css'
export * from '@scope/re-export/sub'
export { a, b } from "lodash/fp"
export type { T } from 'exported-type'
export const x = 1
const lazy = await import('lazy-pkg')
const cjs = require("cjs-pkg")
const notreq = obj.require('nope')
const meta = import.meta.url
const re = /import x from 'regex'/g
const s = "import y from 'string'"
const t = `template ${require('in-template')} ${ { a: `nested ${import('deep')}` }.a } import 'no'`
const div = a / b / c
const jsx = <p>l'apostrophe ne casse rien</p>
import z = require('ts-import-equals')
import later from 'after-jsx'
"""


def test_js_imports():
    found = [(i.module, i.line, i.types_only) for i in js_imports(JS)]
    assert found == [
        ("react", 4, False),
        ("node:fs", 5, False),
        ("@scope/types-only", 6, True),
        ("type-package", 7, False),
        ("from-pkg", 8, False),
        ("./side-effect.css", 9, False),
        ("@scope/re-export/sub", 10, False),
        ("lodash/fp", 11, False),
        ("exported-type", 12, True),
        ("lazy-pkg", 14, False),
        ("cjs-pkg", 15, False),
        ("in-template", 20, False),
        ("deep", 20, False),
        ("ts-import-equals", 23, False),
        ("after-jsx", 24, False),
    ]


def test_js_dynamic_import_with_options():
    found = js_imports("const m = await import('pkg', { with: { type: 'json' } })\n")
    assert [i.module for i in found] == ["pkg"]


def test_js_dynamic_import_of_a_variable_is_skipped():
    assert js_imports("const m = await import(name)\nrequire(other)\n") == []


def test_js_multiline_import():
    content = "import {\n  a,\n  b,\n} from 'multi'\n"
    assert [(i.module, i.line) for i in js_imports(content)] == [("multi", 1)]


def test_js_unterminated_string_stops_at_the_end_of_its_line():
    content = "const x = 'oups\nimport ok from 'ok'\n"
    assert [i.module for i in js_imports(content)] == ["ok"]


def test_js_division_after_a_closing_paren():
    content = "const r = (a) / 2 / (b)\nimport ok from 'ok'\n"
    assert [i.module for i in js_imports(content)] == ["ok"]


def test_js_regex_after_return():
    content = "function f() { return /'/.test(x) }\nimport ok from 'ok'\n"
    assert [i.module for i in js_imports(content)] == ["ok"]


def test_js_regex_with_a_slash_in_a_class():
    content = "const r = /[/']/\nimport ok from 'ok'\n"
    assert [i.module for i in js_imports(content)] == ["ok"]


def test_js_import_without_from_is_skipped():
    assert js_imports("import x\nconst y = 1\n") == []


# -- Go --------------------------------------------------------------------------------------

GO = """// Package main
package main

import "fmt"
import f "golang.org/x/text/language"
import (
	"net/http"
	_ "github.com/mattn/go-sqlite3"
	. "github.com/go-chi/chi/v5/middleware"
	"C"
	/* un commentaire */ "github.com/google/uuid"
	raw `example.com/raw`
)

func main() { var s = "import \\"fake\\"" ; fmt.Println(s) }

import "after/func"
"""


def test_go_imports():
    found = [(i.module, i.line) for i in go_imports(GO)]
    assert found == [
        ("fmt", 4),
        ("golang.org/x/text/language", 5),
        ("net/http", 7),
        ("github.com/mattn/go-sqlite3", 8),
        ("github.com/go-chi/chi/v5/middleware", 9),
        ("C", 10),
        ("github.com/google/uuid", 11),
        ("example.com/raw", 12),
    ]


def test_go_imports_on_one_line():
    content = 'package main; import ("fmt"; "example.com/a")\n'
    assert [i.module for i in go_imports(content)] == ["fmt", "example.com/a"]


def test_go_without_imports():
    assert go_imports("package lib\n\nfunc F() {}\n") == []


def test_go_needs_a_package_clause():
    with pytest.raises(ParseError, match="package"):
        go_imports('import "fmt"\n')
