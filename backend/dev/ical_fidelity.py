"""icalendar vs vobject: the load-bearing round-trip fidelity comparison (spec §3).

For every corpus file: parse, change ONLY the VTODO SUMMARY, re-serialize, and use
the independent canonicalizer to check that every *other* property, parameter, and
subcomponent survived. Prints a scorecard and picks the library the round-trip
module should use.

Run: backend/.venv/bin/python -m dev.ical_fidelity   (cwd = backend/, PYTHONPATH=.)
"""
from __future__ import annotations

import glob
import os

from tasksd.ical import canonical as C

CHANGED = "CHANGED-BY-TEST"
CORPUS = os.path.join(os.path.dirname(__file__), "..", "tests", "corpus", "*.ics")


def icalendar_rt(text: str) -> str:
    from icalendar import Calendar

    cal = Calendar.from_ical(text)
    for comp in cal.walk("VTODO"):
        comp["SUMMARY"] = CHANGED
    return cal.to_ical().decode("utf-8")


def vobject_rt(text: str) -> str:
    import vobject

    cal = vobject.readOne(text)
    for todo in cal.contents.get("vtodo", []):
        todo.summary.value = CHANGED
    return cal.serialize()


def assess(original: str, rt_text: str) -> dict:
    drop = frozenset({"SUMMARY"})
    o, r = C.parse(original), C.parse(rt_text)
    lost = C.flatten(o, drop=drop) - C.flatten(r, drop=drop)
    added = C.flatten(r, drop=drop) - C.flatten(o, drop=drop)
    summary_changed = any(
        p[0] == "SUMMARY" and p[2] == CHANGED
        for comp in _walk(r)
        for p in comp.props
    )
    return {
        "semantic_ok": C.signature(o, drop=drop) == C.signature(r, drop=drop),
        "summary_changed": summary_changed,
        "lost": lost,
        "added": added,
    }


def _walk(comp: C.Comp):
    yield comp
    for c in comp.children:
        yield from _walk(c)


def _fmt(bag) -> str:
    if not bag:
        return "—"
    return "; ".join(f"{comp}:{n}" + (f";{dict(pr)}" if pr else "") + f"={v!r}"
                      for (comp, (n, pr, v)), _ in bag.items())


def main() -> None:
    files = sorted(glob.glob(CORPUS))
    tally = {"icalendar": 0, "vobject": 0}
    for path in files:
        with open(path, encoding="utf-8") as fh:
            original = fh.read()
        name = os.path.basename(path)
        print(f"\n=== {name} ===")
        for lib, fn in (("icalendar", icalendar_rt), ("vobject", vobject_rt)):
            try:
                rt = fn(original)
            except Exception as e:  # noqa: BLE001 — surface parse/serialize failures as a loss
                print(f"  {lib:10} PARSE/SERIALIZE ERROR: {type(e).__name__}: {e}")
                continue
            a = assess(original, rt)
            ok = a["semantic_ok"] and a["summary_changed"]
            tally[lib] += int(ok)
            print(f"  {lib:10} semantic_ok={a['semantic_ok']} summary_changed={a['summary_changed']}")
            if a["lost"]:
                print(f"    LOST : {_fmt(a['lost'])}")
            if a["added"]:
                print(f"    ADDED: {_fmt(a['added'])}")

    print("\n=== scorecard (files with perfect semantic preservation) ===")
    for lib, score in tally.items():
        print(f"  {lib:10} {score}/{len(files)}")
    winner = max(tally, key=tally.get)
    print(f"\n  -> winner: {winner}")


if __name__ == "__main__":
    main()
