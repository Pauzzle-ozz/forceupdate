"""Type 3 du brief : le runtime ou le framework est en fin de vie, ou le sera bientôt (E27).

Les cycles de vie viennent d'endoflife.date (``forceupdate.endoflife``). Deux sortes de
constats ``eol`` :

- **un runtime** (``Project.runtimes`` : Python, Node.js, Go, Ruby, PHP, Java, .NET), lu dans le
  projet sans rien exécuter (``parsers.runtimes``). Il est signalé seulement : changer de runtime
  ne s'automatise pas. ``Finding.dependency`` est ``None`` ; ``Finding.eol.runtime`` dit ce qui a
  été lu. Pour un même runtime, les versions choisies (``.python-version``, ``.nvmrc``, un
  ``FROM``) comptent plutôt que les bornes basses (``requires-python``) ; chaque cycle distinct
  donne son constat ;
- **un framework** : une dépendance de ``FRAMEWORKS`` (Django, Rails, Spring Boot, Laravel,
  Symfony, Angular, Vue, Nuxt, Electron, ASP.NET Core…), dont la version utilisée donne le cycle.
  Il monte comme toute autre dépendance (type 1) : le planificateur propose en plus la dernière
  version du cycle conseillé (``UpdateReason.SUPPORTED_CYCLE``). Un constat par cycle et par
  projet, sur la première dépendance du produit (les starters de Spring Boot ne le répètent pas).

**Le cycle d'une version** (``cycle_of``) : le plus long cycle d'endoflife.date dont les nombres
commencent la version (``3.8`` pour 3.8.10, ``16`` pour 16.20.2, ``2.1`` de .NET pour 2.1.0,
``3.5-sp1`` pour 3.5). Une borne basse se complète de zéros (``>=7`` : 7.0). Une version plus
récente que tous les cycles (Python 3.16 en développement) n'a pas de constat ; une version
choisie moins précise que les cycles (l'image ``python:3``) non plus : elle suit la dernière.
Une version que ne connaît aucun cycle donne un « non concluant ».

**Constat** dans deux cas, à la date du jour (``today``, que les tests fixent) : fin de vie
passée (gravité ``MEDIUM``), ou dans moins de ``SOON_MONTHS`` mois (``LOW``). Il donne la date et
le **cycle conseillé** (``advised``) : parmi les cycles publiés, maintenus et plus récents que celui
utilisé, ceux qui ne finissent pas dans les 6 mois (sinon tous ceux-là), le plus récent à support
long (LTS) s'il y en a, sinon le plus récent. Django 3.2 → 5.2 (LTS), pas 6.1 ; Django 6.0 → 6.1 ;
Node.js 16 → 26 (LTS) ; Python 3.8 → 3.15. Une fin de vie prochaine sans cycle plus récent à
conseiller (la dernière Electron, dont chaque cycle vit 8 mois) n'est pas un constat.

**Une erreur ne donne jamais de faux constat** : endoflife.date injoignable, ou un produit qu'il
ne connaît plus, donne un « non concluant ».
"""

import dataclasses
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from fnmatch import fnmatchcase

from forceupdate import versions
from forceupdate.checks.base import Current
from forceupdate.checks.runtimes import Refusal
from forceupdate.endoflife import Product, Release
from forceupdate.models import (
    Dependency,
    Ecosystem,
    EndOfLife,
    Finding,
    FindingKind,
    Gap,
    Runtime,
    Severity,
)
from forceupdate.parsers.runtimes import LABELS
from forceupdate.versions import InvalidVersion

SOON_MONTHS = 6
"""Une fin de vie dans moins de 6 mois est déjà signalée."""

