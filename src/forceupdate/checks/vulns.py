"""Type 2 du brief : la version utilisée a une faille connue.

Les failles se cherchent sur toutes les dépendances vérifiables, indirectes comprises (brief,
décision n°3), quelle que soit ``--transitive``, qui ne vaut que pour les versions plus
récentes et les retraits ; celles de développement sauf avec ``--no-dev``. C'est le moteur qui
interroge OSV (``advisories``) ; ce module en tire les constats.

- **Une faille, un constat.** OSV a souvent plusieurs avis pour la même faille : celui de
  GitHub (GHSA) et celui de PyPI (PYSEC), qui se citent l'un l'autre dans leurs alias. Ils
  sont réunis, avec tous leurs identifiants : les CVE d'abord, puis les GHSA, puis les autres.
  Les avis d'un paquet malveillant sont tous réunis : ils disent la même chose.
- **Gravité** : celle du plus grave des avis réunis (CVSS 3, sinon celle de GitHub). Un paquet
  malveillant est toujours critique. Sans rien pour en juger, moyenne : le message dit
  « gravité inconnue ».
- **Version corrigée** (``target_version``) : la plus petite qui corrige la faille au-dessus de
  la version utilisée (``Advisory.fixed_in``) ; si les avis réunis ne sont pas d'accord, la
  plus haute des leurs.
- **Version utilisée** : l'installée, ou celle d'une contrainte exacte. Sans lockfile, la
  borne basse de la contrainte, « approximative » : la faille n'est alors que **possible**
  (affichée « faille possible »), car la version réellement installée peut être plus récente,
  et corrigée. Elle reste une faille, et compte pour ``--fail-on vuln`` : la contrainte
  accepte une version concernée, et la relever la corrige. Sans version utilisée (``*``, une
  étiquette npm), rien n'est demandé à OSV ; le contrôle « plus récente » le dit déjà.
- **Erreur** : jamais « pas de faille ». Une version qu'OSV n'a pas pu examiner donne un
  constat « non concluant » (``unchecked``) ; un avis illisible reste une faille, de gravité et
  de version corrigée inconnues.
"""

from collections.abc import Sequence

from forceupdate import versions
from forceupdate.advisories import Advisory, OsvError, Vulnerabilities
from forceupdate.checks.base import Current, current_version, sentence
from forceupdate.models import Dependency, Finding, FindingKind, ScanOptions, Scope, Severity

SEVERITY_LABELS = {
    Severity.CRITICAL: "critique",
    Severity.HIGH: "élevée",
    Severity.MEDIUM: "moyenne",
    Severity.LOW: "faible",
    Severity.INFO: "nulle",
}
"""La gravité d'une faille en français, telle qu'on l'affiche."""

_PREFIXES = ("CVE-", "GHSA-")
"""Les identifiants qu'on cite dans le message, et qui passent en tête de ``identifiers``."""


def audited(dependency: Dependency, options: ScanOptions) -> bool:
    """Vrai si l'analyse cherche les failles de ``dependency`` : vérifiable, directe ou non ;
    de développement seulement avec ``options.dev``. Encore faut-il connaître sa version
    (``version_to_check``)."""
    return dependency.verifiable and (options.dev or dependency.scope is not Scope.DEV)


def version_to_check(dependency: Dependency) -> Current | None:
    """La version actuelle de ``dependency``, à soumettre à OSV ; ``None`` si on ne la connaît
    pas, ou si les versions de son écosystème ne sont pas encore gérées."""
    try:
        current = current_version(dependency)
    except LookupError:
        return None
    return current if current.version is not None else None


def check(dependency: Dependency, current: Current, found: Vulnerabilities) -> list[Finding]:
    """Les failles de ``dependency`` en version ``current``, d'après ce qu'OSV en dit
    (``found``) : un constat par faille, les plus graves d'abord (gravité, puis score CVSS).
    Une liste vide s'il n'y en a pas."""
    findings = [_finding(dependency, current, group) for group in _groups(found.advisories)]
    return sorted(findings, key=lambda f: (-f.severity.rank, -(f.cvss_score or 0), f.identifiers))


def unchecked(dependency: Dependency, current: Current, error: OsvError) -> Finding:
    """Le constat « non concluant » de ``dependency`` quand OSV n'a pas pu dire quelles failles
    concernent sa version."""
    return Finding(
        kind=FindingKind.INCONCLUSIVE,
        message=f"Failles non vérifiées. {error}",
        dependency=dependency,
        current_version=current.version,
        current_is_approximate=current.approximate,
    )


