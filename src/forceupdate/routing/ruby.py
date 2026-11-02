"""La source globale d'un ``Gemfile`` (E33) : ``source "https://gems.corp.example"`` hors d'un bloc.

Un bloc ``source "…" do`` vers un autre serveur que rubygems.org rend déjà ses gems « non
vérifiables » (``parsers.ruby``) ; une source globale ne l'était pas : ses gems étaient demandées à
rubygems.org, où une gem privée peut avoir un homonyme. Tant que forceupdate ne lit pas ce serveur
(son index compact, avec les identifiants de Bundler : ajouté au plan, E34), les gems d'un
``Gemfile`` dont la source globale n'est pas rubygems.org sont « non vérifiées », sans être privées
par leur nom (un miroir sert les gems publiques : leurs failles sont cherchées).
"""

import posixpath
import re
from urllib.parse import urlsplit

from forceupdate.models import Dependency, Project
from forceupdate.parsers.base import ReadText
from forceupdate.parsers.ruby import is_rubygems
from forceupdate.routing import Reading, Route, Router, User

_GLOBAL_SOURCE = re.compile(
    r"""^\s*source\s*\(?\s*(['"])(?P<url>[^'"]+)\1\s*\)?\s*(?:#.*)?$""", re.MULTILINE
)
"""Une ligne ``source "…"`` seule (un bloc finit par ``do`` ou ``{``)."""
GEMFILES = ("Gemfile", "gems.rb")


def read(project: Project, read_text: ReadText, user: User) -> Reading | None:
    """Les gems d'un ``Gemfile`` dont la source globale n'est pas rubygems.org : non vérifiées."""
    for manifest in project.manifests:
        if posixpath.basename(manifest) not in GEMFILES:
            continue
        try:
            text = read_text(manifest)
        except ValueError:
            text = None
        found = [m.group("url") for m in _GLOBAL_SOURCE.finditer(text or "")]
        others = [url for url in found if not is_rubygems(url)]
        if others:
            return Reading(router=_router(manifest, others[0]))
    return None


def _router(manifest: str, url: str) -> Router:
    host = (urlsplit(url).hostname or "?").lower()

    def route(dependency: Dependency) -> Route:
        return Route(
            public=False,
            unchecked=(
                f"Non vérifié : la source de {manifest} est {host}, pas rubygems.org ; forceupdate "
                "ne lit pas encore ce serveur, et ne demande pas rubygems.org à sa place"
            ),
        )

    return route
