"""Les index Python déclarés (E33) : uv (``[[tool.uv.index]]``, ``[tool.uv.sources]``, un script
PEP 723, l'environnement), Poetry, PDM, Pipenv, pip (``--index-url``, ``--extra-index-url``,
``--no-index``, ``PIP_INDEX_URL``, ``pip.ini``) ; de bout en bout par le moteur, avec un index
simulé (l'API « simple » en JSON, ou en HTML)."""

import asyncio
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
import respx
from conftest import UserFiles, recorded_responses

from forceupdate import engine
from forceupdate.models import FindingKind, Report
from forceupdate.net import Cache, HttpClient
from forceupdate.registries.pypi import ACCEPT, simple_html_files
from forceupdate.sources import local
from forceupdate.sources.local import LocalSource

MakeTree = Callable[..., Path]
INDEX = "https://pkgs.corp.example/simple"

SIMPLE_JSON = {
    "meta": {"api-version": "1.1"},
    "name": "acme-private",
    "versions": ["1.0.0", "1.4.0"],
    "files": [
        {"filename": "acme_private-1.0.0-py3-none-any.whl", "url": "x", "hashes": {}},
        {"filename": "acme_private-1.4.0-py3-none-any.whl", "url": "x", "hashes": {}},
    ],
}
SIMPLE_HTML = """<!DOCTYPE html><html><body>
<a href="acme_private-1.0.0-py3-none-any.whl#sha256=00"
   data-requires-python="&gt;=3.9">acme_private-1.0.0-py3-none-any.whl</a>
<a href="../../files/acme_private-1.5.0.tar.gz">acme_private-1.5.0.tar.gz</a>
<a href="acme_private-1.6.0-py3-none-any.whl"
   data-yanked="cassée">acme_private-1.6.0-py3-none-any.whl</a>
</body></html>
"""


async def no_sleep(_: float) -> None:
    pass


@contextmanager
def index(html: bool = False, status: int = 200) -> Iterator[dict[str, respx.Route]]:
    """Les réponses enregistrées, plus un index qui sert ``acme-private`` (et pas le reste), et
    une route qui note si PyPI est demandé pour ``acme-private``."""
    extra: dict[str, respx.Route] = {}

    def private(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status)
        if html:
            return httpx.Response(200, text=SIMPLE_HTML, headers={"content-type": "text/html"})
        return httpx.Response(200, json=SIMPLE_JSON, headers={"content-type": ACCEPT})

    def add(router: respx.MockRouter) -> None:
        extra["private"] = router.get(f"{INDEX}/acme-private/").mock(side_effect=private)
        extra["corp-other"] = router.get(url__regex=rf"^{INDEX}/").respond(404)
        extra["pypi-private"] = router.get("https://pypi.org/simple/acme-private/").respond(
            200, json={**SIMPLE_JSON, "versions": ["9.9.9"]}, headers={"content-type": ACCEPT}
        )
        extra["mirror"] = router.get(url__regex=r"^https://mirror\.example/").respond(404)
        extra["extra"] = router.get(url__regex=r"^https://extra\.example/").respond(404)

    with recorded_responses(add) as routes:
        yield {**routes, **extra}


def analyze(path: Path) -> Report:
    async def main() -> Report:
        async with HttpClient(sleep=no_sleep) as http:
            return await engine.analyze(LocalSource(path), http=http, cache=Cache.disabled())

    return asyncio.run(main())


def findings(report: Report, name: str) -> list[tuple[FindingKind, str]]:
    return [
        (f.kind, f.message)
        for project in report.projects
        for f in project.findings
        if f.dependency is not None and f.dependency.name == name
    ]


def osv_names(routes: dict[str, respx.Route]) -> set[str]:
    return {
        query["package"]["name"]
        for call in routes["osv:querybatch"].calls
        for query in json.loads(call.request.content)["queries"]
    }


UV_PROJECT = f"""\
[project]
name = "app"
version = "0.1.0"
dependencies = ["acme-private>=1.0", "flask==2.0.1"]

[[tool.uv.index]]
name = "corp"
url = "{INDEX}/"
explicit = true

[tool.uv.sources]
acme-private = {{ index = "corp" }}
"""


