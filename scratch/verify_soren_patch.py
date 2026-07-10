"""Verify the Søren radicale.py hardening against SCRATCH (never production).

Loads the REAL patched module with its target forced to the scratch server, then
checks that a normal VEVENT calendar stays visible to Søren's event tools while a
VTODO-only task list is excluded from them (but still discoverable if asked).
"""
import asyncio
import importlib.util
import os

# Force the scratch target BEFORE importing the module (it reads env at import).
os.environ["RADICALE_URL"] = "http://127.0.0.1:5233"
os.environ["RADICALE_USER"] = "testuser"
os.environ["RADICALE_PASSWORD"] = "testpass"

MOD = os.path.expanduser("~/soren/tools/radicale.py")
spec = importlib.util.spec_from_file_location("soren_radicale_under_test", MOD)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

import httpx  # noqa: E402


async def main() -> None:
    assert m._URL == "http://127.0.0.1:5233", f"NOT pointed at scratch: {m._URL}"
    async with httpx.AsyncClient() as client:
        cols = await m._propfind_collections(client)
        event_map = await m._calendar_urls(client)                    # event_only=True
        all_map = await m._calendar_urls(client, event_only=False)

    print("target:", m._URL, "user:", m._USER)
    print("\ndiscovered collections:")
    for c in sorted(cols, key=lambda c: c["name"]):
        comps = sorted(c["comps"]) or "(none advertised)"
        print(f"  {c['name']:14} comps={comps}  event_capable={c['event_capable']}")
    print("\nevent-tool target map (event_only=True):", sorted(event_map))
    print("full map (event_only=False):          ", sorted(all_map))

    assert "Events" in event_map, "FAIL: a real VEVENT calendar was hidden from Søren"
    assert "Inbox" not in event_map, "FAIL: VTODO-only task list leaked into event tools"
    assert "Inbox" in all_map, "FAIL: task list not discoverable even with event_only=False"
    print("\nPASS: real calendar kept for events; VTODO-only task list excluded.")


asyncio.run(main())
