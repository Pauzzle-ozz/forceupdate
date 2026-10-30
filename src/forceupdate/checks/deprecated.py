"""Type 4 du brief : le paquet est abandonné ou déprécié, la version utilisée est retirée.

- **paquet déprécié** (``PackageInfo.deprecated``) : projet PyPI archivé ou déprécié, paquet
  npm dont la ``latest`` est dépréciée, ou retiré par l'équipe sécurité de npm. Signalé, sans
  version à proposer : le remplacer est un choix humain ;
- **version retirée** (PyPI, ``yanked``), avec la raison donnée : à remplacer par la plus
  proche non retirée (``checks.base.nearest``) ;
- **version dépréciée** (npm, qui n'a pas de retrait : c'est sa façon de désavouer une version,
  lodash 4.18.0 « Bad release ») : à remplacer par la plus proche non dépréciée. Quand tout le
  paquet est déprécié, seul le paquet est signalé ;
- **version inconnue du registre** : dépubliée, ou venue d'un autre index. On ne peut pas dire
  si elle est retirée : « non concluant ». Sauf une pseudo-version Go (un commit), que le proxy
  ne liste jamais (``VersionScheme.unlisted``) : rien à en dire ;
- **version retirée d'un module Go** (``retract``) : comme un retrait PyPI, avec la raison que
  donne le ``go.mod`` du module. Son remplacement reste sous le même chemin de module (une autre
  majeure en change : ``VersionScheme.moved``).

Seule une version connue est examinée : l'installée, ou celle qu'impose une contrainte exacte.
Une borne basse (``>=2.32.0``) ne dit pas qu'on utilise ``2.32.0``.
"""

from forceupdate import versions
from forceupdate.checks.base import Current, nearest, sentence
from forceupdate.models import Dependency, Ecosystem, Finding, FindingKind, Gap, Severity
from forceupdate.registries import PackageInfo
from forceupdate.versions import InvalidVersion

_REGISTRIES = {Ecosystem.GO: "proxy.golang.org"}
"""Le registre dans les messages, quand ce n'est pas le nom de l'écosystème."""

_RETIRED = {Ecosystem.GO: "retirée par l'auteur du module (retract)"}
"""Qui retire une version, quand ce n'est pas le registre : un module Go se retire lui-même."""


def check(dependency: Dependency, info: PackageInfo, current: Current) -> list[Finding]:
    """Les constats « déprécié » et « retiré » de ``dependency`` ; une liste vide s'il n'y a
    rien à signaler."""
    findings = []
    common = {
        "dependency": dependency,
        "current_version": current.version,
        "current_is_approximate": current.approximate,
        "url": info.url,
    }
    if info.deprecated is not None:
        findings.append(
            Finding(
                kind=FindingKind.DEPRECATED,
                severity=Severity.LOW,
                message=f"Paquet déprécié : {info.deprecated}",
                detail=info.deprecated,
                **common,
            )
        )
    if current.version is None or current.approximate:
        return findings
    registry = _REGISTRIES.get(dependency.ecosystem, dependency.ecosystem.value)
    scheme = versions.for_ecosystem(dependency.ecosystem)
    published = info.get(current.version)
    if published is None and scheme.unlisted(current.version):
        return findings
    if published is None:
        findings.append(
            Finding(
                kind=FindingKind.INCONCLUSIVE,
                message=(
                    f"Version {current.version} inconnue de {registry} : dépubliée, ou venue "
                    f"d'un autre index. Impossible de dire si elle est retirée."
                ),
                **common,
            )
        )
        return findings
    same_path = [
        v
        for v in info.versions
        if scheme.moved(dependency.name, v.version) is None and v.version not in dependency.excluded
    ]
    if published.yanked:
        target = _nearest(scheme, current.version, [v.version for v in same_path if not v.yanked])
        reason = f" : {published.yanked_reason}" if published.yanked_reason else ""
        retired = _RETIRED.get(dependency.ecosystem, f"retirée de {registry}")
        reason = sentence(f"Version {current.version} {retired}{reason}")
        replacement = (
            f"La plus proche non retirée : {target}."
            if target is not None
            else "Aucune version non retirée à proposer."
        )
        findings.append(
            Finding(
                kind=FindingKind.YANKED,
                severity=Severity.MEDIUM,
                message=f"{reason} {replacement}",
                target_version=target,
                gap=_gap(scheme, current.version, target),
                detail=published.yanked_reason,
                **common,
            )
        )
    elif published.deprecated is not None and info.deprecated is None:
        fresh = [v.version for v in same_path if not v.yanked and v.deprecated is None]
        target = _nearest(scheme, current.version, fresh)
        replacement = (
            f"La plus proche non dépréciée : {target}."
            if target is not None
            else "Aucune version non dépréciée à proposer."
        )
        findings.append(
            Finding(
                kind=FindingKind.DEPRECATED,
                severity=Severity.LOW,
                message=(
                    sentence(f"Version {current.version} dépréciée : {published.deprecated}")
                    + f" {replacement}"
                ),
                target_version=target,
                gap=_gap(scheme, current.version, target),
                detail=published.deprecated,
                **common,
            )
        )
    return findings


def _nearest(scheme: versions.VersionScheme, current: str, choices: list[str]) -> str | None:
    try:
        return nearest(scheme, current, choices)
    except InvalidVersion:  # version utilisée illisible : outdated le dit déjà
        return None


def _gap(scheme: versions.VersionScheme, current: str, target: str | None) -> Gap | None:
    return None if target is None else scheme.gap(current, target)
