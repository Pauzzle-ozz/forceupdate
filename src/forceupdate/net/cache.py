"""Le cache disque : ce que le réseau a répondu, gardé un temps qui dépend du type de donnée.

Un même paquet revient dans plusieurs projets, plusieurs dépôts et plusieurs analyses : il
n'est demandé qu'une fois par durée de vie. On y range des valeurs JSON déjà réduites (les
versions d'un paquet, pas le document de 30 Mo du registre).

Le cache est une base SQLite, dans le dossier de cache de l'utilisateur (``platformdirs``) :
un seul fichier, des écritures atomiques, et l'interface et la ligne de commande peuvent
s'en servir en même temps.

- **Sans cache** (``Cache.disabled()``) : rien n'est lu ni écrit.
- **Hors ligne** : une entrée périmée sert quand même (``stale_ok``). Mieux vaut une donnée
  datée, et dite datée (``CacheEntry.stored_at``), que rien.
- **Jetable** : un fichier illisible ou d'un autre format est vidé ; un disque où l'on ne
  peut pas écrire désactive le cache, avec un avertissement dans les logs. Le cache ne
  fait jamais échouer une analyse.
"""

import enum
import json
import logging
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import platformdirs

logger = logging.getLogger(__name__)

_SCHEMA = 1
"""Version du format de la base, dans ``PRAGMA user_version`` : une autre la fait vider."""
_KEEP = 30 * 24 * 3600.0
"""Les entrées plus vieilles que 30 jours sont effacées à l'ouverture, même hors ligne."""


class CacheKind(enum.StrEnum):
    """Un type de donnée du cache, avec sa durée de vie (``ttl``)."""

    VERSIONS = "versions"
    """Les versions d'un paquet et sa dépréciation : 1 h, une version peut sortir à tout moment."""
    VULNERABILITIES = "vulnerabilities"
    """Les failles connues d'une version d'un paquet (leurs identifiants, chez OSV) : 1 h, un
    avis peut être publié à tout moment."""
    ADVISORIES = "advisories"
    """Un avis de sécurité complet (OSV) : 7 jours. Il ne change pas sans que sa date de
    modification change, et on la vérifie à chaque fois."""

    @property
    def ttl(self) -> float:
        """Durée de vie d'une entrée, en secondes."""
        return _TTLS[self]


_TTLS = {
    CacheKind.VERSIONS: 3600.0,
    CacheKind.VULNERABILITIES: 3600.0,
    CacheKind.ADVISORIES: 7 * 24 * 3600.0,
}


@dataclass(frozen=True, kw_only=True)
class CacheEntry:
    """Une valeur lue dans le cache."""

    value: Any
    stored_at: datetime
    """Quand elle a été rangée (UTC) : la date des données."""
    fresh: bool
    """Faux pour une entrée périmée, rendue seulement parce que ``stale_ok`` le permettait."""


def default_cache_path() -> Path:
    """Le fichier du cache, dans le dossier de cache de l'utilisateur :
    ``%LOCALAPPDATA%\\forceupdate\\Cache`` sous Windows, ``~/.cache/forceupdate`` sous Linux."""
    return platformdirs.user_cache_path("forceupdate", appauthor=False) / "cache.sqlite3"


