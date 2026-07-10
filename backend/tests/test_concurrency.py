"""Concurrency: two writers, interleaved, must never lose a property (spec §8).
This is the Phase-0 done-criterion."""
from __future__ import annotations

import random

import pytest

from tasksd import ical
from tasksd.db import connect, init_db
from tasksd.sync import ConflictError, SyncEngine
from tests.helpers import foreign_raw

pytestmark = pytest.mark.radicale


def _second_engine(new_dav, tmp_path):
    conn = connect(str(tmp_path / "writer_b.db"))
    init_db(conn)
    return SyncEngine(new_dav(), conn), conn


def test_two_writer_merge_no_lost_property(engine, dav, collection, db, new_dav, tmp_path):
    engine.discover()
    engine.sync(collection.href)
    uid = "concur@x"
    dav.put(
        f"{collection.href}{uid}.ics",
        foreign_raw(uid, "orig", extra=("PRIORITY:5", "X-APPLE-SORT-ORDER:733955200")),
        if_none_match="*",
    )
    engine.sync(collection.href)

    engine_b, conn_b = _second_engine(new_dav, tmp_path)
    try:
        engine_b.discover()
        engine_b.sync(collection.href)

        # A changes summary (succeeds). B still holds the pre-A etag, so its
        # priority change hits 412 and must merge onto A's version.
        engine.edit_task(collection.href, uid, ical.TaskEdit(summary="A-summary"))
        engine_b.edit_task(collection.href, uid, ical.TaskEdit(priority=1))

        final = dav.get(f"{collection.href}{uid}.ics").data.decode()
        tf = ical.extract_from_raw(final)
        assert tf.summary == "A-summary", "writer A's change was lost"
        assert tf.priority == 1, "writer B's change was lost in the merge"
        assert "X-APPLE-SORT-ORDER:733955200" in final, "foreign property dropped"
        assert "X-FOREIGN-KEEP" in final
    finally:
        conn_b.close()


def test_fuzz_interleaved_writers_never_lose_foreign_props(
    engine, dav, collection, db, new_dav, tmp_path
):
    engine.discover()
    engine.sync(collection.href)
    uid = "fuzz@x"
    dav.put(
        f"{collection.href}{uid}.ics",
        foreign_raw(uid, "start", extra=("PRIORITY:5", "X-APPLE-SORT-ORDER:1", "X-MOZ-GENERATION:9")),
        if_none_match="*",
    )
    engine.sync(collection.href)

    engine_b, conn_b = _second_engine(new_dav, tmp_path)
    rnd = random.Random(20260709)
    mk = [
        lambda n: ical.TaskEdit(summary=f"s{n}"),
        lambda n: ical.TaskEdit(priority=rnd.choice([1, 5, 9])),
        lambda n: ical.TaskEdit(description=f"d{n}"),
        lambda n: ical.TaskEdit(status=rnd.choice(["NEEDS-ACTION", "IN-PROCESS"])),
    ]
    try:
        engine_b.discover()
        engine_b.sync(collection.href)
        engines = [engine, engine_b]
        for n in range(24):
            for e in engines:
                e.sync(collection.href)
            a, b = rnd.sample(engines, 2)
            a.edit_task(collection.href, uid, rnd.choice(mk)(n))
            try:
                b.edit_task(collection.href, uid, rnd.choice(mk)(n))
            except ConflictError:
                pass  # both retried the same revision; a conflict is surfaced, nothing lost
            wire = dav.get(f"{collection.href}{uid}.ics").data.decode()
            assert "X-FOREIGN-KEEP" in wire, f"round {n}: X-FOREIGN-KEEP lost"
            assert "X-APPLE-SORT-ORDER" in wire, f"round {n}: X-APPLE-SORT-ORDER lost"
            assert "X-MOZ-GENERATION" in wire, f"round {n}: X-MOZ-GENERATION lost"
    finally:
        conn_b.close()
