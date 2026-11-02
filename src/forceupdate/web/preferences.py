"""Les réglages de la personne, côté serveur (E29) : lus au démarrage, réécrits par l'écran
Réglages (``PUT /api/settings``), ils valent pour les analyses, les plans et les PR qui suivent.

Le fichier est celui de la ligne de commande (``preferences.default_path``) : un réglage fait
dans l'interface vaut aussi pour ``forceupdate scan`` et ``update``. Le délai du clone est celui
du module ``forges.git`` (``CLONE_TIMEOUT``), remis comme avant à l'arrêt du serveur.
"""

import logging
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from forceupdate import preferences
from forceupdate.config import ECOSYSTEM_KEYS, Problem
from forceupdate.forges import git
from forceupdate.preferences import Preferences
from forceupdate.update import lockfiles
from forceupdate.web import schemas

logger = logging.getLogger(__name__)


class UserPreferences:
    """Les réglages de la session. À créer et à fermer dans la boucle du serveur."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or preferences.default_path()
        self.current, self.problems = preferences.load(self.path)
        for problem in self.problems:
            logger.warning("réglages : %s", problem)
        self._clone_timeout = git.CLONE_TIMEOUT
        self._apply()

    @property
    def tools(self) -> lockfiles.Tools:
        """Comment lancer les outils de lockfile."""
        return lockfiles.Tools(
            timeout=float(self.current.lock_timeout),
            rust_default_toolchain=self.current.rust_default_toolchain,
        )

    def save(self, value: Preferences) -> None:
        """Enregistre ``value`` (lève ``OSError``), et l'applique."""
        preferences.save(value, self.path)
        self.current, self.problems = value, []
        self._apply()

    def close(self) -> None:
        git.CLONE_TIMEOUT = self._clone_timeout

    def _apply(self) -> None:
        git.CLONE_TIMEOUT = float(self.current.clone_timeout)


def from_request(body: schemas.SettingsRequest) -> tuple[Preferences, list[schemas.FieldError]]:
    """Les réglages demandés, vérifiés comme ceux du fichier (``preferences.from_table``) ; les
    valeurs refusées, champ par champ."""
    table: dict[str, Any] = {
        "ignore": list(body.ignore),
        "include-tests": body.include_tests,
        "excluded-repositories": list(body.excluded_repositories),
        "lock-timeout": body.lock_timeout,
        "clone-timeout": body.clone_timeout,
        "rust-default-toolchain": body.rust_default_toolchain,
        "selection": _selection_table(body.selection),
    }
    value, problems = preferences.from_table(table)
    return value, [_field_error(problem) for problem in problems]


def _selection_table(rules: Iterable[schemas.SelectionInput]) -> Mapping[str, Any]:
    table: dict[str, Any] = {}
    for rule in rules:
        target = (
            table
            if rule.ecosystem is None
            else table.setdefault(ECOSYSTEM_KEYS[rule.ecosystem], {})
        )
        if rule.level is not None:
            target["level"] = rule.level.value
        if rule.security_only is not None:
            target["security-only"] = rule.security_only
    return table


def _field_error(problem: Problem) -> schemas.FieldError:
    """``ignore[2]`` → le champ ``ignore``, rang 2 ; ``lock-timeout`` → ``lock_timeout`` ;
    ``selection.npm.level`` → ``selection``."""
    name, _, rest = problem.field.partition("[")
    index = int(rest.rstrip("]")) if rest.rstrip("]").isdigit() else None
    name = name.split(".")[0].replace("-", "_")
    return schemas.FieldError(field=name, index=index, message=problem.message)


def document(store: UserPreferences, cache: schemas.CacheState) -> schemas.SettingsDocument:
    return schemas.SettingsDocument(
        values=store.current,
        defaults=preferences.DEFAULTS,
        file=store.path.as_posix(),
        problems=tuple(store.problems),
        cache=cache,
    )
