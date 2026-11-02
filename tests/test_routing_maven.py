"""Les dépôts Maven déclarés (E33) : ``<repositories>`` des ``pom.xml`` (et de leurs parents),
``settings.xml`` (miroirs, serveurs, profils), ``repositories { }`` de Gradle (``content``,
``exclusiveContent``) ; de bout en bout par le moteur, avec un dépôt simulé."""

import asyncio
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
import respx
from conftest import UserFiles, recorded_responses

from forceupdate import engine
from forceupdate.models import FindingKind, Report
from forceupdate.net import Cache, HttpClient
from forceupdate.routing.maven import Repository, _mirror_of
from forceupdate.sources.local import LocalSource

MakeTree = Callable[..., Path]
NEXUS = "https://nexus.corp.example/repository/maven-releases"
MIRROR = "https://nexus.corp.example/repository/maven-public"

METADATA = """<?xml version="1.0" encoding="UTF-8"?>
<metadata><groupId>com.acme</groupId><artifactId>billing</artifactId>
<versioning><versions><version>1.0.0</version><version>1.3.0</version></versions></versioning>
</metadata>
"""


def pom(repositories: str = "", parent: str = "") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  {parent}
  <groupId>com.acme</groupId>
  <artifactId>app</artifactId>
  <version>1.0.0</version>
  <properties><nexus.url>https://nexus.corp.example</nexus.url></properties>
  {repositories}
  <dependencies>
    <dependency><groupId>com.acme</groupId><artifactId>billing</artifactId>
      <version>1.0.0</version></dependency>
    <dependency><groupId>junit</groupId><artifactId>junit</artifactId>
      <version>4.12</version></dependency>
  </dependencies>
</project>
"""


REPOSITORIES = """<repositories>
    <repository><id>corp</id><url>${nexus.url}/repository/maven-releases/</url></repository>
  </repositories>"""


async def no_sleep(_: float) -> None:
    pass


@contextmanager
def nexus(status: int = 200) -> Iterator[dict[str, respx.Route]]:
    extra: dict[str, respx.Route] = {}

    def add(router: respx.MockRouter) -> None:
        for base in (NEXUS, MIRROR):
            name = "releases" if base == NEXUS else "mirror"
            extra[name] = router.get(f"{base}/com/acme/billing/maven-metadata.xml").respond(
                status, text=METADATA
            )
            extra[f"{name}-other"] = router.get(url__regex=rf"^{base}/").respond(404)
        extra["central-billing"] = router.get(
            "https://repo1.maven.org/maven2/com/acme/billing/maven-metadata.xml"
        ).respond(200, text=METADATA.replace("1.3.0", "9.9.9"))

    with recorded_responses(add) as routes:
        yield {**routes, **extra}


def metadata_calls(route: respx.Route) -> int:
    """Les requêtes de ``maven-metadata.xml`` d'une route, sans celles du ``pom`` de la dernière
    version (sa relocation, E34)."""
    return sum(1 for call in route.calls if not call.request.url.path.endswith(".pom"))


def analyze(root: Path) -> Report:
    async def main() -> Report:
        async with HttpClient(sleep=no_sleep) as http:
            return await engine.analyze(LocalSource(root), http=http, cache=Cache.disabled())

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


def test_pom_repositories_come_before_central(make_tree: MakeTree) -> None:
    root = make_tree({"pom.xml": pom(REPOSITORIES)})
    with nexus() as routes:
        report = analyze(root)
    assert routes["releases"].call_count == 1
    assert routes["central-billing"].call_count == 0
    # junit : pas sur Nexus, puis Central ; et le pom de la dernière version de billing, pour sa
    # relocation (E34), demandé au même dépôt.
    assert routes["releases-other"].call_count == 2
    asked = [call.request.url.path for call in routes["releases-other"].calls]
    assert any(path.endswith(".pom") for path in asked)
    assert routes["maven:junit:junit"].call_count == 1
    assert "com.acme:billing" in osv_names(routes)  # pas privé par son nom
    ((kind, message),) = findings(report, "com.acme:billing")
    assert kind is FindingKind.OUTDATED
    assert "1.3.0" in message


def test_a_parent_in_the_repository_declares_the_repository(make_tree: MakeTree) -> None:
    parent_pom = pom(REPOSITORIES).replace(
        "<artifactId>app</artifactId>", "<artifactId>parent</artifactId>"
    )
    child = pom(
        parent="<parent><groupId>com.acme</groupId><artifactId>parent</artifactId>"
        "<version>1.0.0</version></parent>"
    )
    root = make_tree({"pom.xml": parent_pom, "app/pom.xml": child})
    with nexus() as routes:
        analyze(root)
    assert routes["releases"].call_count == 1
    assert routes["central-billing"].call_count == 0


def test_a_mirror_with_its_server_credentials(make_tree: MakeTree, user_files: UserFiles) -> None:
    root = make_tree({"pom.xml": pom(REPOSITORIES)})
    user_files.env["NEXUS_PASSWORD"] = "pw"
    user_files.write(
        ".m2/settings.xml",
        f"""<settings>
  <servers>
    <server><id>corp-mirror</id><username>jo</username>
      <password>${{env.NEXUS_PASSWORD}}</password></server>
    <server><id>corp</id><username>jo</username><password>pw</password></server>
  </servers>
  <mirrors>
    <mirror><id>corp-mirror</id><url>{MIRROR}</url><mirrorOf>*</mirrorOf></mirror>
  </mirrors>
