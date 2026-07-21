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


def test_settings_hidden_calendars_roundtrip(db):
    # A list value round-trips as-is (whole array replaced on each write).
    assert store.update_settings(db, {"hidden_calendars": ["a", "b"]}) == {
        "hidden_calendars": ["a", "b"]
    }
    assert store.get_settings(db) == {"hidden_calendars": ["a", "b"]}
    # An empty list is a real value (all calendars visible again), not an
    # omission — the store must store it rather than skip it like None.
    assert store.update_settings(db, {"hidden_calendars": []}) == {
        "hidden_calendars": []
    }
    assert store.get_settings(db) == {"hidden_calendars": []}


def test_settings_archived_calendars_roundtrip(db):
    # Archived calendars are stored the same way as hidden ones: a list of ids
    # in the account settings blob (the collections themselves stay on the wire).
    assert store.update_settings(db, {"archived_calendars": ["a", "b"]}) == {
        "archived_calendars": ["a", "b"]
    }
    assert store.get_settings(db) == {"archived_calendars": ["a", "b"]}
    # An empty list is a real value (everything restored), not an omission.
    assert store.update_settings(db, {"archived_calendars": []}) == {
        "archived_calendars": []
    }
    assert store.get_settings(db) == {"archived_calendars": []}
    # Archived and hidden are independent keys that coexist in the blob.
    merged = store.update_settings(
        db, {"hidden_calendars": ["x"], "archived_calendars": ["y"]}
    )
    assert merged == {"hidden_calendars": ["x"], "archived_calendars": ["y"]}


def test_settings_show_completed_roundtrip(db):
    # Whether completed tasks show inline in the main view. Booleans must
    # round-trip and False must persist (only None is "unset" — see the merge).
    store.update_settings(db, {"show_completed_tasks": True})
    assert store.update_settings(db, {"show_completed_tasks": False}) == {
        "show_completed_tasks": False
    }
    assert store.get_settings(db) == {"show_completed_tasks": False}


def test_settings_hidden_lists_roundtrip(db):
    # The tasks-side analogue of hidden_calendars: a plain list of list ids in
    # the settings blob (the collections themselves are untouched on the wire).
    assert store.update_settings(db, {"hidden_lists": ["a", "b"]}) == {
        "hidden_lists": ["a", "b"]
    }
    assert store.get_settings(db) == {"hidden_lists": ["a", "b"]}
    # An empty list is a real value (every list visible again), not an omission.
    assert store.update_settings(db, {"hidden_lists": []}) == {"hidden_lists": []}
    assert store.get_settings(db) == {"hidden_lists": []}


def test_settings_task_groups_roundtrip(db):
    # Groups are stored as an ordered array of {id, name, lists} objects. The
    # whole array is replaced on each write (membership + order in one blob).
    groups = [
        {"id": "g1", "name": "Work", "lists": ["l1", "l2"]},
        {"id": "g2", "name": "Home", "lists": []},
    ]
    assert store.update_settings(db, {"task_groups": groups}) == {"task_groups": groups}
    assert store.get_settings(db) == {"task_groups": groups}
    # Collapsed-group ids coexist as an independent key.
    merged = store.update_settings(db, {"collapsed_groups": ["g2"]})
    assert merged == {"task_groups": groups, "collapsed_groups": ["g2"]}
    # An empty array clears grouping (a real value, not an omission).
    assert store.update_settings(db, {"task_groups": []})["task_groups"] == []
