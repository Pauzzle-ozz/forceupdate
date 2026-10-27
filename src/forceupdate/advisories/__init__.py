"""Les avis de sécurité : les failles connues d'une version de paquet (type 2 du brief).

- ``osv.py`` : le client d'OSV (``Osv``), et ``Advisory``, un avis réduit à ce qui sert,
  avec la version qui corrige la faille (``Advisory.fixed_in``) ;
- ``cvss.py`` : le score CVSS 3 d'un vecteur, et la gravité qui va avec.

Les constats qu'on en tire sont dans ``checks/vulns.py``, qui ne parle pas au réseau.
"""

from forceupdate.advisories.osv import (
    Advisory,
    Affected,
    AffectedRange,
    Osv,
    OsvError,
    Query,
    Vulnerabilities,
    parse_vuln,
)

__all__ = [
    "Advisory",
    "Affected",
    "AffectedRange",
    "Osv",
    "OsvError",
    "Query",
    "Vulnerabilities",
    "parse_vuln",
]
