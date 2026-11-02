"""Les versions de paquets que le runtime du projet ne peut pas faire tourner (E27).

Une version publiée peut demander un runtime : ``engines.node`` (npm), ``require.php``
(Packagist), ``ruby`` (l'index compact de RubyGems), ``requires-python`` (PyPI), ``rust_version``
(l'index de crates.io, E34). Les outils la refusent quand le runtime ne convient pas : Composer
d'après ``config.platform.php`` (sinon le PHP de la machine), Bundler d'après le Ruby qui tourne,
uv, Poetry et PDM d'après tout l'intervalle de ``requires-python``, ``npm outdated`` d'après le
Node installé (``npm install`` avertit seulement), Cargo avec le résolveur 3 d'après le
``rust-version`` du projet (vérifié avec cargo 1.99 : il prend la plus haute qui convient, et se
replie sur la plus haute sinon ; le résolveur 2, celui de l'édition 2021 et d'avant, l'ignore). La
proposer fait échouer la régénération du lockfile (E23 : forceupdate v8.1.10 de symfony/console,
qui demande PHP 8.4, à un projet en PHP 8.1), ou casse ce que le projet promet de faire tourner
(un ``rust-version`` : sous le résolveur 2, ``cargo update`` la prendrait, et la compilation avec
ce Rust échouerait ; elle n'est pas proposée non plus).

**Le runtime du projet** (``project_runtime``) : le plus ancien de ceux qu'on lit pour
l'écosystème, versions choisies (``.nvmrc``, ``config.platform.php``) comme bornes basses
(``engines.node``, ``require.php``). C'est le plus prudent : uv résout pour toutes les versions de
Python qu'accepte ``requires-python``, même si ``.python-version`` en choisit une plus récente.
Sans runtime lu, rien n'est écarté.

**Une version qui demande plus** est écartée des versions proposées (``refused`` : le constat
« plus récente » vise la plus haute qui convient, le planificateur n'en propose pas d'autre), et
le constat le dit. Une version choisie partielle (``.nvmrc`` : ``16``) désigne toute la ligne 16.x :
elle convient si la dernière de la ligne convient ; une borne basse (``>=16``) vaut 16.0.0.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from forceupdate import versions
from forceupdate.models import Ecosystem, Project, Runtime
from forceupdate.parsers.runtimes import LABELS
from forceupdate.registries import PackageInfo
from forceupdate.versions import InvalidConstraint, InvalidVersion

_REQUIRED = {
    Ecosystem.NPM: "nodejs",
    Ecosystem.PACKAGIST: "php",
    Ecosystem.RUBYGEMS: "ruby",
    Ecosystem.PYPI: "python",
    Ecosystem.CRATES_IO: "rust",
}
"""Les écosystèmes dont le registre dit le runtime que demande chaque version."""

_LINE = 99999
"""Le nombre qui complète une version choisie partielle : ``16`` → ``16.99999.99999``, la dernière
de la ligne."""


@dataclass(frozen=True, kw_only=True)
class Refusal:
    """Une version publiée que le runtime du projet ne peut pas faire tourner."""

    requires: str
    """Ce qu'elle demande, tel que le registre l'écrit (``>=8.4``, ``^24.15.0``)."""
    runtime: Runtime
    """Le runtime du projet."""

    @property
    def demand(self) -> str:
        """Ce qu'elle demande : ``PHP >=8.4``."""
        return f"{LABELS.get(self.runtime.product, self.runtime.product)} {self.requires}"

    @property
    def project(self) -> str:
        """Le runtime du projet : ``8.1 et plus (composer.json)``, ``16 (.nvmrc)``."""
        runtime = self.runtime
        used = f"{runtime.version} et plus" if runtime.approximate else runtime.version
        return f"{used} ({runtime.file})"

    @property
    def reason(self) -> str:
        """En une phrase : ``elle demande PHP >=8.4 ; le projet : 8.1 et plus
        (composer.json)``."""
        return f"elle demande {self.demand} ; le projet : {self.project}"


def project_runtime(project: Project, ecosystem: Ecosystem) -> Runtime | None:
    """Le runtime du projet qui fait tourner les paquets de ``ecosystem`` : le plus ancien de
    ceux qu'on a lus (voir la docstring du module) ; ``None`` si on n'en a lu aucun, ou si le
    registre de ``ecosystem`` ne dit pas ce que demandent ses versions."""
    product = _REQUIRED.get(ecosystem)
    if product is None:
        return None
    scheme = versions.for_ecosystem(ecosystem)
    found = []
    for runtime in project.runtimes:
        if runtime.product != product:
            continue
        try:
            found.append((scheme.parse(probe(runtime)), runtime))
        except InvalidVersion:
            continue
    if not found:
        return None
    return min(found, key=lambda item: item[0])[1]


def probe(runtime: Runtime) -> str:
    """La version à tester contre ce que demande un paquet : trois nombres, complétés par des 0
    pour une borne basse, par ``_LINE`` pour une version choisie partielle (voir la docstring du
    module)."""
    parts = runtime.version.split(".")
    fill = "0" if runtime.approximate else str(_LINE)
    return ".".join([*parts, *[fill] * (3 - len(parts))])


def refused(info: PackageInfo, runtime: Runtime | None) -> Mapping[str, Refusal]:
    """Les versions de ``info`` que ``runtime`` ne peut pas faire tourner, d'après ce que chacune
    demande ; vide sans runtime. Ce qui ne se lit pas (une contrainte illisible) n'écarte rien."""
    if runtime is None or _REQUIRED.get(info.ecosystem) != runtime.product:
        return {}
    scheme = versions.for_ecosystem(info.ecosystem)
    version = probe(runtime)
    found = {}
    for published in info.versions:
        requires = published.requires_runtime
        if not requires:
            continue
        try:
            if not scheme.satisfies(_constraint(info.ecosystem, requires), version):
                found[published.version] = Refusal(requires=requires, runtime=runtime)
        except (InvalidConstraint, InvalidVersion):
            continue
    return found


def _constraint(ecosystem: Ecosystem, requires: str) -> str:
    """``requires`` dans la syntaxe des contraintes de ``ecosystem`` : l'index compact de RubyGems
    sépare ses conditions par ``&`` (``< 4.1.dev&>= 3.2``) ; le ``rust_version`` d'un crate est la
    plus ancienne version de Rust qu'il accepte (``1.80`` : ``>=1.80``)."""
    if ecosystem is Ecosystem.RUBYGEMS:
        return ", ".join(part.strip() for part in requires.split("&"))
    if ecosystem is Ecosystem.CRATES_IO:
        return f">={requires.strip()}"
    return requires
