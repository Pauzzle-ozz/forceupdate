"""Les dépendances d'un fichier de code seul (E28) : des imports aux paquets, et le bloc PEP 723
d'un script."""

import sys

import pytest

from forceupdate.models import Dependency, Ecosystem, Project, Scope
from forceupdate.parsers import code, parse_project
from forceupdate.parsers.base import ParseError
from forceupdate.parsers.code import (
    IMPORT_PACKAGES,
    NODE_BUILTINS,
    PYTHON_STDLIB,
    candidates,
    go_candidates,
    imported,
    is_go_module_path,
    npm_package,
    python_package,
)


def reader(files: dict[str, str]):
    return files.get


# -- Python ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("module", "package"),
    [
        ("yaml", "pyyaml"),
        ("cv2", "opencv-python"),
        ("PIL", "pillow"),
        ("sklearn", "scikit-learn"),
        ("bs4", "beautifulsoup4"),
        ("dateutil", "python-dateutil"),
        ("requests", "requests"),
        ("Flask_SQLAlchemy", "flask-sqlalchemy"),
        ("google.protobuf.json_format", "protobuf"),
        ("google.oauth2.credentials", "google-auth"),
        ("google.cloud.storage", "google-cloud-storage"),
        ("google.cloud.bigquery_storage", "google-cloud-bigquery-storage"),
        ("azure.storage.blob", "azure-storage-blob"),
        ("zope.interface", "zope-interface"),
        ("ruamel.yaml", "ruamel-yaml"),
    ],
)
def test_python_package(module, package):
    assert python_package(module) == package


def test_python_table_keys_are_not_in_the_stdlib():
    assert not {key.split(".")[0] for key in IMPORT_PACKAGES} & PYTHON_STDLIB


def test_python_stdlib_includes_removed_modules():
    assert {"distutils", "imp", "cgi", "telnetlib"} <= PYTHON_STDLIB
    assert set(sys.stdlib_module_names) <= PYTHON_STDLIB


def test_python_imports_to_dependencies():
    content = (
        "import os\n"
        "import yaml\n"
        "from yaml import safe_load\n"
        "import cv2\n"
        "import helpers\n"
        "import pkg\n"
        "try:\n"
        "    import ujson\n"
        "except ImportError:\n"
        "    ujson = None\n"
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    import pandas\n"
    )
    files = {"scripts/helpers.py": "", "scripts/pkg/__init__.py": ""}
    found = imported("scripts/run.py", content, Ecosystem.PYPI, reader(files))
    assert [(d.name, d.imported, d.scope) for d in found] == [
        ("pyyaml", "yaml", Scope.RUNTIME),
        ("opencv-python", "cv2", Scope.RUNTIME),
        ("ujson", "ujson", Scope.OPTIONAL),
        ("pandas", "pandas", Scope.DEV),
    ]
    assert all(d.constraint == "" and d.location is None and d.direct for d in found)
    assert all(d.file == "scripts/run.py" and d.installed is None for d in found)


def test_python_import_once_runtime_wins():
    content = "try:\n    import requests\nexcept ImportError:\n    pass\nimport requests\n"
    (dependency,) = imported("run.py", content, Ecosystem.PYPI)
    assert dependency.scope is Scope.RUNTIME


def test_python_namespace_imports():
    content = (
        "from google.cloud import storage, bigquery\n"
        "from azure.identity import DefaultAzureCredential\n"
        "from google import genai\n"
        "import google.protobuf\n"
    )
    found = imported("run.py", content, Ecosystem.PYPI)
    assert [(d.name, d.imported) for d in found] == [
        ("google-cloud-storage", "google.cloud.storage"),
        ("google-cloud-bigquery", "google.cloud.bigquery"),
        ("azure-identity", "azure.identity"),
        ("google-genai", "google.genai"),
        ("protobuf", "google.protobuf"),
    ]


def test_python_candidates():
    def dependency(name: str, written: str | None) -> Dependency:
        return Dependency(ecosystem=Ecosystem.PYPI, name=name, file="run.py", imported=written)

    storage = dependency("google-cloud-storage", "google.cloud.storage")
    assert candidates(storage) == ["google-cloud-storage", "google-cloud"]
    assert candidates(dependency("protobuf", "google.protobuf")) == ["protobuf"]
    assert candidates(dependency("pyyaml", "yaml")) == []
    assert candidates(dependency("flask", None)) == []


