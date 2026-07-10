"""Does Radicale store PUT bodies verbatim, or re-serialize them?

Decisive for the write-path design. If Radicale returns exactly what we PUT
(modulo line endings), a surgical text-level editor buys real byte-fidelity. If
Radicale normalizes on write, we only owe semantic fidelity and can let icalendar
serialize.

Run: backend/.venv/bin/python -m dev.radicale_normalization   (cwd=backend/, PYTHONPATH=.)
"""
from __future__ import annotations

import glob
import os

from tasksd.dav import DavClient
from tasksd.ical import canonical as C

CORPUS = os.path.join(os.path.dirname(__file__), "..", "tests", "corpus", "*.ics")


def _nl(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def main() -> None:
    c = DavClient("http://127.0.0.1:5233", "testuser", "testpass")
    # A permissive collection so any component (incl. VTIMEZONE siblings) is accepted.
    col = c.create_task_collection("norm-check", components=("VTODO", "VEVENT"))
    try:
        for path in sorted(glob.glob(CORPUS)):
            name = os.path.basename(path)
            with open(path, "rb") as fh:
                raw = fh.read()
            href = f"{col.href}{name}"
            c.put(href, raw, if_none_match="*")
            got = c.get(href).data or b""

            same_bytes = got == raw
            same_ignoring_eol = _nl(got) == _nl(raw)
            crlf = b"\r\n" in got
            semantic = C.signature(C.parse(raw.decode())) == C.signature(C.parse(got.decode()))
            print(f"{name:16} verbatim={same_bytes!s:5} "
                  f"verbatim_ignoring_EOL={same_ignoring_eol!s:5} "
                  f"stored_CRLF={crlf!s:5} semantic_equal={semantic!s:5} "
                  f"len {len(raw)}->{len(got)}")
            if not same_ignoring_eol:
                # show the first differing logical line
                a = _nl(raw).decode().splitlines()
                b = _nl(got).decode().splitlines()
                for i, (x, y) in enumerate(zip(a, b)):
                    if x != y:
                        print(f"    first diff @line {i}: PUT  {x!r}")
                        print(f"                        GOT  {y!r}")
                        break
                if len(a) != len(b):
                    print(f"    line count {len(a)} -> {len(b)}")
    finally:
        c.delete_collection(col.href)


if __name__ == "__main__":
    main()
