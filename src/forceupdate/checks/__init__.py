"""Les contrôles : les constats d'une dépendance, d'après ce que dit son registre.

- ``base.py`` : la version actuelle (brief, décision n°2), la plus proche version de
  remplacement ;
- ``outdated.py`` : une version plus récente existe (type 1) ;
- ``deprecated.py`` : paquet ou version déprécié, version retirée (type 4) ;
- ``vulns.py`` : la version utilisée a une faille connue (type 2) ;
- ``eol.py`` : le runtime ou le framework est en fin de vie (type 3, E27) ;
- ``runtimes.py`` : les versions qu'un runtime du projet ne fait pas tourner (E27) ;
- ``priority.py`` : l'ordre des constats (décision n°8) et le seuil de ``--fail-on``.

Les contrôles ne parlent pas au réseau : le moteur leur donne le ``PackageInfo`` du registre, ce
qu'OSV sait des failles, et ce qu'endoflife.date sait des cycles de vie.
"""

from collections.abc import Mapping

from forceupdate.checks import deprecated, outdated
from forceupdate.checks.base import GAP_LABELS, Current, current_version
from forceupdate.checks.priority import FailOn, fails, priority, reaches, sort_findings
from forceupdate.checks.runtimes import Refusal
from forceupdate.models import Dependency, Finding, ScanOptions, Scope
from forceupdate.registries import PackageInfo

__all__ = [
    "GAP_LABELS",
    "Current",
    "FailOn",
    "check_dependency",
    "current_version",
    "fails",
    "priority",
    "reaches",
    "selected",
    "sort_findings",
]


def selected(dependency: Dependency, options: ScanOptions) -> bool:
    """Vrai si l'analyse vérifie ``dependency`` auprès de son registre : une directe, ou une
    indirecte avec ``options.transitive`` ; de développement seulement avec ``options.dev`` ;
    jamais un paquet ignoré (``Dependency.ignored``, E29), dont seules les failles sont
    cherchées."""
    return (
        dependency.ignored is None
        and (dependency.direct or options.transitive)
        and (options.dev or dependency.scope is not Scope.DEV)
    )


def check_dependency(
    dependency: Dependency,
    info: PackageInfo,
    refused: Mapping[str, Refusal] | None = None,
    resolution: Mapping[str, str] | None = None,
) -> list[Finding]:
    """Les constats de ``dependency``, vérifiable, d'après ``info``, ce que son registre en
    dit : déprécié, retiré, plus récente. Une liste vide si elle est à jour. ``refused`` : les
    versions que le runtime du projet ne fait pas tourner (``runtimes.refused``), jamais
    proposées. ``resolution`` : les réglages de l'outil du projet (``Project.resolution``)."""
    current = current_version(dependency)
    refused = refused or {}
    return [
        *deprecated.check(dependency, info, current, refused),
        *outdated.check(dependency, info, current, refused, resolution or {}),
    ]