def test_a_uv_package_attached_to_its_index(make_tree: MakeTree, user_files: UserFiles) -> None:
    root = make_tree({"pyproject.toml": UV_PROJECT})
    user_files.write(".netrc", "machine pkgs.corp.example login jo password pw\n")
    with index() as routes:
        report = analyze(root)
    assert routes["private"].calls.last.request.headers["authorization"] == "Basic am86cHc="
    assert routes["pypi-private"].call_count == 0
    assert routes["corp-other"].call_count == 0  # flask : PyPI seul (l'index est « explicit »)
    assert routes["flask"].call_count == 1
    assert "acme-private" not in osv_names(routes)
    assert "flask" in osv_names(routes)
    ((kind, message),) = findings(report, "acme-private")
    assert kind is FindingKind.OUTDATED
    assert "1.4.0" in message


def test_an_undeclared_index_stays_unverifiable(make_tree: MakeTree) -> None:
    pyproject = UV_PROJECT.replace('name = "corp"', 'name = "other"')
    root = make_tree({"pyproject.toml": pyproject})
    with index() as routes:
        report = analyze(root)
    assert routes["pypi-private"].call_count == 0
    ((kind, message),) = findings(report, "acme-private")
    assert kind is FindingKind.UNVERIFIABLE
    assert message == "Non vérifiable : vient de l'index « corp », pas de PyPI."


def test_the_html_simple_api(make_tree: MakeTree) -> None:
    root = make_tree({"pyproject.toml": UV_PROJECT})
    with index(html=True) as routes:
        report = analyze(root)
    accept = routes["private"].calls.last.request.headers["accept"]
    assert accept.startswith("application/vnd.pypi.simple.v1+json")
    ((kind, message),) = findings(report, "acme-private")
    assert kind is FindingKind.OUTDATED
    assert "1.5.0" in message  # 1.6.0 est retirée


def test_simple_html_files() -> None:
    assert simple_html_files(SIMPLE_HTML) == [
        {"filename": "acme_private-1.0.0-py3-none-any.whl", "requires-python": ">=3.9"},
        {"filename": "acme_private-1.5.0.tar.gz"},
        {"filename": "acme_private-1.6.0-py3-none-any.whl", "yanked": "cassée"},
    ]


def test_index_url_of_a_requirements_file(make_tree: MakeTree) -> None:
    root = make_tree(
        {
            "requirements.txt": "-i https://jo:pw@pkgs.corp.example/simple/\n"
            "acme-private==1.0.0\nflask==2.0.1\n"
        }
    )
    with index() as routes:
        report = analyze(root)
    assert routes["private"].calls.last.request.headers["authorization"] == "Basic am86cHc="
    assert routes["corp-other"].call_count == 1  # flask, demandé à l'index qui remplace PyPI
    assert routes["flask"].call_count == 0
    assert routes["pypi-private"].call_count == 0
    assert "flask" in osv_names(routes)  # un miroir sert des paquets publics
    assert findings(report, "flask") == [
        (FindingKind.UNVERIFIABLE, "flask est introuvable sur pkgs.corp.example.")
    ]
    # L'adresse et ses identifiants ne sont pas dans le rapport.
    assert "jo:pw" not in json.dumps([n.message for p in report.projects for n in p.notices])


def test_extra_index_comes_first(make_tree: MakeTree) -> None:
    root = make_tree(
        {"requirements.txt": f"--extra-index-url {INDEX}\nacme-private==1.0.0\nflask==2.0.1\n"}
    )
    with index() as routes:
        analyze(root)
    assert routes["private"].call_count == 1
    assert routes["pypi-private"].call_count == 0  # trouvé sur l'index d'abord
    assert routes["flask"].call_count == 1  # pas sur l'index : PyPI


def test_a_variable_of_a_requirements_file_is_never_expanded(
    make_tree: MakeTree, user_files: UserFiles
) -> None:
    root = make_tree(
        {
            "requirements.txt": "--extra-index-url https://${USER}:${TOKEN}@pkgs.corp.example/simple\n"
            "acme-private==1.0.0\n"
        }
    )
    user_files.env.update({"USER": "jo", "TOKEN": "pw"})
    with index() as routes:
        report = analyze(root)
    assert "authorization" not in routes["private"].calls.last.request.headers
    (project,) = report.projects
    assert any("variable d'environnement" in n.message for n in project.notices)


def test_no_index(make_tree: MakeTree) -> None:
    root = make_tree({"requirements.txt": "--no-index\n-f ./wheels\nflask==2.0.1\n"})
    with index() as routes:
        report = analyze(root)
    assert routes["flask"].call_count == 0
    ((kind, message),) = findings(report, "flask")
    assert kind is FindingKind.UNVERIFIABLE
    assert "--no-index" in message


