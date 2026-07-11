"""Account-synced settings store — pure sqlite (the `db` fixture), no Radicale."""
from __future__ import annotations

from tasksd.db import store


def test_settings_default_empty(db):
    assert store.get_settings(db) == {}


def test_settings_merge_and_persist(db):
    assert store.update_settings(db, {"theme": "dark"}) == {"theme": "dark"}
    assert store.get_settings(db) == {"theme": "dark"}
    # None values are ignored (partial patch never clears a key by omission).
    assert store.update_settings(db, {"theme": None}) == {"theme": "dark"}
    # New keys merge in alongside existing ones.
    merged = store.update_settings(db, {"theme": "light", "density": "compact"})
    assert merged == {"theme": "light", "density": "compact"}
    assert store.get_settings(db) == {"theme": "light", "density": "compact"}


def test_settings_false_is_a_value_not_a_clear(db):
    # Booleans must round-trip: False is stored (only None is "unset").
    store.update_settings(db, {"sidebar_collapsed": True})
    assert store.update_settings(db, {"sidebar_collapsed": False}) == {
        "sidebar_collapsed": False
    }
    assert store.get_settings(db) == {"sidebar_collapsed": False}
