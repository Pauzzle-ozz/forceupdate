"""Les parseurs PHP : ``composer.json``, ``composer.lock``, et le lien entre les deux.

``TestParseComposerJson`` est repris de ``reference/argos_sca_parsers_tests.py`` ; le reste couvre
ce que la reprise a corrigé ou ajouté (contraintes telles qu'écrites, emplacements, noms en
minuscules, branches, dépôts ``path`` et autres, ``replace``, ``conflict``, graphe du lockfile).
"""

import json

import pytest

from forceupdate import parsers
from forceupdate.detect.manifests import find_projects
from forceupdate.models import Location, Notice, Project, Scope
from forceupdate.parsers.base import REASON_LOCAL, ParseError
from forceupdate.parsers.php import (
    REASON_BRANCH,
    REASON_OTHER_REPOSITORY,
    REASON_PROVIDED,
    is_platform,
    parse_composer_json,
    parse_composer_lock,
)

RUNTIME, DEV = Scope.RUNTIME, Scope.DEV
PACKAGIST = "https://packagist.org/downloads/"


def parse(files: dict[str, str], path: str = ".") -> Project:
    """Le projet ``path`` de ``files``, avec ses dépendances lues."""
    projects, _ = find_projects(files, include_tests=True)
    project = next(p for p in projects if p.path == path)
    parsers.parse_project(project, files.get)
    return project


def manifest(**sections: object) -> str:
    return json.dumps(sections, indent=4)


def package(
    name: str, version: str, requires: dict[str, str] | None = None, **extra: object
) -> dict[str, object]:
    """Une entrée de ``composer.lock`` venue de Packagist (sauf ``notification-url`` donné)."""
    entry: dict[str, object] = {"name": name, "version": version}
    if requires:
        entry["require"] = requires
    entry.setdefault("notification-url", PACKAGIST)
    entry.update(extra)
    return entry


def lockfile(packages: list[dict[str, object]], dev: list[dict[str, object]] | None = None) -> str:
    return json.dumps({"content-hash": "x", "packages": packages, "packages-dev": dev or []})


def directs(project: Project) -> list[tuple[str, str, str | None, Scope, str | None]]:
    return [
        (d.name, d.constraint, d.installed, d.scope, d.unverifiable_reason)
        for d in project.dependencies
        if d.direct
    ]


def transitives(project: Project) -> list[tuple[str, str | None, Scope, str | None]]:
    return [
        (d.name, d.installed, d.scope, d.unverifiable_reason)
        for d in project.dependencies
        if not d.direct
    ]


# ---------------------------------------------------------------------------
# Repris de reference/argos_sca_parsers_tests.py
# ---------------------------------------------------------------------------


class TestParseComposerJson:
    def test_skips_php_and_ext(self) -> None:
        content = json.dumps(
            {
                "require": {
                    "php": ">=8.1",
                    "ext-json": "*",
                    "symfony/http-kernel": "6.4.0",
                },
                "require-dev": {"phpunit/phpunit": "10.5.0"},
            }
        )
        names = {d.name for d in parse_composer_json("composer.json", content)}
        assert "symfony/http-kernel" in names
        assert "phpunit/phpunit" in names
        assert "php" not in names
        assert "ext-json" not in names


# ---------------------------------------------------------------------------
# composer.json
# ---------------------------------------------------------------------------


