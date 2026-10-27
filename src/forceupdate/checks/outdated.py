"""Type 1 du brief : une version plus récente existe.

Pour une dépendance, trois versions, comme ``npm outdated`` :

- **utilisée** : la version actuelle (``checks.base.current_version``) ;
- **dans la contrainte** (``wanted_version``) : la plus haute que la contrainte accepte déjà.
  On y monte en régénérant le lockfile, sans toucher au manifeste ;
- **dernière** (``target_version``) : la dernière stable du registre (``PackageInfo.latest``),
  à deux précisions près, prises à ``npm outdated`` :

  - si elle est dépréciée, la plus haute non dépréciée qui ne la dépasse pas, s'il y en a :
    ``@types/parse-json`` 7.0.0 est un paquet vide déprécié, on ne le propose pas à qui a la
    4.0.2. Le paquet déprécié est signalé à part (``deprecated.py``) ;
  - si la version utilisée est une pré-version, une pré-version plus récente de la même version
    compte aussi (de ``2.0.0-rc.1``, on propose ``2.0.0-rc.2``), et l'étiquette ``latest`` de
    npm même si c'est une pré-version : chromium-bidi publie ainsi toutes ses versions
    (``158.0.8127-2``).

Le constat porte l'écart entre la version utilisée et la dernière. Une version utilisée au-
dessus de la dernière (la voie ``next`` de npm) ne donne rien.

``npm outdated`` écarte aussi les versions que le Node installé ne peut pas faire tourner
(``engines``) : jsdom 30 demande Node ``^24.15.0``, il ne la propose pas sous Node 24.12.
forceupdate ne connaît pas le Node de la machine (ni celui d'un dépôt distant), et la propose.

**Dans la contrainte, pour npm (tranché à E07)** : on choisit comme ``npm install`` et
``npm outdated`` (``npm-pick-manifest``), pas simplement la plus haute qui respecte la plage.
La version de l'étiquette ``latest`` si la plage l'accepte et qu'elle n'est pas dépréciée ;
sinon la plus haute non dépréciée ; sinon la plus haute. Une plage ``>=4`` donne donc la
``latest`` 4.17.21, pas une 5.0.0 publiée sous ``next``. Une étiquette (``"react": "next"``)
donne sa version. PyPI : la plus haute non retirée qui respecte la contrainte, comme pip.
"""

from forceupdate import versions
from forceupdate.checks.base import GAP_LABELS, Current
from forceupdate.models import Dependency, Ecosystem, Finding, FindingKind, Gap, Severity
from forceupdate.registries import PackageInfo
from forceupdate.versions import InvalidVersion, VersionScheme
from forceupdate.versions.npm import NPM, NpmRange


def check(dependency: Dependency, info: PackageInfo, current: Current) -> list[Finding]:
    """Le constat « plus récente » de ``dependency`` ; une liste vide si elle est à jour, ou
    si le registre n'a rien à proposer (pas de dernière stable)."""
    scheme = versions.for_ecosystem(dependency.ecosystem)
    if current.version is not None:
        try:
            scheme.parse(current.version)
        except InvalidVersion:
            return [
                Finding(
                    kind=FindingKind.INCONCLUSIVE,
                    message=(
                        f"Version « {current.version} » illisible selon les règles de "
                        f"{dependency.ecosystem} : impossible de la comparer."
                    ),
                    dependency=dependency,
                    current_version=current.version,
                    url=info.url,
                )
            ]
    target = _target(scheme, info, current.version)
    if target is None:
        return []
    wanted = wanted_version(dependency, info, current)
    if current.version is None:
        return [
            Finding(
                kind=FindingKind.INCONCLUSIVE,
                message=f"Version utilisée inconnue : {current.unknown}. Dernière : {target}.",
                dependency=dependency,
                target_version=target,
                wanted_version=wanted,
                url=info.url,
            )
        ]
    gap = scheme.gap(current.version, target)
    if gap is None:
        return []
    return [
        Finding(
            kind=FindingKind.OUTDATED,
            severity=Severity.LOW if gap is Gap.MAJOR else Severity.INFO,
            message=_message(scheme, current, target, gap, wanted),
            dependency=dependency,
            current_version=current.version,
            current_is_approximate=current.approximate,
            target_version=target,
            wanted_version=wanted,
            gap=gap,
            url=info.url,
        )
    ]


