"""Stage 5 of the audit backlog: delivery infrastructure and test gaps.

Two kinds of finding live here.

**Delivery.** The Windows client, the install script and the release workflow.
There is no dotnet runtime in the unit environment, so the C# findings are pinned
structurally — the source is read and the property asserted. That is weaker than
executing it, but it is deterministic, it runs everywhere, and it fails the
moment the shape regresses. Closing finding "the Windows client ships with zero
tests" is what would let these become real tests.

**Test gaps.** A test-gap finding is closed by a test EXISTING, so the pin is
necessarily a meta-test: it asserts the suite covers the named path, and it goes
green when somebody writes that coverage. Kept honest by naming the specific
symbol or behaviour the gap is about, not just a file.

See test_backlog_stage1.py for how the xfail(strict=True) harness works.
"""
from __future__ import annotations

import pathlib
import re
from datetime import datetime, timezone

import pytest

pytestmark = [pytest.mark.backlog, pytest.mark.stage5]

XFAIL = dict(strict=True)
REPO = pathlib.Path(__file__).resolve().parents[2]
TESTS = pathlib.Path(__file__).resolve().parent


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _suite_text() -> str:
    """Every test in the backend suite except the backlog pins themselves — a
    pin must never be able to satisfy the gap it is pinning."""
    return "\n".join(
        p.read_text(encoding="utf-8")
        for p in sorted(TESTS.glob("test_*.py"))
        if not p.name.startswith("test_backlog_")
    )


# ── delivery: the Windows client ──────────────────────────────────────────

@pytest.mark.xfail(reason="AUDIT open: Updater.cs:75 update failure kills startup", **XFAIL)
def test_an_update_failure_falls_back_to_the_installed_build():
    """`EnsureWebAssetsAsync` guards the RELEASE LOOKUP with `haveLocal` and
    degrades to "Offline — using the installed build". The DOWNLOAD that follows
    has no such guard, so a connection dropped mid-transfer, a truncated zip or
    a failed directory swap throws straight out of startup — with a complete,
    working build sitting on disk. The client refuses to open over a fault that
    it is already designed to survive."""
    src = _read("desktop/Smylte.Desktop/Updater.cs")

    swap = re.search(r"await DownloadAndSwapAsync\(.*?\);", src, re.S)
    assert swap, "DownloadAndSwapAsync call not found — has Updater.cs been restructured?"

    window = src[max(0, swap.start() - 400):swap.end() + 200]
    assert re.search(r"\btry\b", window) and "haveLocal" in window, (
        "the download/swap is not wrapped in a fallback that keeps a working "
        "installed build openable when an update fails"
    )


@pytest.mark.xfail(reason="AUDIT open: Updater.cs:207 interrupted swap strands the build", **XFAIL)
def test_a_stranded_previous_build_is_recovered_on_the_next_run():
    """The swap is: move `web` -> `web.old`, then `web.new` -> `web`. The catch
    handles a throw from the second move, but a process killed BETWEEN them (the
    user closing the window, a reboot, the installer being terminated) leaves the
    only working copy in `web.old` and no `web` at all. Nothing ever looks in
    `web.old` again, and the next run sees `haveLocal == false`."""
    src = _read("desktop/Smylte.Desktop/Updater.cs")

    have_local = re.search(r"var haveLocal\s*=.*?;", src, re.S)
    assert have_local, "haveLocal probe not found"

    # Recovery has to happen before the first thing that consumes haveLocal.
    assert re.search(r'\.old.*?(Directory\.Move|Restore|Recover)', src[:have_local.end()], re.S), (
        "nothing restores a build stranded in web.old by an interrupted swap"
    )


@pytest.mark.xfail(reason="AUDIT open: LocalServer.cs:257 the client has no tests", **XFAIL)
def test_the_windows_client_has_tests():
    """CI compiles the client and never runs it, so the local proxy's
    path-traversal guard and its cookie rewriting — the two places where a
    mistake is a security bug rather than a cosmetic one — are unverified. This
    is the finding that unblocks the two structural pins above."""
    csproj = list((REPO / "desktop").rglob("*.csproj"))
    test_projects = [p for p in csproj
                     if "test" in p.stem.lower()
                     or "Microsoft.NET.Test.Sdk" in p.read_text(encoding="utf-8")]
    assert test_projects, (
        f"no test project under desktop/ (found only {[p.name for p in csproj]}); "
        f"the client is compiled by CI but never exercised"
    )


# ── delivery: install script and release workflow ─────────────────────────

@pytest.mark.xfail(reason="AUDIT open: setup.sh:31 runs python -m tasksd from the wrong cwd", **XFAIL)
def test_setup_runs_the_module_from_the_backend_directory():
    """`python -m tasksd hash-password` resolves `tasksd` off the interpreter's
    path, which only contains the CWD. setup.sh calls it without changing into
    $BACKEND, so the documented install aborts on "No module named tasksd" —
    after prompting for every password, and before writing the env file."""
    src = _read("deploy/setup.sh")

    call = re.search(r"^.*-m tasksd hash-password.*$", src, re.M)
    assert call, "the hash-password call is gone — has setup.sh been rewritten?"
    line = call.group(0)

    assert re.search(r"\bcd\b|--directory|\bpushd\b", line) or re.search(
        r"^\s*cd\s+\"?\$\{?BACKEND", src[:call.start()], re.M), (
        f"nothing puts the shell in $BACKEND before `python -m tasksd`:\n  {line.strip()}"
    )