class TestComposerJson:
    def test_constraints_as_written_scopes_and_lowercase_names(self) -> None:
        content = manifest(
            require={
                "Monolog/Monolog": " ^2.3 ",
                "symfony/console": "~5.4",
                "twig/twig": "3.4.*",
                "psr/log": "^1.1 || ^2.0",
                "guzzlehttp/guzzle": "7.4.0",
            },
            **{"require-dev": {"phpunit/phpunit": "^9.5"}},
        )
        found = parse_composer_json("composer.json", content)
        assert [(d.name, d.constraint, d.scope) for d in found] == [
            ("monolog/monolog", "^2.3", RUNTIME),
            ("symfony/console", "~5.4", RUNTIME),
            ("twig/twig", "3.4.*", RUNTIME),
            ("psr/log", "^1.1 || ^2.0", RUNTIME),
            ("guzzlehttp/guzzle", "7.4.0", RUNTIME),
            ("phpunit/phpunit", "^9.5", DEV),
        ]
        assert all(d.verifiable and d.file == "composer.json" for d in found)

    def test_every_location_points_at_its_constraint(self) -> None:
        content = manifest(
            require={"a/b": " ^1.0 ", "c/d": "~2.0@beta", "e/f": ">=1.2 <2.0"},
            **{"require-dev": {"g/h": "dev-main"}},
        )
        found = parse_composer_json("composer.json", content)
        assert [d.location.extract(content) for d in found if d.location] == [
            "^1.0",
            "~2.0@beta",
            ">=1.2 <2.0",
            "dev-main",
        ]
        assert found[0].location == Location(line=3, column=17, end_column=21)

    def test_an_escaped_constraint_has_no_location(self) -> None:
        found = parse_composer_json("composer.json", '{"require": {"a/b": "\\u005e1.0"}}')
        assert [(d.constraint, d.location) for d in found] == [("^1.0", None)]

    @pytest.mark.parametrize(
        "name",
        [
            "php",
            "php-64bit",
            "hhvm",
            "ext-json",
            "ext-pdo_mysql",
            "lib-pcre",
            "composer-plugin-api",
            "composer-runtime-api",
            "composer",
            "PHP",
        ],
    )
    def test_platform_packages_are_set_aside(self, name: str) -> None:
        assert is_platform(name)
        assert parse_composer_json("composer.json", manifest(require={name: "*"})) == []

    def test_not_platform(self) -> None:
        assert not is_platform("phpunit/phpunit")
        assert not is_platform("ext-json/polyfill")

    @pytest.mark.parametrize(
        "constraint",
        [
            "dev-main",
            "dev-master",
            "1.x-dev",
            "2.0.x-dev",
            "dev-main as 1.0.x-dev",
            "dev-main#abc123",
            "dev-feature/foo@dev",
            "master",
        ],
    )
    def test_a_branch_is_not_verifiable(self, constraint: str) -> None:
        (dependency,) = parse_composer_json("composer.json", manifest(require={"a/b": constraint}))
        assert dependency.constraint == constraint
        assert dependency.unverifiable_reason == REASON_BRANCH

    @pytest.mark.parametrize("constraint", ["^1.0 || dev-main", "*@dev", "^1.0@dev", "*", ""])
    def test_not_only_a_branch(self, constraint: str) -> None:
        (dependency,) = parse_composer_json("composer.json", manifest(require={"a/b": constraint}))
        assert dependency.verifiable

    def test_replaced_or_provided_by_the_project(self) -> None:
        content = manifest(
            require={"a/replaced": "^1.0", "b/provided": "^2.0", "c/other": "^3.0"},
            replace={"a/replaced": "*", "symfony/polyfill-php80": "*"},
            provide={"B/Provided": "2.0.0"},
        )
        found = parse_composer_json("composer.json", content)
        assert [(d.name, d.unverifiable_reason) for d in found] == [
            ("a/replaced", REASON_PROVIDED),
            ("b/provided", REASON_PROVIDED),
            ("c/other", None),
        ]

    def test_conflicts_are_excluded_versions(self) -> None:
        content = manifest(
            require={"monolog/monolog": "^2.3", "twig/twig": "^3.0"},
            conflict={"Monolog/Monolog": "2.11.*", "symfony/symfony": "*"},
        )
        found = parse_composer_json("composer.json", content)
        assert [(d.name, d.excluded) for d in found] == [
            ("monolog/monolog", ("2.11.*",)),
            ("twig/twig", ()),
        ]

    def test_an_unreadable_constraint_gives_a_notice(self) -> None:
        project = parse({"composer.json": manifest(require={"a/b": ["^1.0"], "c/d": "^1.0"})})
        assert [d.name for d in project.dependencies] == ["c/d"]
        assert project.notices == [
            Notice(file="composer.json", message="« a/b » : contrainte illisible.")
        ]

    def test_invalid_json(self) -> None:
        with pytest.raises(ParseError, match="JSON invalide"):
            parse_composer_json("composer.json", "{")
        with pytest.raises(ParseError, match="objet"):
            parse_composer_json("composer.json", "[]")

    def test_a_bom_is_ignored(self) -> None:
        found = parse_composer_json("composer.json", "﻿" + manifest(require={"a/b": "^1.0"}))
        assert [d.name for d in found] == ["a/b"]

    @pytest.mark.parametrize(
        ("stability", "prefer_stable", "noticed"),
        [
            ("dev", False, True),
            ("beta", None, True),
            ("dev", True, False),
            ("stable", False, False),
        ],
    )
    def test_minimum_stability(
        self, stability: str, prefer_stable: bool | None, noticed: bool
    ) -> None:
        sections: dict[str, object] = {"require": {"a/b": "^1.0"}, "minimum-stability": stability}
        if prefer_stable is not None:
            sections["prefer-stable"] = prefer_stable
        project = parse({"composer.json": manifest(**sections)})
        messages = [n.message for n in project.notices]
        if noticed:
            assert messages == [
                f"minimum-stability « {stability} » sans prefer-stable : Composer peut choisir "
                "des pré-versions ; forceupdate ne propose que des versions stables."
            ]
        else:
            assert messages == []


