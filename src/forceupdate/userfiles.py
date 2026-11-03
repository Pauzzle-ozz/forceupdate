"""Les fichiers de configuration de la personne et son environnement, tels que ses outils les lisent
(E33) : ``~/.npmrc``, le fichier ``GOENV`` de Go, ``auth.json`` de Composer, ``~/.m2/settings.xml``,
le ``NuGet.Config`` de son profil, ``pip.ini``, ``uv.toml``, ``.netrc``.

Tout passe par ici : ``home``, ``config_home`` et ``environ`` décident de l'endroit où chercher, et
``read`` lit. Les tests remplacent les trois premiers (``tests/conftest.py`` : ``user_files``) :
aucun ne lit jamais les fichiers de la personne.

Les dossiers, comme les outils les cherchent (vérifié le 2026-11-02 sous Windows) :

- ``config_home`` : ``%APPDATA%`` sous Windows (``go env GOENV`` : ``%APPDATA%\\go\\env`` ; NuGet,
  Composer, pip et uv y rangent aussi les leurs), ``~/Library/Application Support`` sous macOS,
  ``$XDG_CONFIG_HOME`` (ou ``~/.config``) ailleurs : le ``os.UserConfigDir`` de Go ;
- ``home`` : le dossier personnel (``~/.npmrc``, ``~/.m2``, ``~/.netrc``).
"""

import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path

from forceupdate.detect.manifests import safe_read_text

MAX_SIZE = 1_000_000
"""Taille maximale d'un fichier de configuration lu, en octets."""

_SHELL = re.compile(r"\$\{([A-Za-z_.][A-Za-z0-9_.]*)\??\}")
_WINDOWS = re.compile(r"%([A-Za-z_][A-Za-z0-9_]*)%")


def _home() -> Path:
    return Path.home()


def _environ() -> Mapping[str, str]:
    return os.environ


def home() -> Path:
    """Le dossier personnel."""
    return _home()


def tilde(text: str) -> str:
    """``text`` avec le dossier personnel écrit ``~`` : la sortie d'un outil (npm, git) qui va à
    l'écran ou dans la description d'une PR ne dit pas le nom de la personne (session 36)."""
    folder = home()
    flags = re.IGNORECASE if sys.platform == "win32" else 0
    for spelled in dict.fromkeys((str(folder), folder.as_posix())):
        if len(spelled) > 3:  # jamais une racine (« C:\ », « / »)
            text = re.sub(re.escape(spelled), "~", text, flags=flags)
    return text


def environ() -> Mapping[str, str]:
    """L'environnement de la personne (``GOPRIVATE``, ``COMPOSER_AUTH``, ``PIP_INDEX_URL``…)."""
    return _environ()


def env(name: str) -> str | None:
    """La variable ``name`` de l'environnement ; ``None`` si elle manque ou est vide."""
    return environ().get(name) or None


def config_home() -> Path:
    """Le dossier de configuration des outils (``os.UserConfigDir`` de Go, voir plus haut)."""
    if sys.platform == "win32":
        appdata = env("APPDATA")
        return Path(appdata) if appdata else home() / "AppData" / "Roaming"
    if sys.platform == "darwin":
        return home() / "Library" / "Application Support"
    xdg = env("XDG_CONFIG_HOME")
    return Path(xdg) if xdg else home() / ".config"


def xdg_config_home() -> Path:
    """``$XDG_CONFIG_HOME``, sinon ``~/.config`` : là où uv et pip cherchent aussi sous macOS."""
    xdg = env("XDG_CONFIG_HOME")
    return Path(xdg) if xdg else home() / ".config"


def read(path: Path) -> str | None:
    """Le texte du fichier ``path`` ; ``None`` s'il manque, est illisible ou trop gros."""
    if not path.is_file():
        return None
    return safe_read_text(path, max_size=MAX_SIZE)


def expand(value: str, style: str = "shell") -> str | None:
    """``value`` avec ses variables d'environnement remplacées : ``${NOM}`` (``style="shell"``,
    celui de npm, de pip, de Maven : ``${env.NOM}``) ou ``%NOM%`` (``style="windows"``, NuGet).
    ``None`` si une variable manque : la valeur n'est pas utilisable. Seulement pour un fichier de
    la personne : celles d'un fichier du projet ne sont jamais développées (``unexpanded``)."""
    pattern = _WINDOWS if style == "windows" else _SHELL
    missing = False

    def replace(match: re.Match[str]) -> str:
        nonlocal missing
        name = match.group(1).removeprefix("env.")
        found = env(name)
        if found is None:
            missing = True
            return ""
        return found

    expanded = pattern.sub(replace, value)
    return None if missing else expanded


def unexpanded(value: str) -> bool:
    """Vrai si ``value`` contient une variable (``${NOM}``, ``%NOM%``) : venue d'un fichier du
    projet, elle n'est jamais développée (un dépôt pourrait faire partir un secret de
    l'environnement vers l'adresse de son choix), et la valeur n'est pas utilisable."""
    return bool(_SHELL.search(value) or _WINDOWS.search(value))