</settings>
""",
    )
    with nexus() as routes:
        report = analyze(root)
    assert routes["mirror"].calls.last.request.headers["authorization"] == "Basic am86cHc="
    assert routes["releases"].call_count == 0  # le miroir remplace tout
    assert routes["maven:junit:junit"].call_count == 0
    assert metadata_calls(routes["mirror-other"]) == 1
    (project,) = report.projects
    assert not any("« corp »" in n.message for n in project.notices)


def test_credentials_written_in_a_mirror_address(
    make_tree: MakeTree, user_files: UserFiles
) -> None:
    root = make_tree({"pom.xml": pom()})
    address = MIRROR.replace("https://", "https://jo:pw@")
    user_files.write(
        ".m2/settings.xml",
        f"<settings><mirrors><mirror><id>m</id><url>{address}</url><mirrorOf>*</mirrorOf>"
        "</mirror></mirrors></settings>",
    )
    with nexus() as routes:
        analyze(root)
    request = routes["mirror"].calls.last.request
    assert request.headers["authorization"] == "Basic am86cHc="
    assert "jo" not in str(request.url)


def test_server_credentials_never_follow_a_pom_address(
    make_tree: MakeTree, user_files: UserFiles
) -> None:
    """Le ``pom.xml`` donne l'id « corp » à une adresse : les identifiants du serveur « corp » de
    la personne n'y partent pas."""
    root = make_tree({"pom.xml": pom(REPOSITORIES)})
    user_files.write(
        ".m2/settings.xml",
        "<settings><servers><server><id>corp</id><username>jo</username>"
        "<password>pw</password></server></servers></settings>",
    )
    with nexus() as routes:
        report = analyze(root)
    assert "authorization" not in routes["releases"].calls.last.request.headers
    (project,) = report.projects
    assert any("serveur « corp » ne partent pas" in n.message for n in project.notices)


def test_an_encrypted_password_is_not_read(make_tree: MakeTree, user_files: UserFiles) -> None:
    root = make_tree({"pom.xml": pom()})
    user_files.write(
        ".m2/settings.xml",
        "<settings><servers><server><id>corp</id><username>jo</username>"
        "<password>{COQLCE6DU6GtcS5P=}</password></server></servers></settings>",
    )
    with nexus():
        report = analyze(root)
    (project,) = report.projects
    assert any("chiffré" in n.message for n in project.notices)


