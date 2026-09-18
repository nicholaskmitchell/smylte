"""The TASKS_* -> SMYLTE_* fallback, which is what makes the rename survivable.

The two halves of a deployment do not move at the same instant: autopull ships
new code to the Pi every minute, while `/etc/smylte/smylte.env` is only rewritten
when a human runs `deploy/migrate.sh`. In that window the new code reads an env
file written in the old spelling.

Without the fallback that window is not graceful degradation. `auth_enabled`
defaults ON, `auth_password_hash` reads empty, and `create_app` raises — the
service refuses to start. These pin the fallback so nobody deletes it before the
deployments have actually migrated.
"""
from __future__ import annotations

import logging

import pytest

from smylted import config as cfg


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Both spellings of everything cleared, and the warn-once memo reset."""
    for k in list(cfg.os.environ):
        if k.startswith(("SMYLTE_", "TASKS_")):
            monkeypatch.delenv(k, raising=False)
    cfg._stale_warned.clear()
    yield
    cfg._stale_warned.clear()


def test_the_old_spelling_still_answers(monkeypatch):
    monkeypatch.setenv("TASKS_AUTH_USER", "nick")
    assert cfg.Settings.from_env().auth_user == "nick"


def test_the_new_spelling_wins_when_both_are_set(monkeypatch):
    """A half-rewritten env file is a real mid-migration state. Preferring the
    stale value there would make the migration look applied when it was not."""
    monkeypatch.setenv("TASKS_AUTH_USER", "old")
    monkeypatch.setenv("SMYLTE_AUTH_USER", "new")
    assert cfg.Settings.from_env().auth_user == "new"


def test_booleans_come_through_the_fallback_too(monkeypatch):
    """_bool gates auth_enabled, cookie_secure and access_required. If it did not
    read the old spelling, a pre-rename env file would silently lose three
    security controls to their defaults rather than keeping what was configured."""
    monkeypatch.setenv("TASKS_AUTH_ENABLED", "false")
    monkeypatch.setenv("TASKS_COOKIE_SECURE", "false")
    s = cfg.Settings.from_env()
    assert s.auth_enabled is False
    assert s.cookie_secure is False


def test_a_pre_rename_env_file_still_boots(monkeypatch):
    """The whole point. Every security-critical setting in the old spelling, and
    the app must come up configured — not fall back to defaults and refuse."""
    monkeypatch.setenv("TASKS_AUTH_USER", "nick")
    monkeypatch.setenv("TASKS_AUTH_PASSWORD_HASH", "scrypt$fake$hash")
    monkeypatch.setenv("TASKS_SESSION_SECRET", "s" * 64)
    monkeypatch.setenv("TASKS_HOOK_SECRET", "hook-secret")
    monkeypatch.setenv("TASKS_DB", "/tmp/whatever.db")
    s = cfg.Settings.from_env()
    assert s.auth_enabled is True                    # default, unchanged
    assert s.auth_password_hash == "scrypt$fake$hash"
    assert s.session_secret == "s" * 64              # NOT empty -> no ephemeral secret
    assert s.hook_secret == "hook-secret"
    assert s.db_path == "/tmp/whatever.db"


def test_a_stale_name_is_named_once_in_the_log(monkeypatch, caplog):
    """The journal has to say which variable to fix, or the deprecation is
    invisible. Once per variable, not once per read — from_env reads some of
    them more than once and a per-read warning would bury the others."""
    monkeypatch.setenv("TASKS_AUTH_USER", "nick")
    with caplog.at_level(logging.WARNING, logger="smylted.config"):
        cfg.Settings.from_env()
        cfg.Settings.from_env()
    hits = [r for r in caplog.records if "TASKS_AUTH_USER" in r.getMessage()]
    assert len(hits) == 1, [r.getMessage() for r in hits]
    assert "SMYLTE_AUTH_USER" in hits[0].getMessage()


def test_defaults_carry_no_pre_rename_paths():
    """The dev-path defaults moved with the rename. A default still pointing at
    ~/tasks would quietly recreate the old layout on a fresh checkout."""
    s = cfg.Settings.from_env()
    assert "/tasks/" not in s.db_path and "/tasks/" not in s.static_dir
    assert s.db_path.endswith("smylte.db")


def test_an_unprefixed_name_is_not_mangled(monkeypatch):
    """_legacy only maps SMYLTE_*. A bare prefix swap would turn `RADICALE_URL`
    into a plausible-looking variable that is silently never found."""
    assert cfg._legacy("RADICALE_URL") is None
    assert cfg._legacy("SMYLTE_DB") == "TASKS_DB"
    monkeypatch.setenv("RADICALE_URL", "http://127.0.0.1:9999")
    assert cfg.Settings.from_env().radicale_url == "http://127.0.0.1:9999"
