"""Les contrôles : les constats d'une dépendance, d'après ce que dit son registre.

- ``base.py`` : la version actuelle (brief, décision n°2), la plus proche version de
  remplacement ;
- ``outdated.py`` : une version plus récente existe (type 1) ;
- ``deprecated.py`` : paquet ou version déprécié, version retirée (type 4) ;
- ``priority.py`` : l'ordre des constats (décision n°8) et le seuil de ``--fail-on``.

Les failles (``vulns.py``, type 2) viennent à E08, les fins de vie (``eol.py``, type 3) à E27.
Les contrôles ne parlent pas au réseau : le moteur leur donne le ``PackageInfo`` du registre.
"""

from forceupdate.checks import deprecated, outdated
from forceupdate.checks.base import GAP_LABELS, Current, current_version
from forceupdate.checks.priority import FailOn, fails, priority, reaches, sort_findings
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
    """Vrai si l'analyse vérifie ``dependency`` : une directe, ou une indirecte avec
    ``options.transitive`` ; de développement seulement avec ``options.dev``."""
    return (dependency.direct or options.transitive) and (
        options.dev or dependency.scope is not Scope.DEV
    )


def check_dependency(dependency: Dependency, info: PackageInfo) -> list[Finding]:
    """Les constats de ``dependency``, vérifiable, d'après ``info``, ce que son registre en
    dit : déprécié, retiré, plus récente. Une liste vide si elle est à jour."""
    current = current_version(dependency)
    return [
        *deprecated.check(dependency, info, current),
        *outdated.check(dependency, info, current),
    ]
