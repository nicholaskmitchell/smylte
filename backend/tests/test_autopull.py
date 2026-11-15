"""`deploy/smylte-autopull.sh`, run for real against a throwaway origin.

Cron runs it every minute with nothing set, and the desk key's updater runs it
with SMYLTE_AUTOPULL_REPO, SMYLTE_AUTOPULL_REPORT and SMYLTE_AUTOPULL_NO_RESTART.
Each test builds a bare origin, a clone of it at $HOME/smylte (HOME is tmp), a
fake backend/.venv/bin/pip and a stub deploy/migrate.sh in the clone, then runs
the repo's script, never the clone's copy.

npm, sudo and curl are faked as exported bash functions rather than files on
PATH: the script puts /usr/local/bin:/usr/bin:/bin before PATH, so a fake there
would lose to a real sudo or npm. A function wins over any PATH lookup.

Cron mode must not have changed at all, so it is checked against the script as
it was at HEAD (`git show HEAD:deploy/smylte-autopull.sh`), run on an identical
fixture: the same exit code, the same log lines and the same calls, and nothing
on stdout.
"""
from __future__ import annotations

import fcntl
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
AUTOPULL = REPO / "deploy" / "smylte-autopull.sh"

if shutil.which("bash") is None or shutil.which("git") is None:
    pytest.skip("needs bash and git", allow_module_level=True)

_MIGRATE_STUB = """#!/bin/bash
case "$1" in
  --auto) echo "migrate.sh --auto" >> "$CALLS"; echo "migrate: nothing to do"
          exit "${MIGRATE_AUTO_RC:-0}" ;;
  --status) if [ -n "${MIGRATE_BLOCKED:-}" ]; then echo "PENDING 0099 synthetic (needs root)"
            else echo "nothing pending"; fi ;;
esac
"""

_PIP = """#!/bin/bash
echo "pip $*" >> "$CALLS"
echo "pip output"
exit "${PIP_RC:-0}"
"""

# Exported functions: bash imports them before it reads the script.
_FUNCTIONS = {
    "npm": '() { echo "npm $* in ${PWD##*/}" >> "$CALLS"; echo "npm output"; '
           'if [ "$1" = ci ]; then return "${NPM_CI_RC:-0}"; fi; return "${NPM_RC:-0}"; }',
    "sudo": '() { echo "sudo $*" >> "$CALLS"; return "${SUDO_RC:-0}"; }',
    "curl": '() { echo "curl" >> "$CALLS"; return 1; }',
}

_TS = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} ", re.M)
_SHA = re.compile(r"\b[0-9a-f]{7,40}\b")


