"""Les constats de fin de vie (E27, ``checks.eol``) : le cycle d'une version, le cycle conseillé,
la date du jour qui décide, les runtimes et les frameworks, d'après les réponses enregistrées
d'endoflife.date."""

from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from forceupdate import endoflife
from forceupdate.checks import eol
from forceupdate.checks.base import Current
from forceupdate.checks.runtimes import Refusal
from forceupdate.endoflife import Product
from forceupdate.models import Dependency, Ecosystem, FindingKind, Gap, Runtime, Severity
from forceupdate.net import Response

FIXTURES = Path(__file__).parent / "fixtures" / "endoflife"
TODAY = date(2026, 11, 1)


def product(name: str) -> Product:
    """Le produit ``name``, lu dans sa réponse enregistrée."""
    response = Response(
        url=f"{endoflife.BASE_URL}/api/v1/products/{name}",
        status_code=200,
        headers=httpx.Headers({"content-type": "application/json"}),
        content=(FIXTURES / f"{name}.json").read_bytes(),
    )
    return endoflife.parse(name, response, datetime(2026, 11, 1, tzinfo=UTC))


def runtime(name: str, version: str, *, approximate: bool = False, file: str = ".nvmrc") -> Runtime:
    return Runtime(
        product=name, version=version, approximate=approximate, file=file, source=version
    )


def cycle(name: str, version: str, *, approximate: bool = False) -> str | None:
    found = eol.cycle_of(product(name), version, approximate=approximate)
    return None if found.release is None else found.release.name


# ---------------------------------------------------------------------------
# Le cycle d'une version
# ---------------------------------------------------------------------------


class TestCycle:
    @pytest.mark.parametrize(
        ("name", "version", "expected"),
        [
            ("python", "3.8.10", "3.8"),
            ("python", "3.10", "3.10"),
            ("nodejs", "16", "16"),
            ("nodejs", "16.20.2", "16"),
            ("nodejs", "v18.0.0", "18"),
            ("django", "3.2.25", "3.2"),
            ("dotnet", "2.1.0", "2.1"),
            ("dotnet", "8.0", "8"),
            ("dotnet", "10.0.100", "10"),
            ("dotnetfx", "4.8", "4.8"),
            ("dotnetfx", "4.8.1", "4.8.1"),
            ("dotnetfx", "3.5", "3.5-sp1"),
            ("log4j", "2.14.1", "2"),
            ("log4j", "2.12.4", "2.12"),
            ("eclipse-temurin", "17", "17"),
        ],
    )
    def test_the_longest_cycle_that_starts_the_version(
        self, name: str, version: str, expected: str
    ) -> None:
        assert cycle(name, version) == expected

    def test_a_lower_bound_is_completed_with_zeros(self) -> None:
        assert cycle("php", "7", approximate=True) == "7.0"
        assert cycle("php", "7") is None

    def test_nothing_to_say(self) -> None:
        # Plus récente que tous les cycles (en développement), ou une ligne entière (python:3).
        for version in ("3.16", "4.0", "3"):
            found = eol.cycle_of(product("python"), version)
            assert (found.release, found.known) == (None, True)

    def test_an_unknown_version(self) -> None:
        found = eol.cycle_of(product("python"), "2.4")
        assert (found.release, found.known) == (None, False)
        assert eol.cycle_of(product("python"), "pypy").known is False


# ---------------------------------------------------------------------------
# Le cycle conseillé
# ---------------------------------------------------------------------------


class TestAdvised:
    @pytest.mark.parametrize(
        ("name", "after", "today", "expected"),
        [
            # Pas de LTS : le plus récent publié.
            ("python", "3.8", TODAY, "3.15"),
            ("python", "3.8", date(2026, 10, 1), "3.14"),
            # Le plus récent à support long, pas 6.1.
            ("django", "3.2", TODAY, "5.2"),
            # Plus récent que le cycle utilisé : jamais un retour en arrière.
            ("django", "6.0", TODAY, "6.1"),
            # Node.js 26 n'est LTS que depuis le 2026-10-28.
            ("nodejs", "16", TODAY, "26"),
            ("nodejs", "16", date(2026, 10, 27), "24"),
            ("dotnet", "8", TODAY, "10"),
            ("dotnetfx", "4.6.2", TODAY, "4.8.1"),
            ("eclipse-temurin", "8", TODAY, "25"),
            # Tous en fin de vie.
            ("angularjs", "1.8", TODAY, None),
        ],
    )
    def test_advised(self, name: str, after: str, today: date, expected: str | None) -> None:
        found = product(name)
        current = next(r for r in found.releases if r.name == after)
        advice = eol.advised(found, today, after=current)
        assert (None if advice is None else advice.name) == expected

    def test_a_cycle_that_ends_soon_is_advised_only_without_better(self) -> None:
        # Toutes les Electron finissent dans les 6 mois, sauf la dernière parfois : la plus récente.
        found = product("electron")
        current = next(r for r in found.releases if r.name == "44")
        advice = eol.advised(found, TODAY, after=current)
        assert advice is not None and advice.name == "45"

    @pytest.mark.parametrize(
        ("day", "months", "expected"),
        [
            (date(2026, 11, 1), 6, date(2027, 5, 1)),
            (date(2026, 8, 31), 6, date(2027, 2, 28)),
            (date(2027, 8, 31), 6, date(2028, 2, 29)),
            (date(2026, 1, 15), 11, date(2026, 12, 15)),
        ],
    )
    def test_months_later(self, day: date, months: int, expected: date) -> None:
        assert eol.months_later(day, months) == expected