# ---------------------------------------------------------------------------
# composer.lock
# ---------------------------------------------------------------------------


class TestComposerLock:
    def test_packages_dev_packages_and_graph(self) -> None:
        content = lockfile(
            [
                package("monolog/monolog", "2.3.5", {"php": ">=7.2", "psr/log": "^1.0.1 || ^2.0"}),
                package("psr/log", "1.1.4", {"php": ">=5.3.0"}),
            ],
            [package("Doctrine/Cache", "1.12.1", {"php": "~7.1 || ^8.0"})],
        )
        lock = parse_composer_lock("composer.lock", content).lockfile
        assert lock.graph
        assert [(p.name, p.version, p.scope, p.dependencies) for p in lock.packages] == [
            ("monolog/monolog", "2.3.5", RUNTIME, (("psr/log", frozenset()),)),
            ("psr/log", "1.1.4", RUNTIME, ()),
            ("doctrine/cache", "1.12.1", DEV, ()),
        ]

    def test_path_packages_and_branches_are_not_verifiable(self) -> None:
        content = lockfile(
            [
                package("acme/tools", "1.0.0", dist={"type": "path", "url": "packages/tools"}),
                package("psr/container", "dev-master"),
                package("foo/bar", "2.x-dev"),
                package("good/one", "v1.0.2"),
            ]
        )
        lock = parse_composer_lock("composer.lock", content).lockfile
        assert [(p.name, p.unverifiable_reason) for p in lock.packages] == [
            ("acme/tools", REASON_LOCAL),
            ("psr/container", REASON_BRANCH),
            ("foo/bar", REASON_BRANCH),
            ("good/one", None),
        ]

    def test_invalid_json(self) -> None:
        with pytest.raises(ParseError):
            parse_composer_lock("composer.lock", "{not json")

    def test_parse_lockfile_knows_it(self) -> None:
        lock = parsers.parse_lockfile("app/composer.lock", lockfile([package("a/b", "1.0.0")]))
        assert [(p.name, p.version) for p in lock.packages] == [("a/b", "1.0.0")]


# ---------------------------------------------------------------------------
# Un projet
# ---------------------------------------------------------------------------


