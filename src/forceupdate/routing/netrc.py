"""Les identifiants de ``.netrc`` (E33) : ceux que lisent ``go`` (``GOAUTH=netrc``), pip et uv.

Le fichier : ``NETRC``, sinon ``~/.netrc`` (sous Windows, ``~/_netrc`` aussi, celui de Go et de
curl). Chaque ``machine`` donne un identifiant lié à cet hôte (en https, ou en http vers la
machine elle-même), quel que soit le port, comme pip, uv et Go ;
``default`` n'est pas lu (il vaudrait pour tous les hôtes).
"""

import shlex
import sys
from pathlib import Path

from forceupdate import userfiles
from forceupdate.net.auth import Credential, basic
from forceupdate.routing import User

SOURCE = "~/.netrc"


def netrc_path() -> Path | None:
    """Le fichier ``.netrc`` de la personne ; ``None`` s'il n'y en a pas."""
    configured = userfiles.env("NETRC")
    candidates = [Path(configured)] if configured else [userfiles.home() / ".netrc"]
    if not configured and sys.platform == "win32":
        candidates.append(userfiles.home() / "_netrc")
    return next((path for path in candidates if path.is_file()), None)


def parse_netrc(text: str) -> list[tuple[str, str, str]]:
    """Les ``machine`` d'un ``.netrc`` : (hôte, nom, mot de passe), la première de chaque hôte.
    Des mots séparés par des blancs, entre guillemets s'ils en contiennent ; ``#`` en début de ligne
    commente ; ``macdef`` va jusqu'à la ligne vide ; ``default`` n'est pas gardé."""
    words: list[str] = []
    in_macro = False
    for line in text.splitlines():
        if in_macro:
            in_macro = bool(line.strip())
            continue
        if line.lstrip().startswith("#"):
            continue
        try:
            tokens = shlex.split(line, posix=True)
        except ValueError:  # un guillemet non fermé
            tokens = line.split()
        if "macdef" in tokens:
            words += tokens[: tokens.index("macdef")]
            in_macro = True
            continue
        words += tokens
    found: dict[str, tuple[str, str]] = {}
    host: str | None = None
    entry: dict[str, str] = {}

    def close() -> None:
        if host is not None and entry.get("login") and entry.get("password"):
            found.setdefault(host.lower(), (entry["login"], entry["password"]))

    position = 0
    while position < len(words):
        word = words[position]
        if word in ("machine", "default"):
            close()
            entry = {}
            host = words[position + 1] if word == "machine" and position + 1 < len(words) else None
            position += 2 if word == "machine" else 1
        elif word in ("login", "password", "account") and position + 1 < len(words):
            entry[word] = words[position + 1]
            position += 2
        else:
            position += 1
    close()
    return [(host, login, password) for host, (login, password) in found.items()]


def netrc_credentials(user: User) -> list[Credential]:
    """Un identifiant par ``machine`` du ``.netrc`` de la personne."""

    def load() -> list[Credential]:
        path = netrc_path()
        text = userfiles.read(path) if path is not None else None
        if text is None:
            return []
        return [
            Credential(host=host, any_port=True, value=basic(login, password), source=SOURCE)
            for host, login, password in parse_netrc(text)
        ]

    return user.memo("netrc", load)