@pytest.mark.xfail(reason="AUDIT open: desktop-release.yml:10 no concurrency group", **XFAIL)
def test_the_desktop_release_workflow_serialises_its_runs():
    """The release is a ROLLING tag: every run overwrites the same assets. With
    no concurrency group, two pushes in quick succession race, and the slower —
    older — build can land last and become what everyone downloads. ci.yml can
    race harmlessly; this one publishes."""
    # Read as text, not yaml: PyYAML is not in requirements.txt, and a test that
    # ERRORS on a missing import in CI is worse than no test at all.
    src = _read(".github/workflows/desktop-release.yml")
    assert re.search(r"^concurrency:", src, re.M), (
        "desktop-release.yml has no top-level concurrency group, so an older "
        "build can clobber a newer one on the rolling release"
    )


# ── test gaps ─────────────────────────────────────────────────────────────

@pytest.mark.xfail(reason="AUDIT open: xml.py:198 parse_multistatus untested", **XFAIL)
def test_the_multistatus_parser_has_unit_coverage():
    """`parse_multistatus` is the single place untrusted wire XML becomes app
    state — every href, etag, displayname, colour and component set the rest of
    the backend trusts comes through it. It has no unit test at all, so its
    behaviour on a partial 207, a missing propstat, a non-200 status or a
    namespace-shifted document is unpinned."""
    assert "parse_multistatus" in _suite_text(), (
        "no test exercises parse_multistatus — the whole PROPFIND/REPORT "
        "response-parsing path is uncovered"
    )


@pytest.mark.xfail(reason="AUDIT open: test_mcp.py:259 batch framing untested", **XFAIL)
def test_the_json_rpc_batch_path_has_coverage():
    """`run_batch`'s list branch — empty-batch rejection, mixed
    request/notification batches, the all-notifications case that must answer
    202 with no body — is entirely uncovered, on the endpoint a hostile client
    talks to."""
    assert "run_batch" in _suite_text(), (
        "no test sends a JSON-RPC batch; the batch-framing path is uncovered"
    )


@pytest.mark.xfail(reason="AUDIT open: test_mcp.py:208 no event write tool coverage", **XFAIL)
@pytest.mark.parametrize("tool", [
    "smylte_create_event", "smylte_update_event", "smylte_delete_event",
])
def test_every_event_write_tool_is_exercised(tool):
    """The task tools are covered; the event tools are not — including the
    `scope` argument that decides whether an edit touches one occurrence or
    rewrites a whole series. That is the most destructive argument the connector
    exposes, and no MCP-level test drives it."""
    assert tool in _suite_text(), f"no MCP test exercises {tool}"


def test_book_slot_is_driven_across_a_dst_transition(tmp_path):
    """Closes the write half of the DST test gap.

    The read half is already covered — the battery in test_scheduling.py now
    supplies a real `busy` list and a `now` inside the repeated fall-back hour.
    What had no coverage at all was `book_slot` itself, which is where an
    accepted booking becomes a real VEVENT on the owner's calendar: the guard
    that a booked instant was genuinely offered, and the end instant written for
    it, both had to be right across a transition and neither was pinned.

    NOT xfail: this is the test whose absence was the finding, so it asserts the
    behaviour as fixed and must stay green.
    """
    from tests.test_service_unit import _make_link, _settings, _stub_create_event
    from tasksd.dav.client import CollectionInfo
    from tasksd.db import store as _store
    from tasksd.service import TaskService

    svc = TaskService(_settings())
    try:
        _store.upsert_collection(svc._conn, CollectionInfo(
            href="/u/meetings/", displayname="Meetings", components={"VEVENT"}))
        # Sunday 2026-11-01, America/Chicago: 01:00-02:00 runs twice.
        token = _make_link(
            svc, availability={"6": ["00:00-05:00"]}, duration_minutes=30,
            horizon_days=1, min_notice_hours=0)
        captured = _stub_create_event(svc)
        now = datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc)   # 00:30 CDT

        # The SECOND pass of the repeated hour, named by its true offset.
        res = svc.book_slot(token, start_iso="2026-11-01T01:00:00-06:00",
                            name="N", email="n@x.co", now=now)
        assert res is not None
        assert captured["dtstart"] == datetime(2026, 11, 1, 7, 0, tzinfo=timezone.utc)
        assert captured["dtend"] == datetime(2026, 11, 1, 7, 30, tzinfo=timezone.utc)

        # An instant outside the link's window must still be refused on the day
        # the wall clock repeats — 05:30 CST is past the 05:00 close.
        with pytest.raises(Exception):
            svc.book_slot(token, start_iso="2026-11-01T05:30:00-06:00",
                          name="M", email="m@x.co", now=now)
    finally:
        svc.close()
