"""Les réglages de la personne (E29) : ce qui vaut pour toutes ses analyses. Ils sont rangés dans
``forceupdate.toml``, dans son dossier de configuration (``platformdirs`` :
``%LOCALAPPDATA%\\forceupdate`` sous Windows, ``~/.config/forceupdate`` sous Linux), comme uv le
fait de ``uv.toml``. L'écran Réglages les écrit ; la ligne de commande et l'interface les lisent.

Les clés de la configuration d'un projet (``config`` : ``ignore``, ``include-tests``,
``[selection]``), sauf ``exclude`` ; la configuration d'un projet prime sur elles. En plus :

- ``excluded-repositories`` : des dépôts des forges (``github.com/owner/repo``, ``*`` permis :
  ``gitlab.com/groupe/*``), masqués comme un dépôt archivé, jamais analysés avec les autres ni
  proposés pour une PR ;
- ``lock-timeout`` : le délai de chaque commande d'un outil de lockfile, en secondes (600) ;
- ``clone-timeout`` : le délai d'un clone, d'un fetch ou d'un push, en secondes (600) ;
- ``rust-default-toolchain`` : lancer cargo avec la chaîne d'outils par défaut de la personne
  (``RUSTUP_TOOLCHAIN``) plutôt que celle du ``rust-toolchain.toml`` du projet, que rustup
  installerait.

Le fichier est réécrit en entier à chaque enregistrement (ses commentaires ne sont pas gardés).
Illisible, ou une valeur fausse : les valeurs par défaut à sa place, et la raison
(``load``). Jamais lu ni écrit par les tests (``tests/conftest.py`` : ``default_path``).
"""

import json
import logging
import os
import tempfile
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

import platformdirs

from forceupdate.config import ECOSYSTEM_KEYS, PROJECT_KEYS, Problem, read_table
from forceupdate.models import Gap, SelectionRule

logger = logging.getLogger(__name__)

FILE_NAME = "forceupdate.toml"

DEFAULT_TIMEOUT = 600
"""Le délai par défaut des outils de lockfile et de git, en secondes."""
MIN_TIMEOUT = 10
MAX_TIMEOUT = 24 * 3600

KEYS = (PROJECT_KEYS - {"exclude"}) | {
    "excluded-repositories",
    "lock-timeout",
    "clone-timeout",
    "rust-default-toolchain",
}


@dataclass(frozen=True, kw_only=True)
class Preferences:
    """Les réglages de la personne ; les valeurs par défaut sont celles de forceupdate."""

    ignore: tuple[str, ...] = ()
    """Paquets (``lodash``) et versions (``django@>=5``) ignorés, voir ``config``."""
    include_tests: bool = False
    """Analyser aussi les projets des dossiers de tests et d'exemples (l'option d'analyse
    cochée d'office)."""
    selection: tuple[SelectionRule, ...] = ()
    """La sélection par défaut, pour tous les écosystèmes ou pour un seul."""
    excluded_repositories: tuple[str, ...] = ()
    """Dépôts des forges exclus : ``hôte/propriétaire/nom``, ``*`` permis."""
    lock_timeout: int = DEFAULT_TIMEOUT
    clone_timeout: int = DEFAULT_TIMEOUT
    rust_default_toolchain: bool = False

    def excludes(self, host: str, full_name: str) -> bool:
        """Vrai si le dépôt ``full_name`` de ``host`` est exclu (sans tenir compte de la
        casse)."""
        name = f"{host}/{full_name}".lower()
        return any(fnmatchcase(name, pattern.lower()) for pattern in self.excluded_repositories)


DEFAULTS = Preferences()


def default_path() -> Path:
    """Le fichier des réglages : ``%LOCALAPPDATA%\\forceupdate\\forceupdate.toml`` sous Windows,
    ``~/.config/forceupdate/forceupdate.toml`` sous Linux. Les tests le remplacent."""
    return platformdirs.user_config_path("forceupdate", appauthor=False) / FILE_NAME


def load(path: Path | None = None) -> tuple[Preferences, list[str]]:
    """Les réglages lus dans ``path`` (par défaut ``default_path()``), et ce qui n'a pas pu être
    lu (une phrase chacun) ; sans fichier, les valeurs par défaut."""
    path = path or default_path()
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return DEFAULTS, []
    except (OSError, UnicodeDecodeError) as err:
        logger.warning("réglages illisibles (%s) : %s", path, err)
        return DEFAULTS, [f"{path} : illisible ({err}) : valeurs par défaut."]
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as err:
        return DEFAULTS, [f"{path} : TOML invalide ({err}) : valeurs par défaut."]
    preferences, problems = from_table(data)
    return preferences, [problem.text(path.name) for problem in problems]