_SYMFONY = (
    "symfony",
    "framework-bundle",
    "http-kernel",
    "http-foundation",
    "console",
    "routing",
    "dependency-injection",
    "event-dispatcher",
    "config",
    "yaml",
    "process",
    "finder",
    "filesystem",
    "serializer",
    "validator",
    "form",
    "security-bundle",
    "security-core",
    "security-http",
    "twig-bundle",
    "twig-bridge",
    "doctrine-bridge",
    "monolog-bridge",
    "mailer",
    "messenger",
    "cache",
    "options-resolver",
    "property-access",
    "property-info",
    "translation",
    "var-dumper",
    "var-exporter",
    "dotenv",
    "runtime",
    "asset",
    "string",
    "intl",
    "mime",
    "error-handler",
    "web-profiler-bundle",
    "debug-bundle",
    "browser-kit",
    "css-selector",
    "dom-crawler",
    "expression-language",
    "http-client",
    "lock",
    "notifier",
    "rate-limiter",
    "uid",
    "workflow",
    "stopwatch",
)
"""Les paquets de Symfony qui suivent ses versions. Pas ceux qui ont les leurs : les
``*-contracts``, les ``polyfill-*``, ``flex``, ``maker-bundle``, ``monolog-bundle``…"""

FRAMEWORKS: tuple[tuple[Ecosystem, str, str], ...] = (
    # Python
    (Ecosystem.PYPI, "django", "django"),
    (Ecosystem.PYPI, "wagtail", "wagtail"),
    (Ecosystem.PYPI, "numpy", "numpy"),
    (Ecosystem.PYPI, "apache-airflow", "apache-airflow"),
    # npm
    (Ecosystem.NPM, "@angular/core", "angular"),
    (Ecosystem.NPM, "angular", "angularjs"),
    (Ecosystem.NPM, "vue", "vue"),
    (Ecosystem.NPM, "nuxt", "nuxt"),
    (Ecosystem.NPM, "next", "nextjs"),
    (Ecosystem.NPM, "react", "react"),
    (Ecosystem.NPM, "react-native", "react-native"),
    (Ecosystem.NPM, "svelte", "svelte"),
    (Ecosystem.NPM, "electron", "electron"),
    (Ecosystem.NPM, "express", "express"),
    (Ecosystem.NPM, "@nestjs/core", "nestjs"),
    (Ecosystem.NPM, "ember-source", "emberjs"),
    (Ecosystem.NPM, "jquery", "jquery"),
    (Ecosystem.NPM, "jquery-ui", "jquery-ui"),
    (Ecosystem.NPM, "bootstrap", "bootstrap"),
    (Ecosystem.NPM, "tailwindcss", "tailwind-css"),
    (Ecosystem.NPM, "@ionic/core", "ionic"),
    (Ecosystem.NPM, "vuetify", "vuetify"),
    (Ecosystem.NPM, "quasar", "quasar"),
    (Ecosystem.NPM, "@strapi/strapi", "strapi"),
    (Ecosystem.NPM, "@adonisjs/core", "adonisjs"),
    (Ecosystem.NPM, "eslint", "eslint"),
    # E34 : les produits nouveaux d'endoflife.date (le test réseau des tables).
    (Ecosystem.NPM, "protractor", "protractor"),
    (Ecosystem.NPM, "@fortawesome/fontawesome-svg-core", "font-awesome"),
    (Ecosystem.NPM, "@fortawesome/fontawesome-free", "font-awesome"),
    # PHP
    (Ecosystem.PACKAGIST, "laravel/framework", "laravel"),
    (Ecosystem.PACKAGIST, "behat/behat", "behat"),
    (Ecosystem.PACKAGIST, "sylius/sylius", "sylius"),
    *((Ecosystem.PACKAGIST, f"symfony/{name}", "symfony") for name in _SYMFONY),
    (Ecosystem.PACKAGIST, "drupal/core", "drupal"),
    (Ecosystem.PACKAGIST, "drupal/core-recommended", "drupal"),
    (Ecosystem.PACKAGIST, "typo3/cms-core", "typo3"),
    (Ecosystem.PACKAGIST, "cakephp/cakephp", "cakephp"),
    (Ecosystem.PACKAGIST, "magento/product-community-edition", "magento"),
    (Ecosystem.PACKAGIST, "shopware/core", "shopware"),
    (Ecosystem.PACKAGIST, "api-platform/core", "api-platform"),
    (Ecosystem.PACKAGIST, "livewire/livewire", "livewire"),
    (Ecosystem.PACKAGIST, "guzzlehttp/guzzle", "guzzle"),
    (Ecosystem.PACKAGIST, "twbs/bootstrap", "bootstrap"),
    # Ruby
    (Ecosystem.RUBYGEMS, "rails", "rails"),
    (Ecosystem.RUBYGEMS, "railties", "rails"),
    # Java
    (Ecosystem.MAVEN, "org.springframework.boot", "spring-boot"),
    (Ecosystem.MAVEN, "org.springframework.boot:*", "spring-boot"),
    (Ecosystem.MAVEN, "org.springframework:spring-*", "spring-framework"),
    (Ecosystem.MAVEN, "org.springframework.security:spring-security-*", "spring-security"),
    (Ecosystem.MAVEN, "org.springframework.cloud:spring-cloud-dependencies", "spring-cloud"),
    (Ecosystem.MAVEN, "org.hibernate.orm:hibernate-core", "hibernate-orm"),
    (Ecosystem.MAVEN, "org.hibernate:hibernate-core", "hibernate-orm"),
    (Ecosystem.MAVEN, "org.apache.logging.log4j:log4j-core", "log4j"),
    (Ecosystem.MAVEN, "log4j:log4j", "log4j"),
    (Ecosystem.MAVEN, "io.micronaut:micronaut-core", "micronaut"),
    (Ecosystem.MAVEN, "io.quarkus.platform:quarkus-bom", "quarkus-framework"),
    (Ecosystem.MAVEN, "io.quarkus:quarkus-bom", "quarkus-framework"),
    (Ecosystem.MAVEN, "org.apache.struts:struts2-core", "apache-struts"),
    (Ecosystem.MAVEN, "org.eclipse.jetty:jetty-server", "eclipse-jetty"),
    (Ecosystem.MAVEN, "org.apache.tomcat.embed:tomcat-embed-core", "tomcat"),
    (Ecosystem.MAVEN, "org.apache.camel:camel-core", "apache-camel"),
    (Ecosystem.MAVEN, "org.keycloak:keycloak-core", "keycloak"),
    (Ecosystem.MAVEN, "org.apache.groovy:groovy", "apache-groovy"),
    (Ecosystem.MAVEN, "org.codehaus.groovy:groovy", "apache-groovy"),
    (Ecosystem.MAVEN, "org.codehaus.groovy:groovy-all", "apache-groovy"),
    # .NET : les paquets d'ASP.NET Core suivent les versions de .NET (2.1.0 : .NET Core 2.1)
    (Ecosystem.NUGET, "microsoft.aspnetcore.*", "dotnet"),
    (Ecosystem.NUGET, "microsoft.netcore.app", "dotnet"),
    (Ecosystem.NUGET, "jquery", "jquery"),
    (Ecosystem.NUGET, "bootstrap", "bootstrap"),
)
"""Les frameworks suivis : écosystème, nom du paquet (un motif ``*`` permis ; en minuscules pour
NuGet, dont les noms ne tiennent pas compte de la casse) et produit d'endoflife.date. Vérifiée le
2026-11-01 : chaque produit existe, et la version d'un paquet y trouve son cycle. Ce sont les
``purl`` qu'endoflife.date donne à ses produits (``pkg:pypi/django``, ``pkg:npm/vue``…), et ceux
qui lui manquent (Electron, les composants de Symfony, ASP.NET Core)."""


