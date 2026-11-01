"""Le parseur Maven : ``pom.xml``, et le lecteur XML qui donne la position des versions."""

import pytest

from forceupdate.models import Dependency, Location, Notice, Scope
from forceupdate.parsers.base import REASON_LOCAL, ParseError
from forceupdate.parsers.maven import (
    REASON_MODULE,
    REASON_NO_VERSION,
    REASON_PLUGIN_DEFAULT,
    parse_pom_project,
    parse_pom_xml,
    read_pom,
)
from forceupdate.parsers.xml_spans import parse


def rows(found: list[Dependency]) -> list[tuple[str, str, str | None, str, str | None]]:
    return [(d.name, d.constraint, d.installed, d.file, d.unverifiable_reason) for d in found]


def project(files: dict[str, str], manifest: str = "pom.xml") -> tuple[list[Dependency], list]:
    notices: list[Notice] = []
    return parse_pom_project(manifest, files.get, notices), notices


# ---------------------------------------------------------------------------
# Le lecteur XML
# ---------------------------------------------------------------------------


class TestXmlSpans:
    def test_text_location(self) -> None:
        text = (
            '<?xml version="1.0"?>\n<a xmlns="x">\n  <b> 1.2.3 </b>\n'
            '  <c x="a>b">é<d>4</d></c>\n</a>\n'
        )
        root = parse(text)
        b = root.find("b")
        assert b is not None and b.text == "1.2.3"
        assert b.location == Location(line=3, column=6, end_column=11)
        d = root.find("c").find("d")  # type: ignore[union-attr]
        assert d is not None and d.location is not None
        assert d.location.extract(text) == "4"  # après un « é » et un attribut qui contient « > »
        assert root.find("c").location is None  # type: ignore[union-attr]

    @pytest.mark.parametrize(
        "inner", ["<![CDATA[1.0]]>", "1&#46;0", "1.0<!-- x -->", "", "\n1.0\n2.0\n"]
    )
    def test_no_location_when_not_written_as_is(self, inner: str) -> None:
        root = parse(f"<a><version>{inner}</version></a>")
        version = root.find("version")
        assert version is not None and version.location is None

    def test_a_prefixed_name_loses_its_prefix(self) -> None:
        root = parse('<pom:project xmlns:pom="x"><pom:version>1</pom:version></pom:project>')
        assert root.tag == "project" and root.child_text("version") == "1"

    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ('<!DOCTYPE a [<!ENTITY x "y">]><a>&x;</a>', "DTD"),
            ("<a><b></a>", "XML invalide"),
            ("", "XML invalide"),
            ("pas du XML", "XML invalide"),
        ],
    )
    def test_refused(self, text: str, message: str) -> None:
        with pytest.raises(ParseError, match=message):
            parse(text)


# ---------------------------------------------------------------------------
# Un pom.xml seul
# ---------------------------------------------------------------------------