# -- JavaScript ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("specifier", "package"),
    [
        ("lodash", "lodash"),
        ("lodash/fp", "lodash"),
        ("@hapi/joi", "@hapi/joi"),
        ("@scope/pkg/deep/file.js", "@scope/pkg"),
        ("JSONStream", "JSONStream"),
        ("test", "test"),
        ("punycode/", "punycode"),
        ("svgs/icon.svg?raw", "svgs"),
        ("fs", None),
        ("fs/promises", None),
        ("node:fs", None),
        ("node:test", None),
        ("./util", None),
        ("../up", None),
        ("/abs/path", None),
        ("#internal", None),
        ("@/components/Button", None),
        ("~/lib", None),
        ("https://esm.sh/react", None),
        ("npm:chalk@5", None),
        ("jsr:@std/path", None),
        ("bun:test", None),
        ("@scope", None),
        ("", None),
    ],
)
def test_npm_package(specifier, package):
    assert npm_package(specifier) == package


def test_node_builtins_are_the_bare_ones():
    assert len(NODE_BUILTINS) == 68
    assert "test" not in NODE_BUILTINS and "sqlite" not in NODE_BUILTINS


def test_js_imports_to_dependencies():
    content = (
        "import fp from 'lodash/fp'\n"
        "import _ from 'lodash'\n"
        "import type { Color } from 'colors'\n"
        "import { readFile } from 'node:fs/promises'\n"
        "const pad = require('left-pad')\n"
    )
    found = imported("src/index.ts", content, Ecosystem.NPM)
    assert [(d.name, d.imported, d.scope) for d in found] == [
        ("lodash", "lodash/fp", Scope.RUNTIME),
        ("colors", "colors", Scope.DEV),
        ("left-pad", "left-pad", Scope.RUNTIME),
    ]


# -- Go --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "module"),
    [
        ("fmt", False),
        ("net/http", False),
        ("C", False),
        ("./local", False),
        ("golang.org/x/text/language", True),
        ("gopkg.in/yaml.v3", True),
    ],
)
def test_is_go_module_path(path, module):
    assert is_go_module_path(path) is module


def test_go_candidates():
    assert go_candidates("golang.org/x/text/language") == [
        "golang.org/x/text/language",
        "golang.org/x/text",
    ]
    assert go_candidates("github.com/go-chi/chi/v5/middleware") == [
        "github.com/go-chi/chi/v5/middleware",
        "github.com/go-chi/chi/v5",
        "github.com/go-chi/chi",
    ]
    assert go_candidates("go.uber.org/zap/zapcore") == [
        "go.uber.org/zap/zapcore",
        "go.uber.org/zap",
        "go.uber.org",
    ]


def test_go_imports_to_dependencies():
    content = (
        "package main\n\n"
        'import (\n\t"fmt"\n\t"golang.org/x/text/cases"\n\t"golang.org/x/text/language"\n'
        '\t"C"\n)\n'
    )
    found = imported("main.go", content, Ecosystem.GO)
    assert [(d.name, d.imported) for d in found] == [
        ("golang.org/x/text/cases", "golang.org/x/text/cases"),
        ("golang.org/x/text/language", "golang.org/x/text/language"),
    ]
    assert candidates(found[0]) == ["golang.org/x/text/cases", "golang.org/x/text"]


# -- Le projet d'un fichier de code seul -------------------------------------------------------


def project_of(path: str, ecosystem: Ecosystem | None, lockfiles: list[str] | None = None):
    return Project(
        path=".",
        ecosystems=[ecosystem] if ecosystem else [],
        manifests=[path],
        lockfiles=lockfiles or [],
    )


def test_parse_project_reads_imports():
    project = project_of("run.py", Ecosystem.PYPI)
    parse_project(project, reader({"run.py": "import requests\n"}))
    assert [d.name for d in project.dependencies] == ["requests"]
    assert project.notices == []


def test_parse_project_reads_a_script_block():
    content = '# /// script\n# requires-python = ">=3.11"\n# dependencies = ["flask>=2"]\n# ///\n'
    content += "import requests\n"
    project = project_of("run.py", Ecosystem.PYPI)
    parse_project(project, reader({"run.py": content}))
    assert [(d.name, d.constraint, d.imported) for d in project.dependencies] == [
        ("flask", ">=2", None)
    ]
    (runtime,) = project.runtimes
    assert (runtime.product, runtime.version, runtime.approximate) == ("python", "3.11", True)
    assert runtime.source == 'requires-python = ">=3.11"'


def test_parse_project_broken_block_is_a_notice():
    content = "# /// script\n#dependencies = []\n# ///\nimport requests\n"
    project = project_of("run.py", Ecosystem.PYPI)
    parse_project(project, reader({"run.py": content}))
    assert project.dependencies == []
    (notice,) = project.notices
    assert "uv refuse ce script" in notice.message


def test_parse_project_unreadable_python():
    project = project_of("run.py", Ecosystem.PYPI)
    parse_project(project, reader({"run.py": "def (:\n"}))
    (notice,) = project.notices
    assert notice.message.startswith("ne se lit pas comme du Python")


def test_parse_project_missing_file():
    project = project_of("run.py", Ecosystem.PYPI)
    parse_project(project, reader({}))
    assert project.notices[0].message.startswith("introuvable")