def today() -> date:
    """La date du jour, celle qui décide si une fin de vie est passée ; les tests la fixent."""
    return date.today()


def framework(dependency: Dependency) -> str | None:
    """Le produit d'endoflife.date de ``dependency`` si c'est un framework suivi ; ``None``
    sinon."""
    name = dependency.name.lower() if dependency.ecosystem is Ecosystem.NUGET else dependency.name
    for ecosystem, pattern, product in FRAMEWORKS:
        if ecosystem is dependency.ecosystem and fnmatchcase(name, pattern):
            return product
    return None


WITHOUT_LIFECYCLE = frozenset({"rust"})
"""Les runtimes lus dont la fin de vie n'est pas jugée : Rust (E34) ne suit une version que six
semaines, jusqu'à la suivante (endoflife.date le dit), et son ``rust-version`` est la plus ancienne
que le projet promet de faire tourner, pas celle qui tourne. Il sert aux versions écartées
(``checks.runtimes``)."""


def selected_runtimes(runtimes: Iterable[Runtime]) -> list[Runtime]:
    """Les runtimes à vérifier : pour chaque produit, les versions choisies s'il y en a, sinon
    les bornes basses ; un par version (le premier lu). Pas ceux de ``WITHOUT_LIFECYCLE``."""
    by_product: dict[str, list[Runtime]] = {}
    for runtime in runtimes:
        if runtime.product in WITHOUT_LIFECYCLE:
            continue
        by_product.setdefault(runtime.product, []).append(runtime)
    kept = []
    for found in by_product.values():
        exact = [r for r in found if not r.approximate]
        seen: set[str] = set()
        for runtime in exact or found:
            if runtime.version not in seen:
                seen.add(runtime.version)
                kept.append(runtime)
    return kept


