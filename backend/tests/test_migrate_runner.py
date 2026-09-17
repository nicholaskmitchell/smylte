"""`deploy/migrate.sh` — the versioned migration runner.

It runs on one Raspberry Pi, by hand, a few times a year, which is exactly the
profile of a script that quietly stops working and is found out at the worst
moment. The real migration touches /etc, /var/lib and systemd and cannot be
exercised here, but the FRAMEWORK can: ordering, the level file, the idempotent
skip, and the rule that `--auto` stops at a root-needing migration instead of
skipping ahead to a later one it could have run.

That last one is the whole safety property. 0002 needs no root and would apply
cleanly on its own — against a box 0001 has not touched yet, which is not a
state any migration is written for.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MIGRATE = REPO / "deploy" / "migrate.sh"
MIGRATIONS = REPO / "deploy" / "migrations"


def _run(box: "Box", *args: str, as_root: bool = True):
    cwd, home = box.repo, box.home
    env = dict(
        os.environ,
        HOME=str(home),
        SMYLTE_MIGRATION_STATE=str(home / ".smylte-migration-level"),
        SMYLTE_REPO_DIR=str(cwd),
    )
    if not as_root:
        # The runner asks `id -u`; a stub earlier on PATH answers non-zero.
        env["PATH"] = f"{home / 'fakebin'}:{env['PATH']}"
    return subprocess.run(
        [str(cwd / "deploy" / "migrate.sh"), *args],
        cwd=cwd, env=env, capture_output=True, text=True,
    )


@dataclass
class Box:
    """A throwaway checkout carrying the real runner and synthetic migrations."""
    repo: Path
    marks: Path
    home: Path


@pytest.fixture
def box(tmp_path: Path) -> Box:
    repo = tmp_path / "repo"
    (repo / "deploy" / "migrations").mkdir(parents=True)
    shutil.copy(MIGRATE, repo / "deploy" / "migrate.sh")
    (repo / "deploy" / "migrate.sh").chmod(0o755)

    marks = tmp_path / "marks"
    marks.mkdir()
    for n, needs_root in (("0001", "no"), ("0002", "yes"), ("0003", "no")):
        (repo / "deploy" / "migrations" / f"{n}-synthetic.sh").write_text(
            f'NEEDS_ROOT={needs_root}\n'
            f'describe() {{ echo "synthetic {n}"; }}\n'
            f'applies() {{ [ ! -f "{marks}/{n}" ]; }}\n'
            f'apply() {{ run touch "{marks}/{n}"; }}\n'
        )

    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "id").write_text('#!/bin/sh\n[ "$1" = "-u" ] && echo 1000 || exec /usr/bin/id "$@"\n')
    (fake / "id").chmod(0o755)

    return Box(repo=repo, marks=marks, home=tmp_path)


def _applied(box: Box) -> list[str]:
    return sorted(p.name for p in box.marks.iterdir())


def _level(box: Box) -> str:
    f = box.home / ".smylte-migration-level"
    return f.read_text().strip() if f.exists() else "0"


def test_applies_every_pending_migration_in_order(box):
    r = _run(box)
    assert r.returncode == 0, r.stderr
    assert _applied(box) == ["0001", "0002", "0003"]
    assert _level(box) == "0003"


def test_a_second_run_changes_nothing(box):
    _run(box)
    before = _level(box)
    r = _run(box)
    assert r.returncode == 0, r.stderr
    assert _level(box) == before
    assert _applied(box) == ["0001", "0002", "0003"]


def test_a_reset_level_does_not_re_apply_satisfied_work(box):
    """Resume after a crash, and the belt-and-braces case where the level file
    is lost entirely. `applies()` is the real guard — the level is a shortcut,
    never the thing standing between a migration and running twice."""
    _run(box)
    (box.home / ".smylte-migration-level").write_text("0\n")
    r = _run(box)
    assert r.returncode == 0, r.stderr
    assert "already satisfied" in r.stdout
    assert _level(box) == "0003"


def test_auto_stops_at_a_root_migration_rather_than_skipping_it(box):
    """The safety property. 0003 needs no root and would apply cleanly on its
    own — against a box 0002 has not touched, which is a state nothing is
    written for. Autopull runs this path every minute, so 'stops' must mean
    stops, and must not be an error either or every deploy reports a failure."""
    r = _run(box, "--auto", as_root=False)
    assert r.returncode == 0, r.stderr
    assert _applied(box) == ["0001"], "applied past the root-needing migration"
    assert "NEEDS ROOT" in r.stdout
    assert "sudo" in r.stdout


def test_dry_run_changes_nothing(box):
    r = _run(box, "--dry-run")
    assert r.returncode == 0, r.stderr
    assert _applied(box) == []
    assert _level(box) == "0"


def test_status_reports_without_applying(box):
    r = _run(box, "--status")
    assert r.returncode == 0, r.stderr
    assert _applied(box) == []
    assert "PENDING 0001" in r.stdout
    assert "needs root" in r.stdout          # flagged on 0002, which autopull greps for


def test_an_unknown_option_is_refused(box):
    """Rather than being ignored, which on a script that rewrites /etc is the
    difference between 'you typo'd --dry-run' and 'it ran for real'."""
    r = _run(box, "--dryrun")
    assert r.returncode != 0
    assert _applied(box) == []