def _groups(advisories: Sequence[Advisory]) -> list[list[Advisory]]:
    """Les avis réunis par faille : ceux qui partagent un identifiant (le leur, ou un alias),
    de proche en proche ; et tous ceux d'un paquet malveillant ensemble. Les avis retirés
    sont écartés."""
    groups: list[tuple[set[str], list[Advisory]]] = []
    malicious = []
    for advisory in advisories:
        if advisory.withdrawn:
            continue
        if advisory.malicious:
            malicious.append(advisory)
            continue
        names = {advisory.id, *advisory.aliases}
        members = [advisory]
        kept = []
        for group_names, group in groups:
            if group_names & names:
                names |= group_names
                members = group + members
            else:
                kept.append((group_names, group))
        groups = [*kept, (names, members)]
    found = [group for _, group in groups]
    if malicious:
        found.append(malicious)
    return found


def _finding(dependency: Dependency, current: Current, group: list[Advisory]) -> Finding:
    assert current.version is not None
    scheme = versions.for_ecosystem(dependency.ecosystem)
    known = [advisory for advisory in group if advisory.unavailable is None]
    identifiers = _identifiers(group)
    shown = ", ".join([i for i in identifiers if i.startswith(_PREFIXES)] or identifiers[:1])
    malicious = any(advisory.malicious for advisory in group)
    severities = [a.severity for a in known if a.severity is not None]
    score = max((a.score for a in known if a.score is not None), default=None)
    if malicious:
        severity = Severity.CRITICAL
    elif severities:
        severity = max(severities, key=lambda s: s.rank)
    else:
        severity = Severity.MEDIUM
    fixes = [
        fix
        for advisory in known
        if (fix := advisory.fixed_in(dependency.ecosystem, dependency.name, current.version))
    ]
    target = max(fixes, key=scheme.sort_key) if fixes else None
    main = min(group, key=_main_order)
    summary = next((a.summary for a in sorted(group, key=_main_order) if a.summary), "")

    if not known:
        reasons = "; ".join(dict.fromkeys(a.unavailable or "" for a in group))
        message = (
            f"{shown} : détail de l'avis indisponible ({reasons}) ; gravité et version corrigée "
            "inconnues."
        )
    else:
        if malicious:
            head = f"Code malveillant ({shown})"
        elif severities:
            cvss = "" if score is None else f", CVSS {score:.1f}".replace(".", ",")
            head = f"{shown} (gravité {SEVERITY_LABELS[severity]}{cvss})"
        else:
            head = f"{shown} (gravité inconnue)"
        message = sentence(f"{head} : {summary}" if summary else head)
        if target is not None:
            message += f" Corrigée en {target}."
        elif malicious:
            message += " Retirer ce paquet : aucune version sûre connue."
        else:
            message += " Aucune version corrigée connue."
    if current.approximate:
        message += (
            f" Faille possible : {current.version} est la borne basse de « "
            f"{dependency.effective_constraint} », faute de lockfile ; la version installée peut "
            "être plus récente."
        )
    return Finding(
        kind=FindingKind.VULNERABLE,
        severity=severity,
        message=message,
        dependency=dependency,
        current_version=current.version,
        current_is_approximate=current.approximate,
        target_version=target,
        gap=None if target is None else scheme.gap(current.version, target),
        identifiers=identifiers,
        cvss_score=score,
        detail=summary or None,
        url=main.url,
    )


def _identifiers(group: list[Advisory]) -> tuple[str, ...]:
    """Les identifiants des avis et leurs alias, sans doublon : les CVE, puis les GHSA, puis
    les autres, chacun dans l'ordre alphabétique."""
    found = {name for advisory in group for name in (advisory.id, *advisory.aliases)}

    def order(name: str) -> tuple[int, str]:
        rank = next((i for i, p in enumerate(_PREFIXES) if name.startswith(p)), len(_PREFIXES))
        return rank, name

    return tuple(sorted(found, key=order))


def _main_order(advisory: Advisory) -> tuple[bool, bool, bool, str]:
    """L'avis qui représente la faille (son lien, son titre) : un avis lu, de GitHub de
    préférence (ils ont un titre), avec un titre."""
    return (
        advisory.unavailable is not None,
        not advisory.id.startswith("GHSA-"),
        not advisory.summary,
        advisory.id,
    )