# ---------------------------------------------------------------------------
# Les cycles
# ---------------------------------------------------------------------------


def _numbers(text: str) -> tuple[int, ...]:
    """Les nombres d'une version ou d'un cycle, jusqu'au premier élément qui n'en commence pas
    par un : ``3.5-sp1`` → (3, 5), ``v16.20.2`` → (16, 20, 2), ``8u504`` → (8,)."""
    found = []
    for part in text.strip().lstrip("vV").split("."):
        digits = ""
        for char in part:
            if not char.isdigit():
                break
            digits += char
        if not digits:
            break
        found.append(int(digits))
        if len(digits) != len(part):
            break
    return tuple(found)


@dataclass(frozen=True, kw_only=True)
class Cycle:
    """Ce que dit ``cycle_of`` d'une version."""

    release: Release | None
    """Son cycle ; ``None`` si aucun ne lui correspond."""
    known: bool = True
    """Faux si aucun cycle ne lui correspond alors qu'elle n'est ni plus récente que tous, ni
    moins précise qu'eux : un « non concluant »."""


def cycle_of(product: Product, version: str, *, approximate: bool = False) -> Cycle:
    """Le cycle de ``version`` chez ``product`` (voir la docstring du module)."""
    wanted = _numbers(version)
    if not wanted:
        return Cycle(release=None, known=False)
    best: tuple[int, Release] | None = None
    for release in product.releases:
        cycle = _numbers(release.name)
        if not cycle:
            continue
        if len(cycle) <= len(wanted):
            matches = wanted[: len(cycle)] == cycle
        else:
            # Une borne basse se complète de zéros : « >=7 » est 7.0.
            matches = (
                approximate and cycle[: len(wanted)] == wanted and not any(cycle[len(wanted) :])
            )
        if matches and (best is None or len(cycle) > best[0]):
            best = (len(cycle), release)
    if best is not None:
        return Cycle(release=best[1])
    cycles = [c for c in (_numbers(r.name) for r in product.releases) if c]
    if any(c[: len(wanted)] == wanted for c in cycles if len(c) > len(wanted)):
        return Cycle(release=None)  # une ligne entière (python:3) : elle suit la dernière
    if cycles and all(wanted[: len(c)] > c for c in cycles):
        return Cycle(release=None)  # plus récente que tous les cycles connus
    return Cycle(release=None, known=False)