def wanted_version(dependency: Dependency, info: PackageInfo, current: Current) -> str | None:
    """La plus haute version que la contrainte accepte déjà, choisie comme le ferait le
    gestionnaire de paquets ; ``None`` pour une dépendance indirecte (sa contrainte est celle
    du paquet qui la tire) ou une contrainte illisible."""
    if not dependency.direct or current.constraint is None:
        return None
    scheme = versions.for_ecosystem(dependency.ecosystem)
    constraint = scheme.parse_constraint(current.constraint)
    if isinstance(constraint, NpmRange) and constraint.tag is not None:
        return info.tags.get(constraint.tag)
    if dependency.ecosystem is Ecosystem.NPM:
        return _npm_wanted(current.constraint, info, current.version)
    return scheme.max_satisfying(current.constraint, info.available(), current.version)


def _npm_wanted(constraint: str, info: PackageInfo, current: str | None) -> str | None:
    """Le choix de ``npm-pick-manifest`` pour une plage (voir la docstring du module)."""
    tagged = info.tags.get("latest")
    published = None if tagged is None else info.get(tagged)
    if published is not None and published.deprecated is None:
        try:
            if NPM.satisfies(constraint, published.version):
                return published.version
        except InvalidVersion:
            pass
    fresh = [v.version for v in info.versions if not v.yanked and v.deprecated is None]
    return NPM.max_satisfying(constraint, fresh, current) or NPM.max_satisfying(
        constraint, info.available(), current
    )


def _target(scheme: VersionScheme, info: PackageInfo, current: str | None) -> str | None:
    """La version à proposer (voir la docstring du module)."""
    target = info.latest
    published = None if target is None else info.get(target)
    if target is not None and published is not None and published.deprecated is not None:
        ceiling = scheme.sort_key(target)
        fresh = [
            v.version
            for v in info.versions
            if not v.yanked and v.deprecated is None and scheme.sort_key(v.version) <= ceiling
        ]
        target = scheme.latest(fresh) or target
    if current is None or not scheme.is_prerelease(current):
        return target
    line = [v for v in scheme.candidates(info.available(), current) if scheme.is_prerelease(v)]
    for option in (scheme.latest(line, current), _prerelease_tag(scheme, info, current)):
        if option is not None and (target is None or scheme.compare(option, target) > 0):
            target = option
    return target


def _prerelease_tag(scheme: VersionScheme, info: PackageInfo, current: str) -> str | None:
    """L'étiquette ``latest`` de npm si c'est une pré-version plus récente que ``current``, non
    dépréciée ; ``None`` sinon."""
    tagged = info.tags.get("latest")
    if tagged is None:
        return None
    published = info.get(tagged)
    if published is None or published.yanked or published.deprecated is not None:
        return None
    try:
        if scheme.is_prerelease(tagged) and scheme.compare(tagged, current) > 0:
            return tagged
    except InvalidVersion:
        pass
    return None


def _message(
    scheme: VersionScheme, current: Current, target: str, gap: Gap, wanted: str | None
) -> str:
    assert current.version is not None
    if current.approximate:
        used = f"au moins {current.version} d'après la contrainte (pas de version installée)"
    else:
        used = current.version
    text = f"Version {target} disponible ({GAP_LABELS[gap]}) ; utilisée : {used}."
    if wanted is None:
        return text
    try:
        if scheme.compare(wanted, target) == 0:
            text += " La contrainte l'accepte déjà."
        elif scheme.compare(wanted, current.version) > 0:
            text += f" La contrainte accepte jusqu'à {wanted}."
    except InvalidVersion:  # une étiquette npm qui pointe vers une version illisible
        pass
    return text
