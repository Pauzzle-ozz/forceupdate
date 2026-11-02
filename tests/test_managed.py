"""Les versions Maven gérées hors du dépôt (E34) : le pom d'un parent ou d'un BOM distant, lu comme
Maven construit son modèle (l'héritage, puis les BOM importés ; la propriété du plus proche) ; de
bout en bout par le moteur, avec un Maven Central simulé."""

import asyncio
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import respx
from conftest import recorded_responses

from forceupdate import engine
from forceupdate.models import Dependency, Report
from forceupdate.net import Cache, HttpClient
from forceupdate.sources.local import LocalSource

MakeTree = Callable[..., Path]
CENTRAL = "https://repo1.maven.org/maven2"


def pom_url(group: str, artifact: str, version: str) -> str:
    return f"{CENTRAL}/{group.replace('.', '/')}/{artifact}/{version}/{artifact}-{version}.pom"


STARTER = """<project>
  <groupId>org.demo.boot</groupId>
  <artifactId>starter-parent</artifactId>
  <version>3.0.0</version>
  <parent>
    <groupId>org.demo.boot</groupId>
    <artifactId>dependencies</artifactId>
    <version>3.0.0</version>
  </parent>
  <build><pluginManagement><plugins><plugin>
    <groupId>org.demo.boot</groupId><artifactId>demo-plugin</artifactId><version>3.0.0</version>
  </plugin></plugins></pluginManagement></build>
</project>"""

DEPENDENCIES = """<project>
  <groupId>org.demo.boot</groupId>
  <artifactId>dependencies</artifactId>
  <version>3.0.0</version>
  <properties>
    <json-bom.version>2.15.3</json-bom.version>
    <web.version>${project.version}</web.version>
  </properties>
  <dependencyManagement><dependencies>
    <dependency><groupId>org.demo.boot</groupId><artifactId>web</artifactId>
      <version>${web.version}</version></dependency>
    <dependency><groupId>org.demo.json</groupId><artifactId>json-bom</artifactId>
      <version>${json-bom.version}</version><type>pom</type><scope>import</scope></dependency>
    <dependency><groupId>org.demo.other</groupId><artifactId>other-bom</artifactId>
      <version>1.0</version><type>pom</type><scope>import</scope></dependency>
  </dependencies></dependencyManagement>
</project>"""


def json_bom(version: str) -> str:
    return f"""<project>
  <groupId>org.demo.json</groupId><artifactId>json-bom</artifactId><version>{version}</version>
  <properties><json.version>{version}</json.version></properties>
  <dependencyManagement><dependencies>
    <dependency><groupId>org.demo.json</groupId><artifactId>databind</artifactId>
      <version>${{json.version}}</version></dependency>
  </dependencies></dependencyManagement>
</project>"""


OTHER_BOM = """<project>
  <groupId>org.demo.other</groupId><artifactId>other-bom</artifactId><version>1.0</version>
  <dependencyManagement><dependencies>
    <dependency><groupId>org.demo.json</groupId><artifactId>databind</artifactId>
      <version>9.9.9</version></dependency>
    <dependency><groupId>org.demo.other</groupId><artifactId>tool</artifactId>
      <version>1.0</version></dependency>
  </dependencies></dependencyManagement>
</project>"""


@contextmanager
def central(missing: tuple[str, ...] = ()) -> Iterator[dict[str, respx.Route]]:
    poms = {
        pom_url("org.demo.boot", "starter-parent", "3.0.0"): STARTER,
        pom_url("org.demo.boot", "dependencies", "3.0.0"): DEPENDENCIES,
        pom_url("org.demo.json", "json-bom", "2.15.3"): json_bom("2.15.3"),
        pom_url("org.demo.json", "json-bom", "2.17.0"): json_bom("2.17.0"),
        pom_url("org.demo.other", "other-bom", "1.0"): OTHER_BOM,
    }
    extra: dict[str, respx.Route] = {}

    def add(router: respx.MockRouter) -> None:
        for url, text in poms.items():
            if not any(name in url for name in missing):
                extra[url] = router.get(url).respond(200, text=text)

    with recorded_responses(add) as routes:
        yield {**routes, **extra}