def months_later(day: date, months: int) -> date:
    """``day`` plus ``months`` mois ; le dernier jour du mois quand il n'a pas ce jour-là."""
    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    for last in (31, 30, 29, 28):
        try:
            return date(year, month, min(day.day, last))
        except ValueError:
            continue
    raise AssertionError(day)  # pragma: no cover


def advised(product: Product, today: date, after: Release | None = None) -> Release | None:
    """Le cycle à conseiller à la date ``today`` (voir la docstring du module), plus récent que
    ``after`` s'il est donné ; ``None`` si aucun n'est maintenu."""
    floor = _numbers(after.name) if after is not None else ()
    alive = [
        release
        for release in product.releases
        if (release.released is None or release.released <= today)
        and not release.ended(today)
        and _numbers(release.name) > floor
    ]
    limit = months_later(today, SOON_MONTHS)
    lasting = [r for r in alive if r.eol_from is None or r.eol_from > limit]
    pool = lasting or alive
    lts = [release for release in pool if release.is_lts(today)]
    choices = lts or pool
    if not choices:
        return None
    return max(choices, key=lambda r: (r.released or date.min, _numbers(r.name)))


# ---------------------------------------------------------------------------
# Les constats
# ---------------------------------------------------------------------------


def check_runtime(runtime: Runtime, product: Product, today: date) -> Finding | None:
    """Le constat de fin de vie de ``runtime`` d'après ``product`` ; ``None`` s'il n'y a rien à
    dire. Un cycle inconnu donne un « non concluant »."""
    label = LABELS.get(runtime.product, product.label)
    cycle = cycle_of(product, runtime.version, approximate=runtime.approximate)
    if cycle.release is None:
        if cycle.known:
            return None
        return Finding(
            kind=FindingKind.INCONCLUSIVE,
            message=(
                f"{label} {runtime.version} : version inconnue d'endoflife.date, fin de vie non "
                f"vérifiée. {_where(runtime)}."
            ),
            current_version=runtime.version,
            current_is_approximate=runtime.approximate,
            url=product.url,
        )
    return _finding(
        label=label,
        product=product,
        release=cycle.release,
        today=today,
        current=runtime.version,
        approximate=runtime.approximate,
        runtime=runtime,
        dependency=None,
    )


def check_framework(
    dependency: Dependency,
    current: Current,
    product: Product,
    today: date,
    refused: Mapping[str, Refusal] | None = None,
) -> Finding | None:
    """Le constat de fin de vie du framework ``dependency``, à sa version ``current`` ; ``None``
    s'il n'y a rien à dire, ou si on ne connaît pas sa version. ``refused`` : les versions que le
    runtime du projet ne fait pas tourner (``checks.runtimes``) ; si la version conseillée en
    est, le constat le dit (Django 5.2 demande Python 3.10 : changer de Python d'abord)."""
    if current.version is None:
        return None
    cycle = cycle_of(product, current.version, approximate=current.approximate)
    if cycle.release is None:
        if cycle.known:
            return None
        return Finding(
            kind=FindingKind.INCONCLUSIVE,
            message=(
                f"Version {current.version} inconnue d'endoflife.date ({product.label}) : fin "
                f"de vie non vérifiée."
            ),
            dependency=dependency,
            current_version=current.version,
            current_is_approximate=current.approximate,
            url=product.url,
        )
    finding = _finding(
        label=product.label,
        product=product,
        release=cycle.release,
        today=today,
        current=current.version,
        approximate=current.approximate,
        runtime=None,
        dependency=dependency,
    )
    target = None if finding is None else finding.target_version
    if finding is None or target is None or target not in (refused or {}):
        return finding
    assert refused is not None
    refusal = refused[target]
    runtime = LABELS.get(refusal.runtime.product, refusal.runtime.product)
    blocked = (
        f"{target} demande {refusal.demand} ; le projet : {refusal.project}. Changer de "
        f"{runtime} d'abord."
    )
    message = (
        f"{finding.message.removesuffix('.')}, qui demande {refusal.demand} ; le projet : "
        f"{refusal.project}. Changer de {runtime} d'abord."
    )
    assert finding.eol is not None
    return dataclasses.replace(
        finding, message=message, eol=dataclasses.replace(finding.eol, advised_blocked=blocked)
    )