# ---------------------------------------------------------------------------
# Les runtimes
# ---------------------------------------------------------------------------


class TestRuntime:
    def test_an_ended_runtime(self) -> None:
        found = eol.check_runtime(
            runtime("python", "3.8", file=".python-version"), product("python"), TODAY
        )
        assert found is not None
        assert (found.kind, found.severity, found.dependency) == (
            FindingKind.EOL,
            Severity.MEDIUM,
            None,
        )
        assert found.message == (
            "Python 3.8 : fin de vie depuis le 07/10/2024. Lu dans .python-version : 3.8. Cycle "
            "conseillé : 3.15, dernière version 3.15.2."
        )
        assert (found.current_version, found.target_version, found.gap) == ("3.8", "3.15.2", None)
        assert found.url == "https://endoflife.date/python"
        assert found.eol is not None
        assert (found.eol.cycle, found.eol.ends_on, found.eol.passed) == (
            "3.8",
            date(2024, 10, 7),
            True,
        )
        assert (found.eol.advised_cycle, found.eol.advised_version, found.eol.advised_lts) == (
            "3.15",
            "3.15.2",
            False,
        )
        assert found.eol.runtime is not None and found.eol.runtime.file == ".python-version"

    def test_a_lower_bound(self) -> None:
        bound = Runtime(
            product="go",
            version="1.21",
            approximate=True,
            file="go.mod",
            source="go 1.21",
        )
        found = eol.check_runtime(bound, product("go"), TODAY)
        assert found is not None and found.current_is_approximate
        assert found.message == (
            "Go 1.21 : fin de vie depuis le 13/08/2024. Lu dans go.mod : go 1.21 (au moins "
            "1.21). Cycle conseillé : 1.27, dernière version 1.27.3."
        )

    def test_soon(self) -> None:
        # .NET 8 finit le 2026-11-10 : dans moins de 6 mois.
        found = eol.check_runtime(
            runtime("dotnet", "8.0", file="App.csproj"), product("dotnet"), TODAY
        )
        assert found is not None and found.severity is Severity.LOW
        assert found.eol is not None and not found.eol.passed
        assert found.message.startswith(
            ".NET 8 : fin de vie le 10/11/2026, dans moins de 6 mois. Lu dans App.csproj"
        )
        assert found.message.endswith("Cycle conseillé : 10 (LTS), dernière version 10.0.13.")
        # Six mois plus tôt, ce n'était pas encore à dire.
        assert (
            eol.check_runtime(runtime("dotnet", "8.0"), product("dotnet"), date(2026, 5, 9)) is None
        )

    @pytest.mark.parametrize(
        ("name", "version"),
        [("python", "3.12"), ("python", "3.16"), ("nodejs", "24"), ("go", "1.27")],
    )
    def test_nothing_to_say(self, name: str, version: str) -> None:
        assert eol.check_runtime(runtime(name, version), product(name), TODAY) is None

    def test_an_unknown_version_is_inconclusive(self) -> None:
        found = eol.check_runtime(runtime("python", "2.4"), product("python"), TODAY)
        assert found is not None and found.kind is FindingKind.INCONCLUSIVE
        assert found.message == (
            "Python 2.4 : version inconnue d'endoflife.date, fin de vie non vérifiée. Lu dans "
            ".nvmrc : 2.4."
        )

    def test_selected_runtimes(self) -> None:
        found = [
            runtime("python", "3.8", approximate=True, file="pyproject.toml"),
            runtime("nodejs", "16", approximate=True, file="package.json"),
            runtime("nodejs", "16", file=".nvmrc"),
            runtime("python", "3.8", file=".python-version"),
            runtime("python", "3.8", file="Dockerfile"),
            runtime("python", "3.11", file="api/Dockerfile"),
        ]
        assert [(r.product, r.version, r.file) for r in eol.selected_runtimes(found)] == [
            ("python", "3.8", ".python-version"),
            ("python", "3.11", "api/Dockerfile"),
            ("nodejs", "16", ".nvmrc"),
        ]


# ---------------------------------------------------------------------------
# Les frameworks
# ---------------------------------------------------------------------------


def dependency(ecosystem: Ecosystem, name: str, version: str = "1.0") -> Dependency:
    return Dependency(ecosystem=ecosystem, name=name, constraint=version, file="m")