@dataclass
class Box:
    root: Path
    home: Path
    dev: Path
    clone: Path
    calls: Path
    env: dict

    def git(self, cwd: Path, *args: str) -> str:
        r = subprocess.run(["git", *args], cwd=cwd, env=self.env,
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return r.stdout.strip()

    def push(self, files: dict[str, str], message: str = "change") -> str:
        for name, text in files.items():
            path = self.dev / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        self.git(self.dev, "add", "-A")
        self.git(self.dev, "commit", "-q", "-m", message)
        self.git(self.dev, "push", "-q", "origin", "main")
        return self.git(self.dev, "rev-parse", "HEAD")

    def head(self) -> str:
        return self.git(self.clone, "rev-parse", "HEAD")

    def log(self) -> list[str]:
        f = self.home / "smylte-autopull.log"
        return _TS.sub("", f.read_text()).splitlines() if f.exists() else []

    def called(self) -> list[str]:
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def comparable(self, lines: list[str]) -> list[str]:
        """Without what differs between two fixtures: their paths and commit ids."""
        return [_SHA.sub("<sha>", l.replace(str(self.root), "<box>")) for l in lines]

    @property
    def pending(self) -> Path:
        return self.home / ".smylte-autopull-pending"


def _make_box(root: Path) -> Box:
    root.mkdir()
    home = root / "home"
    home.mkdir()
    calls = root / "calls"
    env = {
        "PATH": os.environ["PATH"], "HOME": str(home), "LANG": "C", "CALLS": str(calls),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    env.update({f"BASH_FUNC_{name}%%": body for name, body in _FUNCTIONS.items()})
    origin, dev, clone = root / "origin.git", root / "dev", home / "smylte"
    box = Box(root=root, home=home, dev=dev, clone=clone, calls=calls, env=env)
    box.git(root, "init", "-q", "--bare", "-b", "main", str(origin))
    box.git(root, "init", "-q", "-b", "main", str(dev))
    box.git(dev, "remote", "add", "origin", str(origin))
    (dev / "deploy").mkdir()
    (dev / "deploy" / "migrate.sh").write_text(_MIGRATE_STUB)
    (dev / "deploy" / "migrate.sh").chmod(0o755)
    box.push({"backend/requirements.txt": "fastapi\n", "frontend/package.json": "{}\n",
              "frontend/src/main.js": "1\n", "README": "x\n"}, "first")
    box.git(root, "clone", "-q", str(origin), str(clone))
    pip = clone / "backend" / ".venv" / "bin" / "pip"
    pip.parent.mkdir(parents=True)
    pip.write_text(_PIP)
    pip.chmod(0o755)
    (clone / "frontend" / "node_modules").mkdir()
    return box


@pytest.fixture
def make_box(tmp_path):
    n = iter(range(100))
    return lambda: _make_box(tmp_path / f"box{next(n)}")


@pytest.fixture
def box(make_box) -> Box:
    return make_box()


def _run(box: Box, text: str | None = None, **env: str) -> subprocess.CompletedProcess:
    """The repo's script, as text (as the updater runs it), or `text`."""
    if text is None:
        text = AUTOPULL.read_text(encoding="utf-8")
    return subprocess.run(["bash", "-c", text, "smylte-autopull"], cwd=box.home,
                          env={**box.env, **env}, capture_output=True, text=True, timeout=120)


def _report(box: Box, **env: str) -> subprocess.CompletedProcess:
    return _run(box, SMYLTE_AUTOPULL_REPORT="1", **env)


def _outcome(r: subprocess.CompletedProcess) -> str:
    lines = r.stdout.splitlines()
    assert lines and lines[-1].startswith("autopull: "), r.stdout + r.stderr
    assert len(lines) == 1, f"more than the outcome on stdout: {r.stdout!r}"
    return lines[-1][len("autopull: "):]


@pytest.fixture(scope="module")
def old_script() -> str:
    r = subprocess.run(["git", "show", "HEAD:deploy/smylte-autopull.sh"], cwd=REPO,
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("the script at HEAD cannot be read: " + r.stderr.strip())
    return r.stdout


# ── cron mode: unchanged ─────────────────────────────────────────────────────

def _scenario(box: Box, name: str) -> dict[str, str]:
    """Arrange `name` in `box`; returns the environment the run gets."""
    if name in ("frontend", "blocked", "migrate-fails", "restart-fails"):
        box.push({"frontend/src/main.js": "2\n"})
    elif name in ("deps", "pip-fails", "npm-fails"):
        box.push({"backend/requirements.txt": "fastapi\nhttpx\n", "frontend/package.json": '{"a": 1}\n'})
    elif name == "fetch-fails":
        shutil.move(str(box.dev.parent / "origin.git"), str(box.dev.parent / "gone.git"))
    elif name == "pull-fails":
        box.push({"README": "theirs\n"})
        (box.clone / "README").write_text("ours\n")
        box.git(box.clone, "commit", "-q", "-am", "local")
    elif name == "no-checkout":
        shutil.rmtree(box.clone)
    return {"blocked": {"MIGRATE_BLOCKED": "1"}, "migrate-fails": {"MIGRATE_AUTO_RC": "1"},
            "pip-fails": {"PIP_RC": "1"}, "npm-fails": {"NPM_CI_RC": "1", "NPM_RC": "1"},
            "restart-fails": {"SUDO_RC": "1"}}.get(name, {})


_SCENARIOS = ["nothing-new", "frontend", "deps", "blocked", "migrate-fails", "pip-fails",
              "npm-fails", "restart-fails", "fetch-fails", "pull-fails", "no-checkout"]


@pytest.mark.parametrize("name", _SCENARIOS)
def test_cron_mode_is_unchanged(make_box, old_script, name):
    runs = []
    for text in (old_script, None):
        box = make_box()
        env = _scenario(box, name)
        r = _run(box, text, **env)
        runs.append((r.returncode, r.stdout, box.comparable(box.log()),
                     box.comparable(box.called())))
    (old_rc, old_out, old_log, old_calls), (rc, out, log, calls) = runs
    assert out == "", out
    assert old_out == ""
    assert rc == old_rc
    assert log == old_log
    assert calls == old_calls
    if name in ("frontend", "deps", "migrate-fails", "pip-fails", "npm-fails", "restart-fails"):
        assert "sudo -n systemctl restart smylte.service" in calls, calls
    else:
        assert not [c for c in calls if c.startswith("sudo")], calls


def test_cron_mode_leaves_at_once_while_another_run_holds_the_lock(box):
    with open(box.home / ".smylte-autopull.lock", "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        start = time.monotonic()
        r = _run(box)
        assert time.monotonic() - start < 10
    assert (r.returncode, r.stdout) == (0, "")
    assert box.log() == [] and box.called() == []


def test_cron_mode_never_writes_the_pending_marker(box):
    box.push({"frontend/src/main.js": "2\n"})
    r = _run(box, NPM_RC="1")
    assert r.stdout == ""
    assert not box.pending.exists()


# ── REPORT mode: the outcome ─────────────────────────────────────────────────

def test_nothing_new_is_current(box):
    r = _report(box)
    assert (_outcome(r), r.returncode) == ("current", 0)
    assert not [c for c in box.called() if c.startswith("sudo")]


def test_a_pull_is_updated_and_restarts_unless_told_not_to(make_box):
    box = make_box()
    box.push({"frontend/src/main.js": "2\n"})
    r = _report(box)
    assert (_outcome(r), r.returncode) == ("updated", 0)
    assert "npm run build in frontend" in box.called()
    assert "sudo -n systemctl restart smylte.service" in box.called()

    box = make_box()
    box.push({"frontend/src/main.js": "2\n"})
    r = _report(box, SMYLTE_AUTOPULL_NO_RESTART="1")
    assert (_outcome(r), r.returncode) == ("updated", 0)
    assert "npm run build in frontend" in box.called()
    assert not [c for c in box.called() if c.startswith("sudo")], box.called()
    assert "applied; the restart is left to the caller" in box.log()


def test_no_restart_alone_changes_only_the_restart(box):
    box.push({"frontend/src/main.js": "2\n"})
    r = _run(box, SMYLTE_AUTOPULL_NO_RESTART="1")
    assert (r.returncode, r.stdout) == (0, "")
    assert not [c for c in box.called() if c.startswith("sudo")]


def test_a_pending_root_migration_is_blocked(box):
    box.push({"frontend/src/main.js": "2\n"})
    r = _report(box, MIGRATE_BLOCKED="1")
    assert (_outcome(r), r.returncode) == ("blocked", 0)
    assert not [c for c in box.called() if c.startswith("sudo")]


@pytest.mark.parametrize("name, outcome", [
    ("no-checkout", "failed cd"),
    ("fetch-fails", "failed fetch"),
    ("pull-fails", "failed pull"),
    ("pip-fails", "failed pip"),
    ("npm-fails", "failed npm"),
    ("migrate-fails", "failed migrate"),
])
def test_each_failure_is_reported_and_exits_1(box, name, outcome):
    env = _scenario(box, name)
    r = _report(box, **env)
    assert (_outcome(r), r.returncode) == (outcome, 1)
    assert not [c for c in box.called() if c.startswith("sudo")]


@pytest.mark.parametrize("env", [{"NPM_CI_RC": "1"}, {"NPM_RC": "1"}], ids=["ci", "build"])
def test_either_npm_step_failing_is_failed_npm_before_the_migrations(box, env):
    box.push({"frontend/package.json": '{"b": 2}\n'})
    r = _report(box, **env)
    assert _outcome(r) == "failed npm"
    assert "migrate.sh --auto" not in box.called()


def test_repo_names_the_checkout(box):
    other = box.home / "elsewhere"
    shutil.move(str(box.clone), str(other))
    box.push({"frontend/src/main.js": "2\n"})
    r = _report(box, SMYLTE_AUTOPULL_REPO=str(other))
    assert _outcome(r) == "updated"
    assert box.git(other, "rev-parse", "HEAD") == box.git(box.dev, "rev-parse", "HEAD")
    assert (box.home / "smylte-autopull.log").exists()      # the log stays in $HOME


def test_report_mode_waits_for_the_lock(box):
    held = open(box.home / ".smylte-autopull.lock", "w")
    fcntl.flock(held, fcntl.LOCK_EX)
    threading.Timer(1.5, held.close).start()
    start = time.monotonic()
    r = _report(box)
    assert time.monotonic() - start >= 1.0
    assert _outcome(r) == "current"


def test_a_lock_that_never_frees_is_failed_busy(box):
    env = {"BASH_FUNC_flock%%": '() { echo "flock $*" >> "$CALLS"; return 1; }'}
    r = _report(box, **env)
    assert (_outcome(r), r.returncode) == ("failed busy", 1)
    assert box.called() == ["flock -w 900 9"]


def test_an_unplanned_exit_prints_no_outcome(box):
    # A `set -u` trip is no planned exit, so there is no outcome to print: the
    # updater then says "autopull gave no outcome" instead of a wrong one.
    text = AUTOPULL.read_text(encoding="utf-8").replace(
        'BRANCH=$(git symbolic-ref', 'echo "$NO_SUCH_VARIABLE"\nBRANCH=$(git symbolic-ref', 1)
    r = _run(box, text, SMYLTE_AUTOPULL_REPORT="1")
    assert r.returncode != 0
    assert r.stdout == ""


# ── REPORT mode: the pending marker ──────────────────────────────────────────

def test_a_failed_rebuild_leaves_a_marker_and_the_retry_rebuilds_and_reports_updated(box):
    before = box.head()
    box.push({"frontend/src/main.js": "2\n"})
    r = _report(box, NPM_RC="1", SMYLTE_AUTOPULL_NO_RESTART="1")
    assert _outcome(r) == "failed npm"
    assert box.head() != before                       # the pull went through
    assert box.pending.read_text().strip() == before
    box.calls.write_text("")

    r = _report(box, SMYLTE_AUTOPULL_NO_RESTART="1")      # nothing new to fetch
    assert (_outcome(r), r.returncode) == ("updated", 0)
    assert "npm run build in frontend" in box.called()
    assert not box.pending.exists()

    box.calls.write_text("")
    r = _report(box, SMYLTE_AUTOPULL_NO_RESTART="1")
    assert _outcome(r) == "current"
    assert box.called() == ["migrate.sh --auto"]


def test_a_failed_pip_leaves_the_marker_too_and_stops_before_the_migrations(box):
    before = box.head()
    box.push({"backend/requirements.txt": "fastapi\nhttpx\n"})
    r = _report(box, PIP_RC="1")
    assert _outcome(r) == "failed pip"
    assert box.pending.read_text().strip() == before
    assert "migrate.sh --auto" not in box.called()
    box.calls.write_text("")
    r = _report(box)
    assert _outcome(r) == "updated"
    assert "pip install -q -r backend/requirements.txt" in box.called()


def test_the_oldest_base_wins(box):
    first = box.head()
    box.push({"frontend/src/main.js": "2\n"})
    assert _outcome(_report(box, NPM_RC="1")) == "failed npm"
    box.push({"backend/requirements.txt": "fastapi\nhttpx\n"})
    assert _outcome(_report(box, NPM_RC="1")) == "failed npm"
    assert box.pending.read_text().strip() == first
    box.calls.write_text("")
    assert _outcome(_report(box)) == "updated"
    # Both commits' changes are rebuilt: the diff runs from the first base.
    assert "pip install -q -r backend/requirements.txt" in box.called()
    assert "npm run build in frontend" in box.called()


@pytest.mark.parametrize("content", ["garbage\n", "0" * 40 + "\n", ""],
                         ids=["not-a-sha", "not-an-ancestor", "empty"])
def test_a_marker_that_is_not_an_ancestor_sha_is_deleted(box, content):
    box.pending.write_text(content)
    r = _report(box)
    assert _outcome(r) == "current"
    assert not box.pending.exists()
