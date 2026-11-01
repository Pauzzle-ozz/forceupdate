"""Les manifestes Java : ``pom.xml``, ``build.gradle``, ``build.gradle.kts``,
``gradle/libs.versions.toml`` et ``gradle.properties``.

Une version Maven ou Gradle se réécrit là où elle est écrite (``parsers.maven``,
``parsers.gradle``) : le texte de ``<version>``, la valeur d'une propriété (``<properties>``,
``gradle.properties``), d'une variable d'un script, d'une entrée de ``[versions]`` du catalogue.
Pour qu'une telle réécriture se vérifie, chaque fichier relu redonne, en plus de ses dépendances,
ces valeurs-là, chacune avec son emplacement : une propriété réécrite doit y avoir la nouvelle
version, et les dépendances qui la citent aussi.

Ni Maven ni Gradle ne sont lancés : il n'y a pas de lockfile à régénérer en V1.
"""

from forceupdate.parsers.gradle import (
    catalog_dependencies,
    read_catalog,
    read_properties,
    read_script,
    script_dependencies,
)
from forceupdate.parsers.maven import parse_pom_xml, read_pom
from forceupdate.update.writers.base import Declaration, Reader, dependencies


def read_pom_xml(path: str, content: str) -> list[Declaration]:
    """Les dépendances d'un ``pom.xml`` lu seul, puis ses propriétés."""
    pom = read_pom(path, content)
    found = dependencies(parse_pom_xml(path, content))
    for name, item in pom.properties.items():
        found.append(Declaration(identity=("property", None, name), constraint=item.value,
                                 location=item.location))  # fmt: skip
    for profile, properties in pom.profile_properties.items():
        for name, item in properties.items():
            found.append(Declaration(identity=("property", profile, name), constraint=item.value,
                                     location=item.location))  # fmt: skip
    return found


def read_build_script(path: str, content: str) -> list[Declaration]:
    """Les dépendances d'un script Gradle (ses variables résolues dans le script seul), puis ses
    variables."""
    script = read_script(path, content)
    found = dependencies(script_dependencies(script, script.variables))
    for name, variable in script.variables.items():
        found.append(Declaration(identity=("variable", name), constraint=variable.value or "",
                                 location=variable.location))  # fmt: skip
    return found


def read_version_catalog(path: str, content: str) -> list[Declaration]:
    """Les entrées d'un catalogue de versions, puis ses ``[versions]``."""
    catalog = read_catalog(path, content)
    found = dependencies(catalog_dependencies(catalog, {}))
    for name, (value, location) in catalog.versions.items():
        found.append(Declaration(identity=("version", name), constraint=value, location=location))
    return found


def read_gradle_properties(path: str, content: str) -> list[Declaration]:
    """Les propriétés d'un ``gradle.properties``."""
    return [
        Declaration(
            identity=("property", name), constraint=item.value or "", location=item.location
        )
        for name, item in read_properties(path, content).items()
    ]


READERS: dict[str, Reader] = {
    "pom.xml": read_pom_xml,
    "build.gradle": read_build_script,
    "build.gradle.kts": read_build_script,
    "gradle/libs.versions.toml": read_version_catalog,
}
"""Le parseur qui relit chaque manifeste, par motif reconnu (``detect.manifests``) ;
``gradle.properties`` n'en est pas un : ``update.writers`` le reconnaît par son nom."""