def test_a_profile_repository_of_the_settings(make_tree: MakeTree, user_files: UserFiles) -> None:
    root = make_tree({"pom.xml": pom()})
    user_files.write(
        ".m2/settings.xml",
        f"""<settings>
  <servers><server><id>corp</id><username>jo</username><password>pw</password></server></servers>
  <profiles><profile><id>corp</id>
    <repositories><repository><id>corp</id><url>{NEXUS}</url></repository></repositories>
  </profile></profiles>
  <activeProfiles><activeProfile>corp</activeProfile></activeProfiles>
</settings>
""",
    )
    with nexus() as routes:
        analyze(root)
    assert routes["releases"].calls.last.request.headers["authorization"] == "Basic am86cHc="


def test_a_refusing_repository_never_falls_back_to_central(make_tree: MakeTree) -> None:
    root = make_tree({"pom.xml": pom(REPOSITORIES)})
    with nexus(status=401) as routes:
        report = analyze(root)
    assert routes["central-billing"].call_count == 0
    ((kind, message),) = findings(report, "com.acme:billing")
    assert kind is FindingKind.UNVERIFIABLE
    assert message.startswith("Registre privé : non vérifié : nexus.corp.example refuse l'accès")


@pytest.mark.parametrize(
    ("pattern", "repository", "expected"),
    [
        ("*", "central", True),
        ("central", "central", True),
        ("other", "central", False),
        ("*,!central", "central", False),
        ("external:*", "central", True),
        ("repo1,central", "central", True),
    ],
)
def test_mirror_of(pattern: str, repository: str, expected: bool) -> None:
    repo = Repository(id=repository, url="https://repo.maven.apache.org/maven2", file="")
    assert _mirror_of(pattern, repo) is expected


def test_external_does_not_take_the_machine_itself() -> None:
    local = Repository(id="local", url="http://localhost:8081/repo", file="")
    assert not _mirror_of("external:*", local)


GRADLE = f"""\
plugins {{ id 'java' }}

repositories {{
    mavenCentral()
    maven {{
        url = uri("{NEXUS}")
        credentials {{ username = findProperty("nexusUser") }}
    }}
}}

dependencies {{
    implementation 'com.acme:billing:1.0.0'
    testImplementation 'junit:junit:4.12'
}}
"""


def test_gradle_repositories(make_tree: MakeTree) -> None:
    root = make_tree({"build.gradle": GRADLE})
    with nexus() as routes:
        report = analyze(root)
    assert routes["releases"].call_count == 1
    assert "authorization" not in routes["releases"].calls.last.request.headers
    assert routes["central-billing"].call_count == 0
    assert routes["maven:junit:junit"].call_count == 1
    (project,) = report.projects
    assert any("ne les lit pas" in n.message for n in project.notices)


def test_gradle_exclusive_content_makes_groups_private(make_tree: MakeTree) -> None:
    script = f"""\
repositories {{
    mavenCentral()
    exclusiveContent {{
        forRepository {{ maven {{ url "{NEXUS}" }} }}
        filter {{ includeGroup("com.acme") }}
    }}
}}
dependencies {{
    implementation("com.acme:billing:1.0.0")
    testImplementation("junit:junit:4.12")
}}
"""
    root = make_tree({"build.gradle.kts": script})
    with nexus() as routes:
        analyze(root)
    assert routes["releases"].call_count == 1
    assert metadata_calls(routes["releases-other"]) == 0  # junit ne lui est pas demandé
    assert "com.acme:billing" not in osv_names(routes)
    assert "junit:junit" in osv_names(routes)


def test_gradle_settings_repositories(make_tree: MakeTree) -> None:
    settings = f"""\
dependencyResolutionManagement {{
    repositories {{
        maven("{NEXUS}")
    }}
}}
"""
    build = "dependencies {\n    implementation 'com.acme:billing:1.0.0'\n}\n"
    root = make_tree({"settings.gradle.kts": settings, "app/build.gradle": build})
    with nexus() as routes:
        report = analyze(root)
    assert routes["releases"].call_count == 1
    assert routes["central-billing"].call_count == 0  # pas de mavenCentral()
    assert findings(report, "com.acme:billing")[0][0] is FindingKind.OUTDATED
