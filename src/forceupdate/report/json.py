"""Le rapport en JSON : ``forceupdate scan --format json``, et le format de l'API (E12).

Le schéma est décrit dans ``docs/JSON_FORMAT.md``. Il porte un numéro (``schema_version``) :
un changement qui casse un lecteur (champ retiré, renommé, ou de sens changé) le fait passer
à 2 ; un champ ajouté, non.

Le texte est de l'UTF-8 sans échappement des accents (``ensure_ascii=False``) : c'est à qui
l'écrit de le faire en UTF-8, sur la sortie standard comme dans un fichier.

``Document`` décrit ce que rend ``build``, champ par champ : l'API s'en sert pour son schéma
OpenAPI, d'où viennent les types du front.
"""

import json
from dataclasses import dataclass
from typing import Any

from forceupdate import __version__
from forceupdate.models import Report, to_dict
from forceupdate.report import Summary, summarize

SCHEMA_VERSION = 1


@dataclass(frozen=True, kw_only=True)
class Tool:
    """L'outil qui a fait le rapport."""

    name: str
    version: str


@dataclass(frozen=True, kw_only=True)
class SummaryDocument(Summary):
    """Le résumé, avec ``to_update`` (une propriété de ``Summary``)."""

    to_update: int = 0


@dataclass(kw_only=True)
class Document(Report):
    """Le rapport tel que le rend ``build`` : ``schema_version``, ``tool``, tous les champs de
    ``Report``, puis ``summary``. Il ne sert qu'à décrire le JSON."""

    schema_version: int
    tool: Tool
    summary: SummaryDocument


def build(report: Report) -> dict[str, Any]:
    """Le rapport en types simples, prêt pour ``json.dumps`` (ou une réponse de l'API) ; sa
    forme est ``Document``."""
    summary = summarize(report)
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "forceupdate", "version": __version__},
        **to_dict(report),
        "summary": {**to_dict(summary), "to_update": summary.to_update},
    }


def render(report: Report) -> str:
    """Le rapport en JSON, indenté, terminé par un saut de ligne."""
    return json.dumps(build(report), ensure_ascii=False, indent=2) + "\n"
