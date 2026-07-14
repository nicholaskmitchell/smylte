"""Sync-engine integration tests against the scratch Radicale (spec §8)."""
from __future__ import annotations

import os
import shutil

import pytest

from tasksd import ical
from tasksd.db import store
from tests.conftest import SCRATCH_STORAGE
from tests.helpers import foreign_raw

pytestmark = pytest.mark.radicale


def _put(dav, collection_href, uid, summary, **kw):
    dav.put(f"{collection_href}{uid}.ics", foreign_raw(uid, summary, **kw), if_none_match="*")


def test_full_sync_pulls_items(engine, dav, collection, db):
    _put(dav, collection.href, "a@x", "Alpha", extra=("PRIORITY:1",))
    _put(dav, collection.href, "b@x", "Beta")
    engine.discover()
    stats = engine.sync(collection.href)
    assert stats.full_resync is True
    assert store.count_items(db, collection.href) == 2
    row = store.get_item(db, collection.href, "a@x")
    assert row["summary"] == "Alpha" and row["priority"] == 1
    assert b"X-FOREIGN-KEEP" in row["raw_ics"]


def test_incremental_new_and_change(engine, dav, collection, db):
    engine.discover()
    engine.sync(collection.href)  # initial full
    _put(dav, collection.href, "c@x", "Gamma")
    s1 = engine.sync(collection.href)
    assert s1.full_resync is False and s1.upserted == 1
    # a foreign client changes the summary (same UID, overwrite)
    dav.put(f"{collection.href}c@x.ics", foreign_raw("c@x", "Gamma-2"), if_match=None,
            if_none_match=None)
    s2 = engine.sync(collection.href)
    assert s2.upserted == 1
    assert store.get_item(db, collection.href, "c@x")["summary"] == "Gamma-2"


def test_foreign_delete_orphans_sidecar(engine, dav, collection, db):
    engine.discover()
    uid = engine.create_task(collection.href, "Doomed")
    store.set_sidecar(db, collection.href, uid, kanban_column="doing")
    href = store.get_item(db, collection.href, uid)["href"]
    dav.delete(href)  # a foreign client removes it
    stats = engine.sync(collection.href)
    assert stats.removed == 1
    assert store.get_item(db, collection.href, uid) is None
    side = store.get_sidecar(db, collection.href, uid)
    assert side is not None and side["orphaned_at"] is not None  # sidecar survived, orphaned
    assert side["kanban_column"] == "doing"


def test_delete_and_recreate_same_uid_keeps_sidecar(engine, dav, collection, db):
    uid = "recreate@x"
    _put(dav, collection.href, uid, "v1")
    engine.discover()
    engine.sync(collection.href)
    store.set_sidecar(db, collection.href, uid, kanban_column="backlog", sort_order=3.5)
    old_href = store.get_item(db, collection.href, uid)["href"]

    # A client that delete-and-recreates: same UID, brand-new href.
    dav.delete(old_href)
    new_href = f"{collection.href}{uid}-RECREATED.ics"
    dav.put(new_href, foreign_raw(uid, "v2"), if_none_match="*")

    engine.sync(collection.href)
    row = store.get_item(db, collection.href, uid)
    # href is opaque and Radicale percent-encodes it (invariant #4: never assert
    # exact href equality); what matters is the row followed the UID to the new
    # resource and the sidecar rode along.
    assert row is not None and row["summary"] == "v2"
    assert "RECREATED" in row["href"] and row["href"] != old_href
    side = store.get_sidecar(db, collection.href, uid)
    assert side["kanban_column"] == "backlog" and side["sort_order"] == 3.5
    assert side["orphaned_at"] is None  # returning UID un-orphaned


def test_invalid_token_falls_back_to_full_resync(engine, dav, collection, db):
    engine.discover()
    engine.sync(collection.href)
    # Corrupt the stored token (as a prune/expiry would).
    store.set_sync_token(db, collection.href, "http://radicale.org/ns/sync/BOGUS-TOKEN")
    _put(dav, collection.href, "post@x", "after invalidation")
    stats = engine.sync(collection.href)
    assert stats.full_resync is True
    assert store.get_item(db, collection.href, "post@x") is not None


def test_dropped_radicale_cache_recovers_consistently(engine, dav, collection, db):
    if not os.path.isdir(SCRATCH_STORAGE):
        pytest.skip(f"scratch storage not at {SCRATCH_STORAGE}")
    engine.discover()
    engine.sync(collection.href)
    _put(dav, collection.href, "d@x", "Delta")
    engine.sync(collection.href)  # token now reflects Delta

    # Drop Radicale's on-disk cache under the collection — the real-world #6
    # scenario (a pruned/rebuilt cache). Whether that invalidates the persisted
    # sync token is a Radicale-version detail, not our engine's contract: it
    # invalidates on 3.7.6 but not on the 3.7.4 the CI image pins, so this test
    # does NOT assert on stats.full_resync — the deterministic invalid-token
    # fallback is covered by test_invalid_token_falls_back_to_full_resync above.
    # What must always hold is that the next sync ends consistent with the wire
    # (incrementally or via full resync) and never crashes.
    for root, dirs, _ in os.walk(SCRATCH_STORAGE):
        if os.path.basename(root) == ".Radicale.cache":
            shutil.rmtree(root, ignore_errors=True)
    _put(dav, collection.href, "e@x", "Epsilon")
    engine.sync(collection.href)
    assert store.get_item(db, collection.href, "e@x") is not None
    assert store.count_items(db, collection.href) == 2


# ── idempotent creates: a caller-supplied slug makes replays safe ────────────

def test_create_replay_with_same_slug_is_idempotent(engine, collection, db):
    engine.discover()
    slug = "ab" * 16
    uid1 = engine.create_task(collection.href, "Once", slug=slug)
    uid2 = engine.create_task(collection.href, "Once", slug=slug)   # lost-response retry
    assert uid1 == uid2 == f"{slug}@tasksd"
    items = store.get_items(db, collection.href)
    assert sum(1 for i in items if i["uid"] == uid1) == 1
    # first write wins: the replay must not clobber the stored resource
    assert store.get_item(db, collection.href, uid1)["summary"] == "Once"


def test_create_slug_occupied_by_foreign_resource_conflicts(engine, dav, collection):
    from tasksd.sync.engine import ConflictError

    engine.discover()
    slug = "cd" * 16
    dav.put(f"{collection.href}{slug}.ics", foreign_raw("theirs@foreign", "Theirs"),
            if_none_match="*")
    with pytest.raises(ConflictError):
        engine.create_task(collection.href, "Mine", slug=slug)