class Cache:
    """Le cache disque, rangé dans le fichier ``path`` (créé au besoin) ; ``None`` le désactive.

    Les clés sont des chaînes (l'URL interrogée, en général), les valeurs du JSON. Les
    méthodes sont synchrones et rapides (une requête SQLite), et sûres entre threads.
    ``clock`` sert aux tests.
    """

    def __init__(self, path: Path | None, *, clock: Callable[[], float] = time.time) -> None:
        self.path = path
        self._clock = clock
        self._lock = threading.Lock()
        self._db: sqlite3.Connection | None = None
        self._opened = path is None

    @classmethod
    def default(cls) -> "Cache":
        """Le cache de l'utilisateur, à ``default_cache_path()``."""
        return cls(default_cache_path())

    @classmethod
    def disabled(cls) -> "Cache":
        """Un cache qui ne lit ni n'écrit rien : l'option « sans cache »."""
        return cls(None)

    @property
    def enabled(self) -> bool:
        """Faux si le cache est désactivé, au départ ou après une erreur du disque."""
        with self._lock:
            return self._connection() is not None

    def get(self, kind: CacheKind, key: str, *, stale_ok: bool = False) -> CacheEntry | None:
        """L'entrée ``key`` de ``kind`` ; ``None`` si elle manque ou a dépassé sa durée de vie.

        ``stale_ok`` rend aussi une entrée périmée (mode hors ligne), avec ``fresh=False``.
        """
        with self._lock:
            row = self._execute(
                "SELECT stored_at, value FROM entries WHERE kind = ? AND key = ?", (kind, key)
            )
        if row is None:
            return None
        stored_at, text = row
        fresh = self._clock() - stored_at < kind.ttl
        if not fresh and not stale_ok:
            return None
        try:
            value = json.loads(text)
        except ValueError:
            return None
        return CacheEntry(
            value=value, stored_at=datetime.fromtimestamp(stored_at, UTC), fresh=fresh
        )

    def set(self, kind: CacheKind, key: str, value: Any) -> None:
        """Range ``value`` (du JSON) sous ``key``, à la place de l'ancienne entrée."""
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self._execute(
                "INSERT OR REPLACE INTO entries (kind, key, stored_at, value) VALUES (?, ?, ?, ?)",
                (kind, key, self._clock(), text),
                commit=True,
            )

    def clear(self) -> None:
        """Vide le cache."""
        with self._lock:
            self._execute("DELETE FROM entries", (), commit=True)

    def close(self) -> None:
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None

    # -- SQLite --------------------------------------------------------------

    def _execute(self, sql: str, params: tuple[Any, ...], *, commit: bool = False) -> Any:
        """Lance ``sql`` et rend la première ligne ; ``None`` si le cache est désactivé. Une
        erreur de SQLite désactive le cache pour la suite de la session."""
        db = self._connection()
        if db is None:
            return None
        try:
            row = db.execute(sql, params).fetchone()
            if commit:
                db.commit()
        except sqlite3.Error as error:
            self._disable(error)
            return None
        return row

    def _connection(self) -> sqlite3.Connection | None:
        if not self._opened:
            self._opened = True
            assert self.path is not None
            try:
                self._db = self._open(self.path)
            except sqlite3.DatabaseError:
                # Fichier abîmé, ou qui n'est pas une base : le cache est jetable.
                try:
                    self.path.unlink()
                    self._db = self._open(self.path)
                except (OSError, sqlite3.Error) as error:
                    self._disable(error)
            except (OSError, sqlite3.Error) as error:
                self._disable(error)
        return self._db

    def _open(self, path: Path) -> sqlite3.Connection:
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(path, timeout=5.0, check_same_thread=False)
        try:
            # WAL : les lectures d'un processus ne bloquent pas les écritures d'un autre.
            db.execute("PRAGMA journal_mode = WAL")
            (version,) = db.execute("PRAGMA user_version").fetchone()
            if version != _SCHEMA:
                db.execute("DROP TABLE IF EXISTS entries")
                db.execute(
                    "CREATE TABLE entries (kind TEXT NOT NULL, key TEXT NOT NULL,"
                    " stored_at REAL NOT NULL, value TEXT NOT NULL, PRIMARY KEY (kind, key))"
                )
                db.execute(f"PRAGMA user_version = {_SCHEMA}")
            db.execute("DELETE FROM entries WHERE stored_at < ?", (self._clock() - _KEEP,))
            db.commit()
        except BaseException:
            db.close()
            raise
        return db

    def _disable(self, error: BaseException) -> None:
        logger.warning("cache désactivé (%s) : %s", self.path, error)
        if self._db is not None:
            self._db.close()
        self._db = None