class TestParsePomXml:
    def test_dependency_block(self) -> None:
        """Repris de ``reference/argos_sca_parsers_tests.py`` : une version écrite, une propriété
        (ici introuvable : non vérifiable, au lieu de « non épinglée »)."""
        content = """\
<project>
  <dependencies>
    <dependency>
      <groupId>org.springframework</groupId>
      <artifactId>spring-core</artifactId>
      <version>6.1.0</version>
    </dependency>
    <dependency>
      <groupId>junit</groupId>
      <artifactId>junit</artifactId>
      <version>${junit.version}</version>
    </dependency>
  </dependencies>
</project>
"""
        found = parse_pom_xml("pom.xml", content)
        assert len(found) == 2
        by_name = {d.name: d for d in found}
        spring = by_name["org.springframework:spring-core"]
        assert spring.verifiable and spring.constraint == "6.1.0" and spring.installed == "6.1.0"
        assert spring.location == Location(line=6, column=15, end_column=20)
        junit = by_name["junit:junit"]
        assert junit.unverifiable_reason == "propriété ${junit.version} introuvable"
        assert junit.constraint == "${junit.version}" and junit.location is None

    def test_any_tag_order_and_properties(self) -> None:
        content = """\
<project>
  <properties>
    <guava.version>31.0.1-jre</guava.version>
    <alias>${guava.version}</alias>
    <major>2</major>
  </properties>
  <dependencies>
    <dependency>
      <version>${alias}</version>
      <artifactId>guava</artifactId>
      <groupId>com.google.guava</groupId>
    </dependency>
    <dependency>
      <groupId>org.x</groupId>
      <artifactId>y</artifactId>
      <version>${major}.0.1</version>
    </dependency>
  </dependencies>
</project>
"""
        guava, composite = parse_pom_xml("pom.xml", content)
        assert guava.name == "com.google.guava:guava"
        assert guava.constraint == "31.0.1-jre"
        assert guava.location is not None and guava.location.line == 3  # la propriété finale
        assert (composite.constraint, composite.location) == ("2.0.1", None)  # à la main

    def test_scopes_plugins_and_profiles(self) -> None:
        content = """\
<project>
  <dependencies>
    <dependency><groupId>a</groupId><artifactId>test</artifactId><version>1</version>
      <scope>test</scope></dependency>
    <dependency><groupId>a</groupId><artifactId>provided</artifactId><version>1</version>
      <scope>provided</scope></dependency>
    <dependency><groupId>a</groupId><artifactId>optional</artifactId><version>1</version>
      <optional>true</optional></dependency>
    <dependency><groupId>a</groupId><artifactId>system</artifactId><version>1</version>
      <scope>system</scope><systemPath>/x.jar</systemPath></dependency>
  </dependencies>
  <build>
    <plugins>
      <plugin><artifactId>maven-jar-plugin</artifactId><version>3.2.0</version>
        <dependencies>
          <dependency><groupId>a</groupId><artifactId>for-plugin</artifactId><version>2</version></dependency>
        </dependencies>
      </plugin>
      <plugin><artifactId>maven-surefire-plugin</artifactId></plugin>
    </plugins>
    <extensions><extension><groupId>a</groupId><artifactId>ext</artifactId><version>3</version></extension></extensions>
  </build>
  <profiles>
    <profile>
      <id>p</id>
      <properties><v>4</v></properties>
      <dependencies><dependency><groupId>a</groupId><artifactId>in-profile</artifactId><version>${v}</version></dependency></dependencies>
    </profile>
  </profiles>
</project>
"""
        found = parse_pom_xml("pom.xml", content)
        assert [(d.name, d.scope, d.unverifiable_reason) for d in found] == [
            ("a:test", Scope.DEV, None),
            ("a:provided", Scope.RUNTIME, None),
            ("a:optional", Scope.OPTIONAL, None),
            ("a:system", Scope.RUNTIME, REASON_LOCAL),
            ("org.apache.maven.plugins:maven-jar-plugin", Scope.BUILD, None),
            ("a:for-plugin", Scope.BUILD, None),
            ("org.apache.maven.plugins:maven-surefire-plugin", Scope.BUILD, REASON_PLUGIN_DEFAULT),
            ("a:ext", Scope.BUILD, None),
            ("a:in-profile", Scope.RUNTIME, None),
        ]
        assert found[-1].constraint == "4"

    def test_managed_in_the_same_file_is_one_declaration(self) -> None:
        """Une dépendance sans version que gère le même ``pom.xml`` ne fait qu'une déclaration :
        celle de ``dependencyManagement``, avec le scope écrit par la dépendance, sinon le sien."""
        content = """\
<project>
  <dependencyManagement>
    <dependencies>
      <dependency><groupId>a</groupId><artifactId>b</artifactId><version>1.0</version></dependency>
      <dependency><groupId>a</groupId><artifactId>c</artifactId><version>2.0</version>
        <scope>test</scope></dependency>
      <dependency><groupId>a</groupId><artifactId>unused</artifactId><version>3.0</version></dependency>
      <dependency><groupId>a</groupId><artifactId>no-version</artifactId></dependency>
    </dependencies>
  </dependencyManagement>
  <dependencies>
    <dependency><groupId>a</groupId><artifactId>b</artifactId><scope>test</scope></dependency>
    <dependency><groupId>a</groupId><artifactId>c</artifactId></dependency>
    <dependency><groupId>a</groupId><artifactId>missing</artifactId></dependency>
  </dependencies>
</project>
"""
        found = parse_pom_xml("pom.xml", content)
        assert [(d.name, d.constraint, d.scope, d.unverifiable_reason) for d in found] == [
            ("a:b", "1.0", Scope.DEV, None),
            ("a:c", "2.0", Scope.DEV, None),
            ("a:unused", "3.0", Scope.RUNTIME, None),
            ("a:missing", "", Scope.RUNTIME, REASON_NO_VERSION),
        ]

    def test_project_version_is_a_module(self) -> None:
        content = """\
<project>
  <groupId>g</groupId><artifactId>me</artifactId><version>1.0</version>
  <dependencies>
    <dependency><groupId>${project.groupId}</groupId><artifactId>other</artifactId>
      <version>${project.version}</version></dependency>
  </dependencies>
</project>
"""
        (other,) = parse_pom_xml("pom.xml", content)
        assert other.name == "g:other" and other.unverifiable_reason == REASON_MODULE

    def test_a_remote_parent_is_a_dependency(self) -> None:
        content = """\
<project>
  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>2.7.0</version>
    <relativePath/>
  </parent>
  <artifactId>demo</artifactId>
  <dependencies>
    <dependency><groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId></dependency>
    <dependency><groupId>a</groupId><artifactId>b</artifactId><version>${jackson.version}</version>
    </dependency>
  </dependencies>
</project>
"""
        parent, web, b = parse_pom_xml("pom.xml", content)
        assert (parent.name, parent.constraint, parent.location) == (
            "org.springframework.boot:spring-boot-starter-parent",
            "2.7.0",
            Location(line=5, column=13, end_column=18),
        )
        assert web.unverifiable_reason == (
            "version gérée par le parent org.springframework.boot:spring-boot-starter-parent "
            "(hors du dépôt)"
        )
        assert b.unverifiable_reason == (
            "propriété ${jackson.version} définie hors du dépôt "
            "(parent org.springframework.boot:spring-boot-starter-parent ?)"
        )

    def test_invalid(self) -> None:
        with pytest.raises(ParseError, match="XML invalide"):
            parse_pom_xml("pom.xml", "<project><dependencies></project>")
        with pytest.raises(ParseError, match="<project>"):
            parse_pom_xml("pom.xml", "<settings/>")

    def test_read_pom(self) -> None:
        pom = read_pom(
            "pom.xml",
            "<project><parent><groupId>g</groupId><artifactId>p</artifactId><version>2</version>"
            "</parent><artifactId>a</artifactId><modules><module>x</module><module>y</module>"
            "</modules></project>",
        )
        assert (pom.coordinates, pom.version, pom.modules) == ("g:a", "2", ("x", "y"))