def project_pom(dependencies: str, properties: str = "") -> str:
    return f"""<project>
  <parent>
    <groupId>org.demo.boot</groupId><artifactId>starter-parent</artifactId><version>3.0.0</version>
    <relativePath/>
  </parent>
  <groupId>com.example</groupId><artifactId>app</artifactId><version>1.0.0</version>
  <properties>{properties}</properties>
  <dependencies>{dependencies}</dependencies>
  <build><plugins><plugin>
    <groupId>org.demo.boot</groupId><artifactId>demo-plugin</artifactId>
  </plugin></plugins></build>
</project>"""


DEPS = """
    <dependency><groupId>org.demo.boot</groupId><artifactId>web</artifactId></dependency>
    <dependency><groupId>org.demo.json</groupId><artifactId>databind</artifactId></dependency>
    <dependency><groupId>org.demo.other</groupId><artifactId>tool</artifactId></dependency>
"""


async def no_sleep(_: float) -> None:
    pass


def analyze(root: Path) -> Report:
    async def main() -> Report:
        async with HttpClient(sleep=no_sleep) as http:
            return await engine.analyze(LocalSource(root), http=http, cache=Cache.disabled())

    return asyncio.run(main())


def dependencies(report: Report) -> dict[str, Dependency]:
    (project,) = report.projects
    return {d.name: d for d in project.dependencies}


def test_inherited_then_imported(make_tree: MakeTree) -> None:
    root = make_tree({"pom.xml": project_pom(DEPS)})
    with central():
        found = dependencies(analyze(root))
    web = found["org.demo.boot:web"]
    # ${project.version} est celle du projet qui hérite, comme dans Maven.
    assert (web.installed, web.unverifiable_reason) == ("1.0.0", None)
    assert web.manual == (
        "version gérée par le parent org.demo.boot:starter-parent:3.0.0 : la changer avec lui, "
        "ou écrire la <version> voulue"
    )
    # Le premier BOM importé qui le gère l'emporte (json-bom, pas other-bom).
    assert found["org.demo.json:databind"].installed == "2.15.3"
    assert found["org.demo.other:tool"].installed == "1.0"
    plugin = found["org.demo.boot:demo-plugin"]
    assert plugin.installed == "3.0.0"  # <pluginManagement> du parent


def test_a_property_of_the_project_changes_the_version_of_its_parent(
    make_tree: MakeTree,
) -> None:
    """La façon documentée de Spring Boot : <jackson-bom.version> dans le projet."""
    root = make_tree({"pom.xml": project_pom(DEPS, "<json-bom.version>2.17.0</json-bom.version>")})
    with central() as routes:
        found = dependencies(analyze(root))
    assert found["org.demo.json:databind"].installed == "2.17.0"
    assert routes[pom_url("org.demo.json", "json-bom", "2.15.3")].call_count == 0


def test_a_missing_pom_says_why(make_tree: MakeTree) -> None:
    root = make_tree({"pom.xml": project_pom(DEPS)})
    with central(missing=("json-bom",)):
        found = dependencies(analyze(root))
    databind = found["org.demo.json:databind"]
    # json-bom manque : other-bom, importé ensuite, le gère aussi.
    assert databind.installed == "9.9.9"
    assert found["org.demo.boot:web"].installed == "1.0.0"


def test_an_unreadable_parent_keeps_the_dependency_unverifiable(make_tree: MakeTree) -> None:
    root = make_tree({"pom.xml": project_pom(DEPS)})
    with central(missing=("dependencies",)):
        found = dependencies(analyze(root))
    web = found["org.demo.boot:web"]
    assert web.installed is None
    assert web.unverifiable_reason == (
        "version gérée par le parent org.demo.boot:starter-parent (hors du dépôt) : le pom de "
        "org.demo.boot:dependencies:3.0.0 est introuvable"
    )
