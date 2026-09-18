"""The `tasksd` compatibility shim, and the literal UID suffix contract.

Both exist to survive the window between a deploy and the migration, and both
were shipped untested — the shim's own source comment even claimed "the warning
is what tests assert on" while nothing imported it.

The shim is what keeps the live Pi booting in that window: autopull pulls new
code every minute, but the migration that replaces `tasks.service` is a human
running sudo, and until then the old unit's ExecStart is `python -m tasksd`.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent


def _run(code: str) -> subprocess.CompletedProcess:
    """A FRESH interpreter, cwd=backend/ — how the systemd unit invokes it.

    In-process importing would prove nothing: `smylted` is already imported by
    the rest of the suite, and pytest's own pythonpath setting is not what
    production uses. The unit sets WorkingDirectory to backend/ and runs
    `python -m tasksd`, which puts cwd on sys.path; that is the path under test.
    """
    return subprocess.run([sys.executable, "-c", code], cwd=BACKEND,
                          capture_output=True, text=True)


def test_the_old_package_still_imports():
    r = _run("import tasksd; print(tasksd.__version__)")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip(), "the shim imported but re-exported nothing"


def test_it_re_exports_the_real_package_rather_than_forking_it():
    """A shim that answers with its own copy of anything is a second source of
    truth that will drift."""
    r = _run("import tasksd, smylted; print(tasksd.__version__ == smylted.__version__)")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "True"


def test_it_says_so_on_stderr_where_the_journal_will_see_it():
    """DeprecationWarning is silent by default, so the operator-facing notice has
    to be a plain write. systemd puts stderr into the journal."""
    r = _run("import tasksd")
    assert r.returncode == 0, r.stderr
    assert "smylted" in r.stderr and "tasksd" in r.stderr
    assert "migrate.sh" in r.stderr, "the notice must name the remedy"


def test_it_also_raises_a_deprecationwarning():
    r = _run("import warnings, sys\n"
             "warnings.simplefilter('error', DeprecationWarning)\n"
             "try:\n"
             "    import tasksd\n"
             "except DeprecationWarning:\n"
             "    print('raised')\n")
    assert r.returncode == 0, r.stderr
    assert "raised" in r.stdout


def test_the_old_entry_point_still_reaches_the_real_one():
    """`python -m tasksd hash-password` is the pre-rename CLI, and the branch
    that proves __main__ delegates without starting a server."""
    r = subprocess.run([sys.executable, "-m", "tasksd", "hash-password"],
                       cwd=BACKEND, input="hunter2xy\nhunter2xy\n",
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    # A scrypt hash, i.e. it really ran smylted.auth.hash_password.
    assert re.search(r"scrypt", r.stdout), r.stdout


# ── the UID suffix, as a literal ────────────────────────────────────────────

def test_the_minted_uid_suffix_is_pinned_literally():
    """Everything else asserts `== ical.UID_SUFFIX`, which cannot catch the
    constant itself changing. The suffix is written into every resource this app
    puts on a CalDAV server other clients read, and frontend/src/api.ts mints the
    same string independently to predict a uid before the server answers — so it
    is a cross-language contract that needs one literal pin on each side."""
    from smylted import ical
    assert ical.UID_SUFFIX == "@smylted"
    assert ical.UID_SUFFIX_LEGACY == "@tasksd"


def test_the_frontend_mints_the_same_suffix():
    """The SPA predicts `{client_id}@smylted` before the create returns, and a
    subtask added in that window writes it as its RELATED-TO. If the two sides
    disagree the pointer names a resource that will never exist, and the subtask
    is orphaned in CalDAV — not just locally."""
    api_ts = (REPO / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")
    from smylted import ical
    assert f"export const UID_SUFFIX = '{ical.UID_SUFFIX}'" in api_ts
    assert f"export const UID_SUFFIX_LEGACY = '{ical.UID_SUFFIX_LEGACY}'" in api_ts