def unchecked(label: str, version: str, error: Exception, dependency: Dependency | None) -> Finding:
    """Le « non concluant » d'une fin de vie qu'endoflife.date n'a pas pu dire (``error``)."""
    return Finding(
        kind=FindingKind.INCONCLUSIVE,
        message=f"Fin de vie de {label} {version} non vérifiée. {error}",
        dependency=dependency,
        current_version=version,
    )


def runtime_label(runtime: Runtime) -> str:
    """Le nom affiché d'un runtime : ``Python``, ``Java (Eclipse Temurin)``."""
    return LABELS.get(runtime.product, runtime.product)


def _finding(
    *,
    label: str,
    product: Product,
    release: Release,
    today: date,
    current: str,
    approximate: bool,
    runtime: Runtime | None,
    dependency: Dependency | None,
) -> Finding | None:
    passed = release.ended(today)
    ends_on = release.eol_from
    if not passed and (ends_on is None or ends_on > months_later(today, SOON_MONTHS)):
        return None
    advice = advised(product, today, after=release)
    if not passed and advice is None:
        return None  # le cycle le plus récent finit bientôt (Electron) : rien de mieux à faire
    text = f"{label} {release.name}"
    if passed and ends_on is not None:
        text += f" : fin de vie depuis le {_french(ends_on)}."
    elif passed:
        text += " : en fin de vie (endoflife.date n'en donne pas la date)."
    else:
        assert ends_on is not None
        text += f" : fin de vie le {_french(ends_on)}, dans moins de {SOON_MONTHS} mois."
    if runtime is not None:
        text += f" {_where(runtime)}."
    if advice is None:
        text += " Aucun cycle maintenu à conseiller."
    else:
        lts = " (LTS)" if advice.is_lts(today) else ""
        latest = f", dernière version {advice.latest}" if advice.latest else ""
        text += f" Cycle conseillé : {advice.name}{lts}{latest}."
    target = advice.latest if advice is not None else None
    return Finding(
        kind=FindingKind.EOL,
        severity=Severity.MEDIUM if passed else Severity.LOW,
        message=text,
        dependency=dependency,
        current_version=current,
        current_is_approximate=approximate,
        target_version=target,
        gap=_gap(dependency, current, target),
        url=product.url,
        eol=EndOfLife(
            product=product.name,
            label=label,
            cycle=release.name,
            ends_on=ends_on,
            passed=passed,
            advised_cycle=None if advice is None else advice.name,
            advised_version=target,
            advised_lts=advice is not None and advice.is_lts(today),
            runtime=runtime,
        ),
    )


def _where(runtime: Runtime) -> str:
    """D'où vient la version : ``Lu dans .nvmrc : 16``, ``Lu dans pyproject.toml :
    requires-python = ">=3.8" (au moins 3.8)``."""
    text = f"Lu dans {runtime.file} : {runtime.source}"
    return f"{text} (au moins {runtime.version})" if runtime.approximate else text


def _french(day: date) -> str:
    return day.strftime("%d/%m/%Y")


def _gap(dependency: Dependency | None, current: str, target: str | None) -> Gap | None:
    if dependency is None or target is None:
        return None
    try:
        return versions.for_ecosystem(dependency.ecosystem).gap(current, target)
    except InvalidVersion:
        return None


def dedupe(findings: Sequence[Finding]) -> list[Finding]:
    """Un constat de fin de vie par produit et par cycle : le premier (les starters de Spring
    Boot, les composants de Symfony ne le répètent pas)."""
    seen: set[tuple[str, str]] = set()
    kept = []
    for finding in findings:
        if finding.eol is not None:
            key = (finding.eol.product, finding.eol.cycle)
            if key in seen:
                continue
            seen.add(key)
        kept.append(finding)
    return kept