class TestProject:
    def test_installed_versions_and_transitives(self) -> None:
        project = parse(
            {
                "composer.json": manifest(
                    require={"php": ">=8.1", "monolog/monolog": "^2.3"},
                    **{"require-dev": {"phpunit/phpunit": "^9.5"}},
                ),
                "composer.lock": lockfile(
                    [
                        package("monolog/monolog", "2.3.5", {"psr/log": "^1.0.1 || ^2.0"}),
                        package("psr/log", "1.1.4"),
                    ],
                    [
                        package("phpunit/phpunit", "9.5.0", {"sebastian/diff": "^4.0"}),
                        package("sebastian/diff", "4.0.4", {"php": ">=7.3"}),
                    ],
                ),
            }
        )
        assert directs(project) == [
            ("monolog/monolog", "^2.3", "2.3.5", RUNTIME, None),
            ("phpunit/phpunit", "^9.5", "9.5.0", DEV, None),
        ]
        assert transitives(project) == [
            ("psr/log", "1.1.4", RUNTIME, None),
            ("sebastian/diff", "4.0.4", DEV, None),
        ]
        assert {d.lockfile for d in project.dependencies} == {"composer.lock"}
        assert project.notices == []

    def test_the_lockfile_says_path_and_branch(self) -> None:
        project = parse(
            {
                "composer.json": manifest(require={"acme/tools": "^1.0", "psr/container": "*@dev"}),
                "composer.lock": lockfile(
                    [
                        package("acme/tools", "1.0.0", dist={"type": "path", "url": "tools"}),
                        package("psr/container", "dev-master"),
                    ]
                ),
            }
        )
        assert directs(project) == [
            ("acme/tools", "^1.0", "1.0.0", RUNTIME, REASON_LOCAL),
            ("psr/container", "*@dev", "dev-master", RUNTIME, REASON_BRANCH),
        ]

    def test_another_repository_than_packagist(self) -> None:
        files = {
            "composer.json": manifest(
                require={"me/fork": "^1.0", "monolog/monolog": "^2.3"},
                repositories=[{"type": "vcs", "url": "https://github.com/me/fork"}],
            ),
            "composer.lock": lockfile(
                [
                    package("me/fork", "1.2.0", **{"notification-url": None}),
                    package("monolog/monolog", "2.3.5", {"me/dep": "^1.0"}),
                    package("me/dep", "1.0.0", **{"notification-url": None}),
                ]
            ),
        }
        assert directs(parse(files)) == [
            ("me/fork", "^1.0", "1.2.0", RUNTIME, REASON_OTHER_REPOSITORY),
            ("monolog/monolog", "^2.3", "2.3.5", RUNTIME, None),
        ]
        assert transitives(parse(files)) == [("me/dep", "1.0.0", RUNTIME, REASON_OTHER_REPOSITORY)]

    def test_a_composer_repository_is_not_set_aside(self) -> None:
        # Un miroir de Packagist, un Satis : ses paquets sont cherchés sur Packagist.
        files = {
            "composer.json": manifest(
                require={"a/b": "^1.0"},
                repositories={
                    "packagist.org": False,
                    "mirror": {"type": "composer", "url": "https://mirror.example/"},
                },
            ),
            "composer.lock": lockfile([package("a/b", "1.0.0", **{"notification-url": None})]),
        }
        assert directs(parse(files)) == [("a/b", "^1.0", "1.0.0", RUNTIME, None)]

    def test_conflicts_also_apply_to_transitives(self) -> None:
        project = parse(
            {
                "composer.json": manifest(
                    require={"monolog/monolog": "^2.3"}, conflict={"psr/log": ">=2"}
                ),
                "composer.lock": lockfile(
                    [
                        package("monolog/monolog", "2.3.5", {"psr/log": "^1.0.1 || ^2.0"}),
                        package("psr/log", "1.1.4"),
                    ]
                ),
            }
        )
        assert [(d.name, d.excluded) for d in project.dependencies] == [
            ("monolog/monolog", ()),
            ("psr/log", (">=2",)),
        ]

    def test_a_lockfile_without_manifest_is_all_transitive(self) -> None:
        project = parse({"composer.lock": lockfile([package("a/b", "1.0.0")])})
        assert transitives(project) == [("a/b", "1.0.0", RUNTIME, None)]

    def test_an_unreadable_lockfile_gives_a_notice(self) -> None:
        project = parse({"composer.json": manifest(require={"a/b": "^1.0"}), "composer.lock": "{"})
        assert directs(project) == [("a/b", "^1.0", None, RUNTIME, None)]
        assert [n.file for n in project.notices] == ["composer.lock"]
        assert "JSON invalide" in project.notices[0].message

    def test_no_workspace_a_nested_package_keeps_no_lockfile(self) -> None:
        files = {
            "composer.json": manifest(require={"a/b": "^1.0"}),
            "composer.lock": lockfile([package("a/b", "1.0.0")]),
            "packages/tools/composer.json": manifest(require={"c/d": "^2.0"}),
        }
        nested = parse(files, "packages/tools")
        assert nested.lockfiles == []
        assert directs(nested) == [("c/d", "^2.0", None, RUNTIME, None)]