def test_parse_project_language_without_import_reader():
    project = project_of("App.java", Ecosystem.MAVEN)
    parse_project(project, reader({"App.java": "import org.junit.Test;\n"}))
    assert project.dependencies == []
    assert "ne lit pas les imports" in project.notices[0].message


def test_code_parse_project_skips_real_manifests():
    project = Project(path=".", ecosystems=[Ecosystem.PYPI], manifests=["requirements.txt"])
    code.parse_project(project, reader({"requirements.txt": "flask\n"}))
    assert project.dependencies == []


# -- E34 : Jupyter, Vue, Svelte, importlib, Deno, tsconfig.json --------------------------------


NOTEBOOK = {
    "cells": [
        {"cell_type": "markdown", "source": ["# import pas_un_import\n"]},
        {"cell_type": "code", "source": ["%matplotlib inline\n", "import numpy as np\n"]},
        {"cell_type": "code", "source": "!pip install requests\nimport requests"},
        {"cell_type": "code", "source": ["%%bash\n", "import pas_du_python\n"]},
        {"cell_type": "code", "source": ["await quelque_chose()\n", "import pandas\n"]},
        {"cell_type": "code", "source": ["x = (\n", "import ne_se_lit_pas\n"]},
        {"cell_type": "code", "source": ["from sklearn import svm\n"]},
    ],
    "metadata": {},
    "nbformat": 4,
}


def test_notebook_imports():
    import json

    found = imported("analyse.ipynb", json.dumps(NOTEBOOK), Ecosystem.PYPI)
    # « await » au premier niveau se lit (ast l'accepte, comme Jupyter) ; une cellule qui ne se
    # lit pas est sautée, les autres restent.
    assert [d.name for d in found] == ["numpy", "requests", "pandas", "scikit-learn"]


def test_not_a_notebook():
    with pytest.raises(ParseError):
        imported("x.ipynb", "pas du json", Ecosystem.PYPI)


def test_vue_and_svelte_scripts():
    vue = """<template><div>{{ msg }}</div></template>
<script setup lang="ts">
import { ref } from 'vue'
import axios from 'axios'
</script>
<style>@import 'pas-un-paquet';</style>
"""
    found = imported("App.vue", vue, Ecosystem.NPM)
    assert [(d.name, d.imported) for d in found] == [("vue", "vue"), ("axios", "axios")]
    svelte = """<script context="module">
  import dayjs from 'dayjs'
</script>
<script>
  import { onMount } from 'svelte'
</script>
<h1>import fake from 'pas-un-paquet'</h1>
"""
    assert [d.name for d in imported("Page.svelte", svelte, Ecosystem.NPM)] == ["dayjs", "svelte"]


def test_importlib_with_a_written_name():
    content = (
        "import importlib\n"
        "yaml = importlib.import_module('yaml')\n"
        "from importlib import import_module\n"
        "toml = import_module('tomli')\n"
        "attrs = __import__('attr')\n"
        "rel = import_module('.local', package='pkg')\n"
        "name = 'x'\n"
        "dyn = importlib.import_module(name)\n"
    )
    found = imported("script.py", content, Ecosystem.PYPI)
    assert [d.name for d in found] == ["pyyaml", "tomli", "attrs"]


def test_deno_specifiers():
    content = (
        'import express from "npm:express@4.18.2"\n'
        'import chalk from "npm:chalk@^5/source/index.js"\n'
        'import { z } from "npm:@zod/mini@4.1.0"\n'
        'import { assertEquals } from "jsr:@std/assert@^1.0.0"\n'
        'import { serve } from "https://deno.land/std@0.200.0/http/server.ts"\n'
    )
    found = imported("main.ts", content, Ecosystem.NPM)
    assert [(d.name, d.constraint, d.unverifiable_reason) for d in found] == [
        ("express", "4.18.2", None),
        ("chalk", "^5", None),
        ("@zod/mini", "4.1.0", None),
        ("jsr:@std/assert", "^1.0.0", code.REASON_JSR),
    ]
    assert all(d.location is None for d in found)  # à réécrire à la main


def test_tsconfig_paths_and_base_url():
    files = {
        "app/tsconfig.json": """{
  // des commentaires, comme tsc les accepte
  "compilerOptions": {
    "baseUrl": ".",
    "paths": { "@app/*": ["src/*"], "config": ["src/config.ts"], },
  },
}""",
        "app/src/utils/date.ts": "export const x = 1\n",
    }
    content = (
        "import { x } from 'src/utils/date'\n"
        "import { y } from '@app/thing'\n"
        "import conf from 'config'\n"
        "import lodash from 'lodash'\n"
        "import { z } from 'src/missing'\n"
    )
    found = imported("app/src/index.ts", content, Ecosystem.NPM, reader(files))
    # src/missing : rien sous baseUrl, c'est le paquet « src » pour forceupdate.
    assert [d.name for d in found] == ["lodash", "src"]
