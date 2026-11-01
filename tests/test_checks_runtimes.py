"""Les versions qu'un runtime du projet ne fait pas tourner (E27, ``checks.runtimes``) : ce que
demande chaque version d'après son registre (``engines.node``, ``require.php``, ``ruby``,
``requires-python``), le runtime retenu pour le projet."""

from typing import Any

import pytest
import respx

from forceupdate.checks import runtimes
from forceupdate.models import Ecosystem, Project, Runtime
from forceupdate.registries import PackageInfo
from forceupdate.registries.npm import Npm
from forceupdate.registries.packagist import Packagist
from forceupdate.registries.pypi import PyPI
from forceupdate.registries.rubygems import RubyGems

Routes = dict[str, respx.Route]


def runtime(product: str, version: str, *, approximate: bool = False, file: str = "f") -> Runtime:
    return Runtime(
        product=product, version=version, approximate=approximate, file=file, source=version
    )


def info(lookup: Any, registry: Any, name: str) -> PackageInfo:
    (found,) = lookup(registry, name)
    assert isinstance(found, PackageInfo)
    return found


class TestWhatEachVersionRequires:
    def test_npm_engines(self, recorded: Routes, lookup: Any) -> None:
        found = info(lookup, Npm, "p-limit")
        assert found.get("4.0.0").requires_runtime == "^12.20.0 || ^14.13.1 || >=16.0.0"  # type: ignore[union-attr]
        assert found.get("7.3.3").requires_runtime == ">=20"  # type: ignore[union-attr]

    def test_packagist_require_php(self, recorded: Routes, lookup: Any) -> None:
        found = info(lookup, Packagist, "symfony/console")
        assert found.get("v8.1.10").requires_runtime == ">=8.4.1"  # type: ignore[union-attr]
        assert found.get("v6.4.49").requires_runtime == ">=8.1"  # type: ignore[union-attr]

    def test_rubygems_ruby(self, recorded: Routes, lookup: Any) -> None:
        found = info(lookup, RubyGems, "minitest")
        # Telle que l'écrit l'index compact : ses conditions séparées par « & ».
        assert found.get("5.15.0").requires_runtime == "< 4.0&>= 2.2"  # type: ignore[union-attr]

    def test_pypi_requires_python(self, recorded: Routes, lookup: Any) -> None:
        found = info(lookup, PyPI, "django")
        assert found.get("5.2.18").requires_runtime == ">=3.10"  # type: ignore[union-attr]
        assert found.get("3.2.25").requires_runtime == ">=3.6"  # type: ignore[union-attr]


class TestProjectRuntime:
    def test_the_oldest_one(self) -> None:
        project = Project(
            path=".",
            runtimes=[
                runtime("nodejs", "20", file=".nvmrc"),
                runtime("nodejs", "16", approximate=True, file="package.json"),
                runtime("python", "3.8"),
            ],
        )
        found = runtimes.project_runtime(project, Ecosystem.NPM)
        assert found is not None and found.file == "package.json"
        assert runtimes.project_runtime(project, Ecosystem.PACKAGIST) is None
        # Go ne dit pas ce que demande chaque version : rien n'est écarté.
        project.runtimes.append(runtime("go", "1.21"))
        assert runtimes.project_runtime(project, Ecosystem.GO) is None

    @pytest.mark.parametrize(
        ("version", "approximate", "expected"),
        [
            ("16", False, "16.99999.99999"),
            ("16.20", False, "16.20.99999"),
            ("16.20.2", False, "16.20.2"),
            ("16", True, "16.0.0"),
            ("8.1", True, "8.1.0"),
        ],
    )
    def test_probe(self, version: str, approximate: bool, expected: str) -> None:
        assert runtimes.probe(runtime("nodejs", version, approximate=approximate)) == expected


class TestRefused:
    def test_npm(self, recorded: Routes, lookup: Any) -> None:
        found = info(lookup, Npm, "p-limit")
        refused = runtimes.refused(
            found, runtime("nodejs", "16", approximate=True, file="package.json")
        )
        assert "4.0.0" not in refused and "3.1.0" not in refused
        assert {"5.0.0", "6.2.0", "7.3.3"} <= set(refused)
        assert refused["7.3.3"].reason == (
            "elle demande Node.js >=20 ; le projet : 16 et plus (package.json)"
        )
        # Une ligne choisie (.nvmrc : 18) : la dernière 18.x fait tourner les 5 et 6.
        refused = runtimes.refused(found, runtime("nodejs", "18", file=".nvmrc"))
        assert "6.2.0" not in refused and "7.3.3" in refused
        assert refused["7.3.3"].reason == "elle demande Node.js >=20 ; le projet : 18 (.nvmrc)"

    def test_packagist(self, recorded: Routes, lookup: Any) -> None:
        found = info(lookup, Packagist, "symfony/console")
        refused = runtimes.refused(found, runtime("php", "8.1.30", file="composer.json"))
        assert "v8.1.10" in refused and "v7.0.0" in refused
        assert "v6.4.49" not in refused and "v5.4.55" not in refused

    def test_rubygems(self, recorded: Routes, lookup: Any) -> None:
        found = info(lookup, RubyGems, "minitest")
        refused = runtimes.refused(found, runtime("ruby", "4.0.9", file="Gemfile.lock"))
        assert "5.15.0" in refused and "5.26.1" not in refused

    def test_pypi(self, recorded: Routes, lookup: Any) -> None:
        found = info(lookup, PyPI, "django")
        refused = runtimes.refused(found, runtime("python", "3.8", approximate=True))
        assert "5.2.18" in refused and "6.1.2" in refused
        assert "4.2.30" not in refused and "3.2.25" not in refused

    def test_nothing_without_a_runtime_or_for_another_one(
        self, recorded: Routes, lookup: Any
    ) -> None:
        found = info(lookup, Npm, "p-limit")
        assert runtimes.refused(found, None) == {}
        assert runtimes.refused(found, runtime("python", "3.8")) == {}

    def test_an_unreadable_requirement_refuses_nothing(self) -> None:
        from datetime import UTC, datetime

        from forceupdate.registries.base import PackageVersion

        found = PackageInfo(
            ecosystem=Ecosystem.NPM,
            name="x",
            versions=(PackageVersion(version="1.0.0", requires_runtime="pas une plage !"),),
            latest="1.0.0",
            fetched_at=datetime.now(UTC),
        )
        assert runtimes.refused(found, runtime("nodejs", "16")) == {}
