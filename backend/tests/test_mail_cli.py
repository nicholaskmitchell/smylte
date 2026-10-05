"""`python -m smylted secrets ...` — the operator's way to manage the mail credentials.

Everything runs in-process through `secrets_main`, with the environment
pointing the database, the encrypted file and its key at tmp_path. The
keyring is a fake module backed by a dict. What these pin down: the key file
is created 0600 and never overwritten, a value goes in through getpass and
never comes back out, and migration moves the secrets rather than copying them.
"""
from __future__ import annotations

import os
import stat
from types import SimpleNamespace

import pytest

from smylted import __main__ as entry
from smylted import config as cfg_module
from smylted.mail import cli, redact
from smylted.mail import secrets as sec

KEY = "sk-ant-api03-" + "B" * 30 + "WXYZ"
PASSWORD = "bridge-pass-CLI-4242"


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    """Only this test's settings in the environment, both spellings cleared."""
    for k in list(os.environ):
        if k.startswith(("SMYLTE_", "TASKS_")):
            monkeypatch.delenv(k, raising=False)
    cfg_module._stale_warned.clear()
    monkeypatch.setenv("SMYLTE_DB", str(tmp_path / "cli.db"))
    monkeypatch.setenv("SMYLTE_SECRETS_BACKEND", "file")
    monkeypatch.setenv("SMYLTE_SECRETS_FILE", str(tmp_path / "secrets.enc"))
    monkeypatch.setenv("SMYLTE_SECRETS_KEY_FILE", str(tmp_path / "secrets.key"))
    redact.forget_all_for_tests()
    yield monkeypatch
    redact.forget_all_for_tests()


def _prompt(monkeypatch, value: str) -> list[str]:
    prompts: list[str] = []

    def fake(prompt: str = "") -> str:
        prompts.append(prompt)
        return value

    monkeypatch.setattr(cli.getpass, "getpass", fake)
    return prompts


class FakeOSKeyring:
    priority = 5


class PasswordDeleteError(Exception):
    pass


def _fake_keyring():
    held: dict[tuple[str, str], str] = {}

    def delete_password(service, name):
        if (service, name) not in held:
            raise PasswordDeleteError("not found")
        del held[(service, name)]

    return SimpleNamespace(
        held=held,
        get_keyring=lambda: FakeOSKeyring(),
        get_password=lambda service, name: held.get((service, name)),
        set_password=lambda service, name, value: held.__setitem__((service, name), value),
        delete_password=delete_password,
        errors=SimpleNamespace(PasswordDeleteError=PasswordDeleteError),
    )


# ── init-key ─────────────────────────────────────────────────────────────────

def test_init_key_creates_a_private_file_and_refuses_to_overwrite(tmp_path, capsys):
    path = tmp_path / "conf" / "my.key"
    assert cli.secrets_main(["init-key", "--path", str(path)]) == 0
    out = capsys.readouterr().out
    assert str(path) in out and "mode 0600" in out
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    before = path.read_bytes()

    assert cli.secrets_main(["init-key", "--path", str(path)]) == 1
    assert "already exists" in capsys.readouterr().err
    assert path.read_bytes() == before


def test_init_key_defaults_to_the_configured_path(tmp_path, capsys):
    assert cli.secrets_main(["init-key"]) == 0
    assert (tmp_path / "secrets.key").exists()
    assert str(tmp_path / "secrets.key") in capsys.readouterr().out


# ── set / status / clear ─────────────────────────────────────────────────────

def test_set_reads_the_value_from_getpass_and_status_shows_only_a_hint(env, tmp_path, capsys):
    prompts = _prompt(env, KEY)
    assert cli.secrets_main(["set", "anthropic_api_key"]) == 0
    assert prompts == ["anthropic_api_key: "]
    assert KEY not in capsys.readouterr().out

    assert cli.secrets_main(["status"]) == 0
    out = capsys.readouterr().out
    assert "backend: file" in out
    assert "anthropic_api_key: set" in out
    assert "…WXYZ" in out
    assert "imap_password: unset" in out
    assert "typesafe_api_key: unset" in out
    assert KEY not in out
    assert KEY.encode() not in (tmp_path / "secrets.enc").read_bytes()

    assert cli.secrets_main(["clear", "anthropic_api_key"]) == 0
    capsys.readouterr()
    assert cli.secrets_main(["status"]) == 0
    assert "anthropic_api_key: unset" in capsys.readouterr().out


def test_an_empty_value_stores_nothing(env, capsys):
    _prompt(env, "   ")
    assert cli.secrets_main(["set", "imap_password"]) == 1
    assert "nothing" in capsys.readouterr().err


def test_an_unknown_name_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as ei:
        cli.secrets_main(["set", "root_password"])
    assert ei.value.code != 0


def test_a_store_error_is_reported_without_a_traceback(env, tmp_path, capsys):
    _prompt(env, KEY)
    assert cli.secrets_main(["set", "anthropic_api_key"]) == 0
    os.chmod(tmp_path / "secrets.key", 0o644)
    capsys.readouterr()
    assert cli.secrets_main(["set", "anthropic_api_key"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error: ") and "chmod 600" in err
    assert KEY not in err


def test_main_dispatches_the_secrets_command(env, monkeypatch, capsys):
    monkeypatch.setattr(entry.sys, "argv", ["smylted", "secrets", "status"])
    assert entry.main() == 0
    assert "anthropic_api_key: unset" in capsys.readouterr().out


# ── migrate ──────────────────────────────────────────────────────────────────

def test_migrate_moves_secrets_from_the_keyring_to_the_file(env, tmp_path, capsys):
    fake = _fake_keyring()

    class FakeKeyringBackend(sec.KeyringBackend):
        def __init__(self, namespace="default", *, module=None):
            super().__init__(namespace, module=fake)

    env.setattr(sec, "KeyringBackend", FakeKeyringBackend)
    env.setenv("SMYLTE_SECRETS_BACKEND", "auto")

    _prompt(env, KEY)
    assert cli.secrets_main(["set", "anthropic_api_key"]) == 0
    _prompt(env, PASSWORD)
    assert cli.secrets_main(["set", "imap_password"]) == 0
    assert "stored in keyring" in capsys.readouterr().out
    assert set(fake.held.values()) == {KEY, PASSWORD}
    assert not (tmp_path / "secrets.enc").exists()

    assert cli.secrets_main(["migrate", "--to", "file"]) == 0
    out = capsys.readouterr().out
    assert "anthropic_api_key" in out and "imap_password" in out
    assert KEY not in out and PASSWORD not in out
    assert fake.held == {}

    assert cli.secrets_main(["status"]) == 0
    out = capsys.readouterr().out
    assert "backend: file" in out
    assert "anthropic_api_key: set" in out and "imap_password: set" in out
    data = (tmp_path / "secrets.enc").read_bytes()
    assert KEY.encode() not in data and PASSWORD.encode() not in data