# ---------------------------------------------------------------------------
# Un projet : ses parents du dépôt, son build
# ---------------------------------------------------------------------------

ROOT = """\
<project>
  <parent>
    <groupId>org.apache</groupId><artifactId>apache</artifactId><version>23</version>
    <relativePath/>
  </parent>
  <groupId>g</groupId>
  <artifactId>parent</artifactId>
  <version>1.0-SNAPSHOT</version>
  <modules><module>lib</module><module>app</module></modules>
  <properties>
    <log4j.version>2.14.1</log4j.version>
    <guava.version>30.1-jre</guava.version>
  </properties>
  <dependencyManagement>
    <dependencies>
      <dependency><groupId>org.apache.logging.log4j</groupId><artifactId>log4j-core</artifactId>
        <version>${log4j.version}</version></dependency>
      <dependency><groupId>junit</groupId><artifactId>junit</artifactId><version>4.12</version>
        <scope>test</scope></dependency>
      <dependency><groupId>com.fasterxml.jackson</groupId><artifactId>jackson-bom</artifactId>
        <version>2.13.0</version><type>pom</type><scope>import</scope></dependency>
    </dependencies>
  </dependencyManagement>
  <build><pluginManagement><plugins>
    <plugin><artifactId>maven-compiler-plugin</artifactId><version>3.8.1</version></plugin>
  </plugins></pluginManagement></build>
</project>
"""

LIB = """\
<project>
  <parent><groupId>g</groupId><artifactId>parent</artifactId><version>1.0-SNAPSHOT</version></parent>
  <artifactId>lib</artifactId>
</project>
"""

