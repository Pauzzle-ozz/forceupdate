"""Les identifiants des registres privés (E33), chacun lié à l'adresse pour laquelle il est déclaré.

Décidé avec l'utilisateur (session 33) : forceupdate lit les identifiants dans les fichiers de la
personne (``~/.npmrc``, ``auth.json``, ``settings.xml``, ``NuGet.Config``, ``.netrc``…), comme
son outil le ferait, et :

- un identifiant ne part que vers l'hôte (et le port, et le chemin, quand ils sont dits) pour
  lequel il est déclaré, en https, ou en http vers la machine elle-même (``localhost``,
  ``127.0.0.1``, ``::1`` : rien ne quitte la machine) ;
- une redirection vers une autre origine part sans lui (``HttpClient``) ;
- il n'est jamais écrit dans le cache (la clé est l'adresse, qui n'en contient pas : les
  identifiants d'une adresse ``https://nom:secret@hôte`` en sont retirés, ``split_userinfo``),
  ni dans un rapport, un journal, l'API ou le navigateur : ``repr`` le masque, les messages
  citent l'hôte ;
- un identifiant rattaché à un *nom* (``<server id>`` de Maven, une source de NuGet) n'est lié qu'à
  l'adresse que donne pour ce nom un fichier de la personne : jamais à celle qu'un fichier du
  projet donnerait au même nom ;
- les variables (``${NOM}``, ``%NOM%``) d'un fichier du projet ne sont jamais développées
  (``userfiles.unexpanded``).
"""

import base64
import ipaddress
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from urllib.parse import SplitResult, unquote, urlsplit, urlunsplit

LOOPBACK_NAMES = frozenset({"localhost"})


def is_loopback(host: str) -> bool:
    """Vrai pour la machine elle-même (``localhost``, ``127.0.0.1``, ``::1``)."""
    host = host.strip("[]").lower()
    if host in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def origin(url: str) -> tuple[str, str, int | None] | None:
    """L'origine de ``url`` (schéma, hôte en minuscules, port) ; ``None`` si ce n'est pas une
    adresse http(s). Le port par défaut du schéma est écrit."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not parts.hostname:
        return None
    return scheme, parts.hostname.lower(), port or (443 if scheme == "https" else 80)


def may_carry_secret(url: str) -> bool:
    """Vrai si un identifiant peut partir vers ``url`` : en https, ou en http vers la machine
    elle-même."""
    found = origin(url)
    if found is None:
        return False
    scheme, host, _ = found
    return scheme == "https" or is_loopback(host)


@dataclass(frozen=True, kw_only=True, repr=False)
class Credential:
    """Un identifiant, et l'adresse à laquelle il est lié : ``host``, ``port`` (``None`` : celui
    du schéma, 443 ou 80 ; ``any_port`` : tous, comme ``.netrc``, qui n'en dit pas), ``path`` (un
    préfixe du chemin, terminé par ``/``), ``scheme`` (``None`` : https, ou http vers la machine
    elle-même)."""

    host: str
    port: int | None = None
    any_port: bool = False
    path: str = "/"
    scheme: str | None = None
    header: str = "Authorization"
    value: str
    """Le secret, déjà mis en forme pour l'en-tête (``Bearer …``, ``Basic …``)."""
    source: str
    """D'où il vient, pour les remarques (``~/.npmrc``) : jamais le secret."""

    def __repr__(self) -> str:
        port = f":{self.port}" if self.port else ""
        return f"Credential({self.host}{port}{self.path}, {self.source})"

    def matches(self, url: str) -> bool:
        """Vrai si l'identifiant peut partir vers ``url`` (voir la docstring du module)."""
        found = origin(url)
        if found is None or not may_carry_secret(url):
            return False
        scheme, host, port = found
        if self.scheme is not None and scheme != self.scheme:
            return False
        if host != self.host:
            return False
        if not self.any_port and port != (self.port or (443 if scheme == "https" else 80)):
            return False
        path = urlsplit(url).path or "/"
        return (path if path.endswith("/") else f"{path}/").startswith(self.path)

    def headers(self) -> dict[str, str]:
        return {self.header: self.value}


def bound_to(
    url: str,
    *,
    value: str,
    source: str,
    header: str = "Authorization",
    with_scheme: bool = True,
) -> Credential:
    """Un identifiant lié à l'adresse ``url`` : son hôte, son port s'il est écrit, son chemin, et
    son schéma (sauf ``with_scheme=False`` : une adresse sans schéma, comme celles des
    identifiants de npm). Lève ``ValueError`` si ce n'est pas une adresse http(s)."""
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        raise ValueError("port illisible") from None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError("adresse http(s) attendue")
    path = parts.path or "/"
    return Credential(
        host=parts.hostname.lower(),
        port=port,
        path=path if path.endswith("/") else f"{path}/",
        scheme=parts.scheme.lower() if with_scheme else None,
        header=header,
        value=value,
        source=source,
    )


def bound_or_none(
    url: str, *, value: str, source: str, header: str = "Authorization", with_scheme: bool = True
) -> Credential | None:
    """``bound_to``, ou ``None`` si ``url`` n'est pas une adresse http(s) lisible."""
    try:
        return bound_to(url, value=value, source=source, header=header, with_scheme=with_scheme)
    except ValueError:
        return None


def bearer(token: str) -> str:
    return f"Bearer {token}"


def basic(username: str, password: str) -> str:
    pair = f"{username}:{password}".encode()
    return f"Basic {base64.b64encode(pair).decode('ascii')}"


def split_userinfo(url: str) -> tuple[str, tuple[str, str] | None]:
    """``url`` sans les identifiants qu'elle porte (``https://nom:secret@hôte/…``), et ceux-ci
    (décodés) ; ``None`` s'il n'y en a pas. L'adresse rendue est celle du cache et des messages."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url, None
    if "@" not in parts.netloc:
        return url, None
    userinfo, _, hostport = parts.netloc.rpartition("@")
    username, _, password = userinfo.partition(":")
    clean = urlunsplit(SplitResult(parts.scheme, hostport, parts.path, parts.query, ""))
    return clean, (unquote(username), unquote(password))


class Credentials:
    """Les identifiants d'une analyse : ``for_url`` donne celui qui peut partir vers une adresse
    (le plus précis, s'il y en a plusieurs), ou ``None``."""

    def __init__(self, items: Iterable[Credential] = ()) -> None:
        self._items: list[Credential] = []
        for item in items:
            self.add(item)

    def add(self, credential: Credential) -> None:
        """Ajoute ``credential`` ; un autre pour la même adresse, déjà là, garde la priorité."""
        same = (credential.host, credential.port, credential.path, credential.scheme)
        if not any((i.host, i.port, i.path, i.scheme) == same for i in self._items):
            self._items.append(credential)

    def for_url(self, url: str) -> Credential | None:
        matching = [item for item in self._items if item.matches(url)]
        if not matching:
            return None
        return max(matching, key=lambda item: (len(item.path), item.port is not None))

    def __iter__(self) -> Iterator[Credential]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:
        return f"Credentials({len(self._items)})"