# ── the real migrations, as source ──────────────────────────────────────────

def _migration_files() -> list[Path]:
    return sorted(MIGRATIONS.glob("[0-9][0-9][0-9][0-9]-*.sh"))


def test_there_are_migrations_to_check():
    """Anti-vacuity: a glob that matched nothing would pass everything below."""
    assert len(_migration_files()) >= 2


@pytest.mark.parametrize("path", _migration_files(), ids=lambda p: p.name)
def test_each_migration_is_valid_bash_and_complete(path: Path):
    assert subprocess.run(["bash", "-n", str(path)]).returncode == 0, f"{path.name} does not parse"
    body = path.read_text()
    for required in ("NEEDS_ROOT=", "describe()", "applies()", "apply()"):
        assert required in body, f"{path.name} is missing {required}"


def test_migration_numbers_are_unique():
    """Two migrations sharing a number means one of them silently never runs:
    the level is a single integer, so recording one records both."""
    nums = [p.name.split("-")[0] for p in _migration_files()]
    assert len(nums) == len(set(nums)), nums


def test_the_runner_itself_parses():
    assert subprocess.run(["bash", "-n", str(MIGRATE)]).returncode == 0


def test_autopull_applies_migrations_and_refuses_to_restart_past_one():
    """Autopull is the only thing that runs unattended, so the two lines that
    make it safe are worth pinning: it calls --auto, and it declines to restart
    while a root migration is outstanding rather than bringing the service up
    against a half-renamed box."""
    body = (REPO / "deploy" / "smylte-autopull.sh").read_text()
    assert "migrate.sh --auto" in body
    assert "--status" in body and "needs root" in body
    guard = body.index("needs root")
    restart = body.index("systemctl restart smylte.service")
    assert guard < restart, "the pending-migration guard must come before the restart"

    # And it must not sit behind the "nothing new, stop" exit. The migration
    # needing root arrives in one commit but is applied by a human minutes or
    # days later; gating the check on "did we just pull" would mention it once
    # and then fall silent for the whole window it actually matters in.
    nothing_new = body.index('[ "$PULLED" = 1 ] || exit 0')
    assert guard < nothing_new, (
        "the migration check must run on every tick, not only after a pull")


def test_the_pending_migration_notice_is_sent_once_not_every_tick():
    """Consequence of the line above. The check runs every minute, so an
    unguarded Telegram send would be a message a minute until the migration is
    applied — which trains you to ignore it, the opposite of the point. The
    marker is cleared once nothing is pending, so the next migration notifies."""
    body = (REPO / "deploy" / "smylte-autopull.sh").read_text()
    assert "notify_pending_migration" in body
    assert 'NOTIFIED="$HOME/.smylte-migration-notified"' in body
    assert '[ -f "$NOTIFIED" ] && return 0' in body, "the once-only guard is gone"
    assert 'rm -f "$NOTIFIED"' in body, "the marker is never cleared; a later migration would be silent"
    # The bot token is in the URL because Telegram offers no alternative, so the
    # call must not be able to write it into the deploy log.
    send = body.index("api.telegram.org")
    line_end = body.index("touch \"$NOTIFIED\"", send)
    assert '>>"$LOG"' not in body[send:line_end], "the telegram call must not log (it carries the token)"


# ── the `run` contract ──────────────────────────────────────────────────────
# --dry-run is only a preview because every side effect goes through `run`. A
# migration that calls `mv` or `sed -i` directly executes it during a dry run —
# on /etc, on a box someone was only inspecting. The runner cannot enforce this
# (it cannot tell a side effect from a guard), so it is enforced here instead.

_SIDE_EFFECTS = ("mv ", "rm ", "cp ", "install ", "chown ", "chmod ",
                 "systemctl ", "crontab ", "sed -i", "touch ", "mkdir ")


@pytest.mark.parametrize("path", _migration_files(), ids=lambda p: p.name)
def test_every_side_effect_goes_through_run(path: Path):
    offenders = []
    for i, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # `run <cmd>` is the contract; a pipeline or a $(...) capture is a read.
        if line.startswith(("run ", "local ", "for ", "if ", "elif ", "while ")):
            continue
        for cmd in _SIDE_EFFECTS:
            if line.startswith(cmd):
                offenders.append(f"{path.name}:{i}: {line}")
                break
    assert not offenders, (
        "side effects must be wrapped in `run` so --dry-run stays a preview:\n"
        + "\n".join(offenders))