def from_table(data: Mapping[str, Any]) -> tuple[Preferences, list[Problem]]:
    """Les réglages d'une table TOML (ou du JSON de l'API, mêmes clés) ; une valeur fausse est
    écartée (valeur par défaut), avec un ``Problem``."""
    found, problems = read_table(data, KEYS)
    repositories: list[str] = []
    raw = found.get("excluded-repositories", [])
    if not isinstance(raw, list):
        problems.append(Problem("excluded-repositories", "une liste de chaînes est attendue."))
        raw = []
    for index, item in enumerate(raw):
        field = f"excluded-repositories[{index}]"
        try:
            repositories.append(repository_pattern(item))
        except ValueError as err:
            problems.append(Problem(field, str(err)))
    timeouts = {}
    for key in ("lock-timeout", "clone-timeout"):
        value = found.get(key, DEFAULT_TIMEOUT)
        if isinstance(value, bool) or not isinstance(value, int):
            problems.append(
                Problem(key, f"« {value!r} » : un nombre entier de secondes est attendu.")
            )
            value = DEFAULT_TIMEOUT
        elif not MIN_TIMEOUT <= value <= MAX_TIMEOUT:
            message = f"{value} s : entre {MIN_TIMEOUT} et {MAX_TIMEOUT} secondes."
            problems.append(Problem(key, message))
            value = DEFAULT_TIMEOUT
        timeouts[key] = value
    toolchain = found.get("rust-default-toolchain", False)
    if not isinstance(toolchain, bool):
        problems.append(
            Problem("rust-default-toolchain", f"« {toolchain!r} » n'est pas true ou false.")
        )
        toolchain = False
    # Une règle générale qui dit les valeurs par défaut n'en est pas une : sans elle, un rapport
    # ne dirait pas « sélection par défaut réglée » pour rien.
    selection = tuple(
        rule
        for rule in found.get("selection", ())
        if rule.ecosystem is not None
        or rule.level not in (None, Gap.MINOR)
        or rule.security_only is True
    )
    preferences = Preferences(
        ignore=found.get("ignore", ()),
        include_tests=found.get("include-tests", False),
        selection=selection,
        excluded_repositories=tuple(repositories),
        lock_timeout=timeouts["lock-timeout"],
        clone_timeout=timeouts["clone-timeout"],
        rust_default_toolchain=toolchain,
    )
    return preferences, problems


def repository_pattern(value: Any) -> str:
    """Le motif d'un dépôt exclu : ``hôte/propriétaire/nom`` (``github.com/owner/repo``), ``*``
    et ``?`` permis ; lève ``ValueError`` (en français)."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("une chaîne non vide est attendue (github.com/propriétaire/dépôt).")
    pattern = value.strip().removeprefix("https://").removeprefix("http://").strip("/")
    pattern = pattern.removesuffix(".git")
    if any(char.isspace() for char in pattern) or pattern.count("/") < 2:
        raise ValueError(
            f"« {value} » : hôte, propriétaire et dépôt sont attendus (github.com/owner/repo, "
            "gitlab.com/groupe/*)."
        )
    return pattern


def save(preferences: Preferences, path: Path | None = None) -> Path:
    """Écrit ``preferences`` dans ``path`` (par défaut ``default_path()``), d'un coup : un
    fichier temporaire, puis ``os.replace``. Lève ``OSError``."""
    path = path or default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".forceupdate-", suffix=".toml")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as file:
            file.write(to_toml(preferences))
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return path


def to_toml(preferences: Preferences) -> str:
    """Les réglages en TOML, dans l'ordre de l'écran Réglages ; une chaîne s'écrit comme en
    JSON, ce qui est une chaîne TOML valide."""
    general = next((rule for rule in preferences.selection if rule.ecosystem is None), None)
    lines = [
        "# Réglages de forceupdate, écrits par l'écran Réglages (forceupdate ui).",
        "# Une configuration de projet (forceupdate.toml, [tool.forceupdate]) prime sur eux.",
        "",
        f"ignore = {_list(preferences.ignore)}",
        f"include-tests = {_bool(preferences.include_tests)}",
        f"excluded-repositories = {_list(preferences.excluded_repositories)}",
        f"lock-timeout = {preferences.lock_timeout}",
        f"clone-timeout = {preferences.clone_timeout}",
        f"rust-default-toolchain = {_bool(preferences.rust_default_toolchain)}",
        "",
        "[selection]",
        *_rule_lines(general),
    ]
    for rule in preferences.selection:
        if rule.ecosystem is not None:
            lines += ["", f"[selection.{ECOSYSTEM_KEYS[rule.ecosystem]}]", *_rule_lines(rule)]
    return "\n".join(lines) + "\n"


def _rule_lines(rule: SelectionRule | None) -> list[str]:
    if rule is None:
        return []
    lines = []
    if rule.level is not None:
        lines.append(f"level = {_string(rule.level.value)}")
    if rule.security_only is not None:
        lines.append(f"security-only = {_bool(rule.security_only)}")
    return lines


def _list(values: tuple[str, ...]) -> str:
    return "[" + ", ".join(_string(value) for value in values) + "]"


def _string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _bool(value: bool) -> str:
    return "true" if value else "false"