class TestFramework:
    @pytest.mark.parametrize(
        ("ecosystem", "name", "expected"),
        [
            (Ecosystem.PYPI, "django", "django"),
            (Ecosystem.NPM, "@angular/core", "angular"),
            (Ecosystem.NPM, "@angular/common", None),
            (Ecosystem.NPM, "angular", "angularjs"),
            (Ecosystem.NPM, "electron", "electron"),
            (Ecosystem.PACKAGIST, "laravel/framework", "laravel"),
            (Ecosystem.PACKAGIST, "symfony/console", "symfony"),
            (Ecosystem.PACKAGIST, "symfony/polyfill-mbstring", None),
            (Ecosystem.PACKAGIST, "symfony/service-contracts", None),
            (Ecosystem.RUBYGEMS, "rails", "rails"),
            (Ecosystem.MAVEN, "org.springframework.boot", "spring-boot"),
            (Ecosystem.MAVEN, "org.springframework.boot:spring-boot-starter-parent", "spring-boot"),
            (Ecosystem.MAVEN, "org.springframework:spring-webmvc", "spring-framework"),
            (Ecosystem.MAVEN, "org.springframework.data:spring-data-jpa", None),
            (Ecosystem.NUGET, "Microsoft.AspNetCore.Http", "dotnet"),
            (Ecosystem.NUGET, "microsoft.aspnetcore.authentication.jwtbearer", "dotnet"),
            (Ecosystem.NUGET, "Microsoft.Extensions.Logging", None),
            (Ecosystem.PYPI, "flask", None),
        ],
    )
    def test_the_table(self, ecosystem: Ecosystem, name: str, expected: str | None) -> None:
        assert eol.framework(dependency(ecosystem, name)) == expected

    def test_an_ended_framework(self) -> None:
        django = dependency(Ecosystem.PYPI, "django", "==3.2.25")
        found = eol.check_framework(django, Current(version="3.2.25"), product("django"), TODAY)
        assert found is not None and found.dependency == django
        assert found.message == (
            "Django 3.2 : fin de vie depuis le 01/04/2024. Cycle conseillé : 5.2 (LTS), dernière "
            "version 5.2.18."
        )
        assert (found.target_version, found.gap) == ("5.2.18", Gap.MAJOR)
        assert found.eol is not None and found.eol.runtime is None and found.eol.advised_lts

    def test_the_advised_version_needs_a_newer_runtime(self) -> None:
        refusal = Refusal(
            requires=">=3.10",
            runtime=runtime("python", "3.8", approximate=True, file="pyproject.toml"),
        )
        django = dependency(Ecosystem.PYPI, "django", "==3.2.25")
        found = eol.check_framework(
            django, Current(version="3.2.25"), product("django"), TODAY, {"5.2.18": refusal}
        )
        assert found is not None and found.eol is not None
        assert found.eol.advised_blocked == (
            "5.2.18 demande Python >=3.10 ; le projet : 3.8 et plus (pyproject.toml). Changer de "
            "Python d'abord."
        )
        assert found.message.endswith(
            "dernière version 5.2.18, qui demande Python >=3.10 ; le projet : 3.8 et plus "
            "(pyproject.toml). Changer de Python d'abord."
        )

    def test_ended_without_a_date(self) -> None:
        nest = dependency(Ecosystem.NPM, "@nestjs/core", "^10.3.0")
        found = eol.check_framework(
            nest, Current(version="10.3.0", approximate=True), product("nestjs"), TODAY
        )
        assert found is not None and found.eol is not None
        assert found.eol.ends_on is None and found.eol.passed
        assert found.message.startswith(
            "NestJS 10 : en fin de vie (endoflife.date n'en donne pas la date)."
        )

    def test_no_advice_when_every_cycle_ended(self) -> None:
        angular = dependency(Ecosystem.NPM, "angular", "1.8.3")
        found = eol.check_framework(angular, Current(version="1.8.3"), product("angularjs"), TODAY)
        assert found is not None and found.message.endswith("Aucun cycle maintenu à conseiller.")
        assert found.target_version is None

    def test_the_newest_electron_is_not_a_finding(self) -> None:
        electron = dependency(Ecosystem.NPM, "electron", "45.2.1")
        assert (
            eol.check_framework(electron, Current(version="45.2.1"), product("electron"), TODAY)
            is None
        )
        older = eol.check_framework(
            electron, Current(version="44.10.1"), product("electron"), TODAY
        )
        assert older is not None and older.severity is Severity.LOW

    def test_an_unknown_version_is_inconclusive(self) -> None:
        old = dependency(Ecosystem.PYPI, "django", "==0.96")
        found = eol.check_framework(old, Current(version="0.96"), product("django"), TODAY)
        assert found is not None and found.kind is FindingKind.INCONCLUSIVE
        assert found.message == (
            "Version 0.96 inconnue d'endoflife.date (Django) : fin de vie non vérifiée."
        )

    def test_an_unknown_current_version(self) -> None:
        django = dependency(Ecosystem.PYPI, "django", "")
        assert eol.check_framework(django, Current(version=None), product("django"), TODAY) is None


def test_the_clock_is_the_recording_day() -> None:
    # tests/conftest.py fixe la date du jour : jamais l'horloge.
    assert eol.today() == TODAY