APP = """\
<project>
  <parent><groupId>g</groupId><artifactId>parent</artifactId><version>1.0-SNAPSHOT</version></parent>
  <artifactId>app</artifactId>
  <properties><guava.version>31.0.1-jre</guava.version></properties>
  <dependencies>
    <dependency><groupId>org.apache.logging.log4j</groupId><artifactId>log4j-core</artifactId></dependency>
    <dependency><groupId>junit</groupId><artifactId>junit</artifactId></dependency>
    <dependency><groupId>com.fasterxml.jackson.core</groupId><artifactId>jackson-databind</artifactId></dependency>
    <dependency><groupId>com.google.guava</groupId><artifactId>guava</artifactId>
      <version>${guava.version}</version></dependency>
    <dependency><groupId>g</groupId><artifactId>lib</artifactId><version>1.0-SNAPSHOT</version></dependency>
    <dependency><groupId>a</groupId><artifactId>b</artifactId><version>${spring.version}</version></dependency>
  </dependencies>
  <build><plugins>
    <plugin><artifactId>maven-compiler-plugin</artifactId></plugin>
    <plugin><artifactId>maven-surefire-plugin</artifactId></plugin>
  </plugins></build>
</project>
"""

FILES = {"pom.xml": ROOT, "lib/pom.xml": LIB, "app/pom.xml": APP}


class TestProject:
    def test_the_root(self) -> None:
        found, notices = project(FILES)
        assert rows(found) == [
            ("org.apache:apache", "23", "23", "pom.xml", None),
            ("org.apache.logging.log4j:log4j-core", "2.14.1", "2.14.1", "pom.xml", None),
            ("junit:junit", "4.12", "4.12", "pom.xml", None),
            ("com.fasterxml.jackson:jackson-bom", "2.13.0", "2.13.0", "pom.xml", None),
            ("org.apache.maven.plugins:maven-compiler-plugin", "3.8.1", "3.8.1", "pom.xml", None),
        ]
        assert notices == []

    def test_a_module_takes_its_versions_from_its_parent(self) -> None:
        found, _ = project(FILES, "app/pom.xml")
        parent = "version gérée par le parent org.apache:apache (hors du dépôt)"
        assert rows(found) == [
            # La version du dependencyManagement du parent, écrite dans le pom.xml racine.
            ("org.apache.logging.log4j:log4j-core", "2.14.1", "2.14.1", "pom.xml", None),
            ("junit:junit", "4.12", "4.12", "pom.xml", None),
            (
                "com.fasterxml.jackson.core:jackson-databind",
                "",
                None,
                "app/pom.xml",
                "version gérée par un BOM importé (com.fasterxml.jackson:jackson-bom)",
            ),
            # La propriété redéfinie par le module l'emporte.
            ("com.google.guava:guava", "31.0.1-jre", "31.0.1-jre", "app/pom.xml", None),
            ("g:lib", "1.0-SNAPSHOT", None, "app/pom.xml", REASON_MODULE),
            (
                "a:b",
                "${spring.version}",
                None,
                "app/pom.xml",
                "propriété ${spring.version} définie hors du dépôt (parent org.apache:apache ?)",
            ),
            ("org.apache.maven.plugins:maven-compiler-plugin", "3.8.1", "3.8.1", "pom.xml", None),
            ("org.apache.maven.plugins:maven-surefire-plugin", "", None, "app/pom.xml", parent),
        ]
        by_name = {d.name: d for d in found}
        assert by_name["junit:junit"].scope is Scope.DEV  # le scope de la gestion
        root_log4j = next(d for d in project(FILES)[0] if d.name.endswith("log4j-core"))
        assert by_name["org.apache.logging.log4j:log4j-core"].location == root_log4j.location

    def test_a_parent_outside_the_repository(self) -> None:
        """Un ``<relativePath>`` qui mène à un autre ``pom.xml`` : le parent est cherché hors du
        dépôt, et une remarque le dit."""
        files = {
            "pom.xml": "<project><groupId>x</groupId><artifactId>other</artifactId></project>",
            "app/pom.xml": (
                "<project><parent><groupId>g</groupId><artifactId>parent</artifactId>"
                "<version>1</version><relativePath>../pom.xml</relativePath></parent>"
                "<artifactId>app</artifactId></project>"
            ),
        }
        found, notices = project(files, "app/pom.xml")
        assert rows(found) == [("g:parent", "1", "1", "app/pom.xml", None)]
        assert notices == [
            Notice(
                file="app/pom.xml",
                message=(
                    "<relativePath> mène à pom.xml, qui n'est pas le parent g:parent : parent "
                    "cherché hors du dépôt."
                ),
            )
        ]

    def test_unreadable(self) -> None:
        found, notices = project({"pom.xml": "<project>"})
        assert found == [] and notices[0].message.startswith("XML invalide")
        found, notices = project({}, "pom.xml")
        assert notices == [
            Notice(file="pom.xml", message="introuvable, illisible ou trop gros : pas lu.")
        ]
