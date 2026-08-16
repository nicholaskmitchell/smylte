"""Stage 5 of the audit backlog: delivery infrastructure and test gaps.

**Stage 5 is CLOSED**, and with it the whole backlog — every finding from the
2026-08-16 sweep is fixed. These began as `xfail(strict=True)` pins and are now
ordinary tests that must stay green.

Two of the findings here were about the Windows client, and were originally
pinned by reading `Updater.cs` and asserting its shape, on the belief that no
dotnet toolchain was available. That was wrong: the SDK installs fine, and
`LocalServer.cs` and `Updater.cs` have no WinForms dependency between them (the
one apparent match was `Cache-Control` catching a `Control\\b` grep). Those two
structural pins are gone rather than kept alongside their replacements —
`desktop/Smylte.Desktop.Tests/` executes the behaviour instead, which a pin that
matches source text cannot. What remains here of the client is the meta-test
that the project exists and CI runs it, because that is a *backend*-visible
guard against the C# suite being quietly dropped.

**Test gaps.** A test-gap finding is closed by a test EXISTING, so the pin is
necessarily a meta-test: it asserts the suite covers the named path. Kept honest
by naming the specific symbol or behaviour the gap is about, not just a file.

See test_backlog_stage1.py for how the xfail(strict=True) harness works.
"""
from __future__ import annotations

import pathlib
import re
from datetime import datetime, timezone

import pytest

pytestmark = [pytest.mark.backlog, pytest.mark.stage5]

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

def test_the_windows_client_has_tests_and_ci_runs_them():
    """CI compiled the client and never ran it, so the local proxy's
    path-traversal guard and its cookie rewriting — the two places where a
    mistake is a security bug rather than a cosmetic one — were unverified.

    The tests themselves are C# and live in desktop/Smylte.Desktop.Tests; this
    asserts they exist and are wired into CI, which is the part a backend-only
    change could silently undo. A test project that nothing runs is a comment.
    """
    csproj = list((REPO / "desktop").rglob("*.csproj"))
    test_projects = [p for p in csproj
                     if "test" in p.stem.lower()
                     or "Microsoft.NET.Test.Sdk" in p.read_text(encoding="utf-8")]
    assert test_projects, (
        f"no test project under desktop/ (found only {[p.name for p in csproj]}); "
        f"the client is compiled by CI but never exercised"
    )

    ci = _read(".github/workflows/ci.yml")
    assert re.search(r"dotnet test\s+\S*desktop/", ci), (
        "the client test project exists but no CI step runs `dotnet test` on it"
    )

    # It has to be buildable off Windows or the ubuntu-side story is a promise:
    # a ProjectReference to the net8.0-windows app would drag in a runtime pack
    # that has no Linux build. Linked sources under a portable TFM is the shape
    # that lets this suite run anywhere.
    project = test_projects[0].read_text(encoding="utf-8")
    assert "<TargetFramework>net8.0</TargetFramework>" in project, (
        "the client test project targets a Windows-only TFM; it can be compiled "
        "but not run outside a Windows runner"
    )
    assert "<Compile Include=" in project
    assert "<ProjectReference" not in project


# ── delivery: install script and release workflow ─────────────────────────

def test_setup_runs_the_module_from_the_backend_directory():
    """`python -m tasksd hash-password` resolves `tasksd` off the interpreter's
    path, which only contains the CWD. setup.sh called it without changing into
    $BACKEND, so the documented install aborted on "No module named tasksd" —
    after prompting for every password, and before writing the env file."""
    src = _read("deploy/setup.sh")

    call = re.search(r"^.*-m tasksd hash-password.*$", src, re.M)
    assert call, "the hash-password call is gone — has setup.sh been rewritten?"
    line = call.group(0)

    assert re.search(r"\bcd\b|--directory|\bpushd\b", line) or re.search(
        r"^\s*cd\s+\"?\$\{?BACKEND", src[:call.start()], re.M), (
        f"nothing puts the shell in $BACKEND before `python -m tasksd`:\n  {line.strip()}"
    )


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
    # cancel-in-progress would be wrong here: killing a half-published release
    # leaves the rolling tag holding whatever assets had uploaded so far.
    assert re.search(r"^\s*cancel-in-progress:\s*false", src, re.M)


# ── test gaps ─────────────────────────────────────────────────────────────

def test_the_multistatus_parser_has_unit_coverage():
    """`parse_multistatus` is the single place untrusted wire XML becomes app
    state — every href, etag, displayname, colour and component set the rest of
    the backend trusts comes through it. It had no unit test at all, so its
    behaviour on a partial 207, a missing propstat, a non-200 status or a
    namespace-shifted document was unpinned. See tests/test_dav_xml.py."""
    assert "parse_multistatus" in _suite_text(), (
        "no test exercises parse_multistatus — the whole PROPFIND/REPORT "
        "response-parsing path is uncovered"
    )


def test_the_json_rpc_batch_path_has_coverage():
    """`run_batch`'s list branch — empty-batch rejection, mixed
    request/notification batches, the all-notifications case that must answer
    202 with no body — was entirely uncovered, on the endpoint a hostile client
    talks to. Covered in test_mcp.py, which is radicale-marked: those tests run
    in CI against the scratch server and skip without one."""
    assert "run_batch" in _suite_text(), (
        "no test sends a JSON-RPC batch; the batch-framing path is uncovered"
    )


@pytest.mark.parametrize("tool", [
    "smylte_create_event", "smylte_update_event", "smylte_delete_event",
])
def test_every_event_write_tool_is_exercised(tool):
    """The task tools were covered; the event tools were not — including the
    `scope` argument that decides whether an edit touches one occurrence or
    rewrites a whole series. That is the most destructive argument the connector
    exposes, and no MCP-level test drove it."""
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
