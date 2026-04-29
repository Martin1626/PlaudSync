"""Disk-backed folder catalog cache with 1h TTL — pure local IO."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from plaudsync.filetag_cache import FiletagCache, _CACHE_FILENAME, _TTL_SECONDS
from plaudsync.plaud_client import FolderCatalogItem


def _items() -> list[FolderCatalogItem]:
    return [
        FolderCatalogItem(id="a" * 32, name="Alza", icon="", color=""),
        FolderCatalogItem(id="b" * 32, name="FHB", icon="📁", color="#FF0000"),
    ]


def test_load_returns_none_when_cache_missing(tmp_path):
    cache = FiletagCache(state_root=tmp_path)
    assert cache.load() is None


def test_save_then_load_roundtrip(tmp_path):
    cache = FiletagCache(state_root=tmp_path)
    cache.save(_items())
    loaded = cache.load()
    assert loaded is not None
    assert [(f.id, f.name, f.icon, f.color) for f in loaded] == [
        (i.id, i.name, i.icon, i.color) for i in _items()
    ]


def test_is_stale_when_missing(tmp_path):
    cache = FiletagCache(state_root=tmp_path)
    assert cache.is_stale() is True


def test_is_stale_after_ttl(tmp_path):
    cache = FiletagCache(state_root=tmp_path)
    cache.save(_items())
    payload = json.loads((tmp_path / _CACHE_FILENAME).read_text(encoding="utf-8"))
    payload["fetched_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=_TTL_SECONDS + 60)
    ).isoformat()
    (tmp_path / _CACHE_FILENAME).write_text(json.dumps(payload), encoding="utf-8")
    assert cache.is_stale() is True


def test_fresh_cache_not_stale(tmp_path):
    cache = FiletagCache(state_root=tmp_path)
    cache.save(_items())
    assert cache.is_stale() is False


def test_lookup_by_id_hits(tmp_path):
    cache = FiletagCache(state_root=tmp_path)
    cache.save(_items())
    item = cache.lookup_by_id("a" * 32)
    assert item is not None
    assert item.name == "Alza"


def test_lookup_by_id_miss(tmp_path):
    cache = FiletagCache(state_root=tmp_path)
    cache.save(_items())
    assert cache.lookup_by_id("z" * 32) is None


def test_corrupt_json_returns_none_load(tmp_path):
    (tmp_path / _CACHE_FILENAME).write_text("{not valid json", encoding="utf-8")
    cache = FiletagCache(state_root=tmp_path)
    assert cache.load() is None
    assert cache.is_stale() is True


def test_fetched_at_returns_iso_or_none(tmp_path):
    cache = FiletagCache(state_root=tmp_path)
    assert cache.fetched_at() is None
    cache.save(_items())
    iso = cache.fetched_at()
    assert iso is not None
    # must parse back as datetime
    datetime.fromisoformat(iso)


def test_save_overwrites_previous(tmp_path):
    cache = FiletagCache(state_root=tmp_path)
    cache.save(_items())
    cache.save([FolderCatalogItem(id="c" * 32, name="New", icon="", color="")])
    loaded = cache.load()
    assert loaded is not None
    assert len(loaded) == 1
    assert loaded[0].name == "New"
