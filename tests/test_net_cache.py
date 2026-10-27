"""Le cache disque : durée de vie par type de donnée, sans cache, hors ligne, cache abîmé."""

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from forceupdate.net import Cache, CacheKind, default_cache_path

VERSIONS = CacheKind.VERSIONS


class Clock:
    """Une horloge qu'on avance à la main."""

    def __init__(self, now: float = 1_800_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_kinds_and_their_lifetime() -> None:
    assert VERSIONS.ttl == 3600
    assert [kind.value for kind in CacheKind] == ["versions"]


def test_default_path_is_the_user_cache_dir() -> None:
    path = default_cache_path()
    assert path.name == "cache.sqlite3"
    assert "forceupdate" in path.parts


def test_set_then_get(tmp_path: Path) -> None:
    clock = Clock()
    cache = Cache(tmp_path / "cache.sqlite3", clock=clock)
    cache.set(VERSIONS, "https://pypi.org/simple/flask/", {"versions": ["1.0", "2.0"], "é": None})
    entry = cache.get(VERSIONS, "https://pypi.org/simple/flask/")
    assert entry is not None
    assert entry.value == {"versions": ["1.0", "2.0"], "é": None}
    assert entry.stored_at == datetime.fromtimestamp(clock.now, UTC)
    assert entry.fresh
    assert cache.get(VERSIONS, "https://pypi.org/simple/django/") is None
    cache.close()


def test_an_entry_expires_after_its_lifetime(tmp_path: Path) -> None:
    clock = Clock()
    cache = Cache(tmp_path / "cache.sqlite3", clock=clock)
    cache.set(VERSIONS, "clé", [1])
    clock.now += 3599
    assert cache.get(VERSIONS, "clé") is not None
    clock.now += 2
    assert cache.get(VERSIONS, "clé") is None
    # Hors ligne, une entrée périmée sert quand même, dite périmée.
    stale = cache.get(VERSIONS, "clé", stale_ok=True)
    assert stale is not None
    assert stale.value == [1]
    assert not stale.fresh
    cache.close()


def test_set_replaces_the_entry(tmp_path: Path) -> None:
    clock = Clock()
    cache = Cache(tmp_path / "cache.sqlite3", clock=clock)
    cache.set(VERSIONS, "clé", "ancien")
    clock.now += 4000
    cache.set(VERSIONS, "clé", "nouveau")
    entry = cache.get(VERSIONS, "clé")
    assert entry is not None
    assert entry.value == "nouveau"
    cache.close()


def test_the_cache_is_shared_between_instances(tmp_path: Path) -> None:
    first = Cache(tmp_path / "cache.sqlite3")
    second = Cache(tmp_path / "cache.sqlite3")
    first.set(VERSIONS, "clé", {"a": 1})
    entry = second.get(VERSIONS, "clé")
    assert entry is not None
    assert entry.value == {"a": 1}
    first.close()
    second.close()


def test_clear(cache: Cache) -> None:
    cache.set(VERSIONS, "clé", 1)
    cache.clear()
    assert cache.get(VERSIONS, "clé") is None


def test_a_disabled_cache_reads_and_writes_nothing() -> None:
    cache = Cache.disabled()
    assert not cache.enabled
    assert cache.path is None
    cache.set(VERSIONS, "clé", 1)
    assert cache.get(VERSIONS, "clé") is None
    assert cache.get(VERSIONS, "clé", stale_ok=True) is None
    cache.clear()
    cache.close()


def test_the_directory_is_created(tmp_path: Path) -> None:
    cache = Cache(tmp_path / "a" / "b" / "cache.sqlite3")
    cache.set(VERSIONS, "clé", 1)
    assert (tmp_path / "a" / "b" / "cache.sqlite3").is_file()
    cache.close()


def test_old_entries_are_purged_when_opening(tmp_path: Path) -> None:
    clock = Clock()
    cache = Cache(tmp_path / "cache.sqlite3", clock=clock)
    cache.set(VERSIONS, "vieille", 1)
    clock.now += 20 * 24 * 3600
    cache.set(VERSIONS, "récente", 2)
    cache.close()
    clock.now += 11 * 24 * 3600
    reopened = Cache(tmp_path / "cache.sqlite3", clock=clock)
    assert reopened.get(VERSIONS, "vieille", stale_ok=True) is None
    assert reopened.get(VERSIONS, "récente", stale_ok=True) is not None
    reopened.close()


def test_a_corrupted_file_is_replaced(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite3"
    path.write_bytes(b"ceci n'est pas une base SQLite" * 100)
    cache = Cache(path)
    assert cache.enabled
    cache.set(VERSIONS, "clé", 1)
    assert cache.get(VERSIONS, "clé") is not None
    cache.close()


def test_another_schema_version_empties_the_cache(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite3"
    cache = Cache(path)
    cache.set(VERSIONS, "clé", 1)
    cache.close()
    db = sqlite3.connect(path)
    db.execute("PRAGMA user_version = 99")
    db.commit()
    db.close()
    reopened = Cache(path)
    assert reopened.get(VERSIONS, "clé") is None
    reopened.set(VERSIONS, "clé", 2)
    assert reopened.get(VERSIONS, "clé") is not None
    reopened.close()


def test_an_unreadable_value_is_a_miss(cache: Cache) -> None:
    cache.set(VERSIONS, "clé", 1)
    assert cache.path is not None
    db = sqlite3.connect(cache.path)
    db.execute("UPDATE entries SET value = 'pas du JSON'")
    db.commit()
    db.close()
    assert cache.get(VERSIONS, "clé") is None


def test_a_disk_error_disables_the_cache(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    (tmp_path / "fichier").write_text("", encoding="utf-8")
    cache = Cache(tmp_path / "fichier" / "cache.sqlite3")
    with caplog.at_level(logging.WARNING, logger="forceupdate.net.cache"):
        cache.set(VERSIONS, "clé", 1)
        assert cache.get(VERSIONS, "clé") is None
        assert not cache.enabled
    assert len(caplog.records) == 1
    assert caplog.records[0].getMessage().startswith("cache désactivé")


def test_an_error_while_running_disables_the_cache(
    cache: Cache, caplog: pytest.LogCaptureFixture
) -> None:
    cache.set(VERSIONS, "clé", 1)
    assert cache.path is not None
    db = sqlite3.connect(cache.path)
    db.execute("DROP TABLE entries")
    db.commit()
    db.close()
    with caplog.at_level(logging.WARNING, logger="forceupdate.net.cache"):
        assert cache.get(VERSIONS, "clé") is None
    assert not cache.enabled
    assert "no such table" in caplog.text