def test_pip_environment_and_configuration(make_tree: MakeTree, user_files: UserFiles) -> None:
    root = make_tree({"requirements.txt": "acme-private==1.0.0\n"})
    user_files.write("AppData/Roaming/pip/pip.ini", f"[global]\nextra-index-url = {INDEX}\n")
    user_files.write(".config/pip/pip.conf", f"[global]\nextra-index-url = {INDEX}\n")
    user_files.write(
        "Library/Application Support/pip/pip.conf", f"[global]\nextra-index-url = {INDEX}\n"
    )
    with index() as routes:
        analyze(root)
    assert routes["private"].call_count == 1
    assert routes["pypi-private"].call_count == 0

    user_files.env["PIP_INDEX_URL"] = "https://${CORP_USER}:pw@pkgs.corp.example/simple"
    user_files.env["CORP_USER"] = "jo"
    with index() as routes:
        analyze(root)
    assert routes["private"].calls.last.request.headers["authorization"] == "Basic am86cHc="


def test_poetry_sources(make_tree: MakeTree) -> None:
    pyproject = f"""\
[tool.poetry]
name = "app"
version = "0.1.0"

[tool.poetry.dependencies]
python = "^3.11"
acme-private = {{ version = "^1.0", source = "corp" }}
flask = "2.0.1"

[[tool.poetry.source]]
name = "corp"
url = "{INDEX}"
priority = "explicit"

[[tool.poetry.source]]
name = "mirror"
url = "https://mirror.example/simple"
priority = "primary"
"""
    root = make_tree({"pyproject.toml": pyproject})
    with index() as routes:
        report = analyze(root)
    assert routes["private"].call_count == 1
    assert routes["mirror"].call_count == 1  # flask : la source primary
    assert routes["flask"].call_count == 0  # une source primary retire PyPI
    assert routes["pypi-private"].call_count == 0
    assert findings(report, "acme-private")[0][0] is FindingKind.OUTDATED


def test_pipfile_index(make_tree: MakeTree) -> None:
    pipfile = f"""\
[[source]]
name = "pypi"
url = "https://pypi.org/simple"
verify_ssl = true

[[source]]
name = "corp"
url = "{INDEX}"
verify_ssl = true

[packages]
acme-private = {{ version = "==1.0.0", index = "corp" }}
flask = "==2.0.1"
"""
    root = make_tree({"Pipfile": pipfile})
    with index() as routes:
        analyze(root)
    assert routes["private"].call_count == 1
    assert routes["pypi-private"].call_count == 0
    assert routes["corp-other"].call_count == 1  # flask : l'index en plus d'abord, puis PyPI
    assert routes["flask"].call_count == 1


def test_pdm_include_packages(make_tree: MakeTree) -> None:
    pyproject = f"""\
[project]
name = "app"
version = "0.1.0"
dependencies = ["acme-private>=1.0", "flask==2.0.1"]

[tool.pdm]
[[tool.pdm.source]]
name = "corp"
url = "{INDEX}"
include_packages = ["acme-*"]
"""
    root = make_tree({"pyproject.toml": pyproject})
    with index() as routes:
        analyze(root)
    assert routes["private"].call_count == 1
    assert routes["pypi-private"].call_count == 0
    assert "acme-private" not in osv_names(routes)
    assert routes["corp-other"].call_count == 0
    assert routes["flask"].call_count == 1


def test_a_script_index(
    make_tree: MakeTree, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """E28 : ``[tool.uv] index`` d'un script."""
    monkeypatch.setattr(local, "_home", lambda: tmp_path.resolve())
    script = f"""\
# /// script
# dependencies = ["acme-private>=1.0"]
#
# [[tool.uv.index]]
# name = "corp"
# url = "{INDEX}"
# default = true
# ///
import acme_private
"""
    root = make_tree({"tool.py": script})
    with index() as routes:
        report = analyze(root / "tool.py")
    assert routes["private"].call_count == 1
    assert routes["pypi-private"].call_count == 0
    assert findings(report, "acme-private")[0][0] is FindingKind.OUTDATED


def test_uv_environment_and_named_credentials(make_tree: MakeTree, user_files: UserFiles) -> None:
    root = make_tree({"pyproject.toml": UV_PROJECT, "uv.lock": "version = 1\n"})
    user_files.env["UV_INDEX_CORP_PASSWORD"] = "pw"
    user_files.env["UV_INDEX"] = "extra=https://extra.example/simple"
    with index() as routes:
        report = analyze(root)
    assert "authorization" not in routes["private"].calls.last.request.headers
    assert routes["extra"].call_count == 1  # flask : UV_INDEX d'abord, puis PyPI
    (project,) = report.projects
    assert any("UV_INDEX_CORP_PASSWORD" in n.message for n in project.notices)
