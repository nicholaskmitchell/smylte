"""The secret store — both backends, the env override, the auto choice and migration.

No real keyring and no network: the keyring is a fake module backed by a dict,
and the encrypted file lives under tmp_path. What these pin down is that a
secret never appears where it should not (the file on disk, a status payload),
that the key file is refused whenever it is not the service user's alone, and
that a ciphertext is bound to the slot it was written for.
"""
from __future__ import annotations

import base64
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from smylted.mail import redact
from smylted.mail import secrets as sec

API_KEY = "sk-ant-api03-abcdefgh1234"
PASSWORD = "bridge-pass-XYZ987"


@pytest.fixture(autouse=True)
def _clean_registry():
    redact.forget_all_for_tests()
    yield
    redact.forget_all_for_tests()


class FakeOSKeyring:
    priority = 5


class PasswordDeleteError(Exception):
    pass


def _fake_keyring(backend=None):
    """A stand-in for the `keyring` module; `.store` is what it holds."""
    store: dict[tuple[str, str], str] = {}

    def delete_password(service, name):
        if (service, name) not in store:
            raise PasswordDeleteError("not found")
        del store[(service, name)]

    return SimpleNamespace(
        store=store,
        get_keyring=lambda: backend if backend is not None else FakeOSKeyring(),
        get_password=lambda service, name: store.get((service, name)),
        set_password=lambda service, name, value: store.__setitem__((service, name), value),
        delete_password=delete_password,
        errors=SimpleNamespace(PasswordDeleteError=PasswordDeleteError),
    )


def _failing_keyring():
    cls = type("Keyring", (), {"priority": 0, "__module__": "keyring.backends.fail"})
    return _fake_keyring(cls())


def _file_backend(tmp_path, **kw):
    return sec.EncryptedFileBackend(str(tmp_path / "data" / "secrets.enc"),
                                    str(tmp_path / "conf" / "secrets.key"), **kw)


def _store(tmp_path, *, choice="auto", module=None, env=None, marker=None):
    marker = marker if marker is not None else {}
    return sec.SecretStore(
        choice=choice,
        file_backend=_file_backend(tmp_path),
        keyring_backend=sec.KeyringBackend("test", module=module or _fake_keyring()),
        env=env,
        marker_get=lambda: marker.get("v"),
        marker_set=lambda v: marker.__setitem__("v", v),
    )


def _mode(path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


# -- file backend ------------------------------------------------------------

def test_file_backend_round_trips_and_keeps_plaintext_off_disk(tmp_path):
    fb = _file_backend(tmp_path)
    key_path = tmp_path / "conf" / "secrets.key"
    assert not key_path.exists()
    fb.set("anthropic_api_key", API_KEY)
    fb.set("imap_password", PASSWORD)

    assert fb.get("anthropic_api_key") == API_KEY
    assert fb.get("imap_password") == PASSWORD
    raw = Path(fb.path).read_bytes()
    assert API_KEY.encode() not in raw and PASSWORD.encode() not in raw
    assert _mode(fb.path) == 0o600
    assert key_path.exists()
    assert _mode(key_path) == 0o600
    fb.delete("imap_password")
    assert fb.get("imap_password") is None
    fb.delete("imap_password")              # absent: no error


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_key_file_readable_by_others_is_refused(tmp_path):
    fb = _file_backend(tmp_path)
    fb.set("anthropic_api_key", API_KEY)
    key_path = tmp_path / "conf" / "secrets.key"

    os.chmod(key_path, 0o644)
    with pytest.raises(sec.SecretStoreError, match="chmod 600"):
        fb.get("anthropic_api_key")
    os.chmod(key_path, 0o640)
    with pytest.raises(sec.SecretStoreError, match="chmod 600"):
        fb.get("anthropic_api_key")
    os.chmod(key_path, 0o600)
    assert fb.get("anthropic_api_key") == API_KEY


def test_key_file_inside_the_source_tree_is_refused(tmp_path):
    root = Path(sec.__file__).resolve().parents[3]
    if not (root / ".git").exists():
        pytest.skip("not running from a git checkout")
    key = root / "backend" / "tmp-test-key"
    try:
        sec.create_key_file(str(tmp_path / "k"))
        key.write_bytes((tmp_path / "k").read_bytes())
        os.chmod(key, 0o600)
        fb = sec.EncryptedFileBackend(str(tmp_path / "s.enc"), str(key))
        with pytest.raises(sec.SecretStoreError, match="inside the source tree"):
            fb.set("anthropic_api_key", API_KEY)
        ok, err = fb.available()
        assert ok is False and "inside the source tree" in err
    finally:
        key.unlink(missing_ok=True)


def test_wrong_key_cannot_decrypt(tmp_path):
    fb = _file_backend(tmp_path)
    fb.set("anthropic_api_key", API_KEY)
    key_path = tmp_path / "conf" / "secrets.key"
    key_path.unlink()
    sec.create_key_file(str(key_path))
    with pytest.raises(sec.SecretStoreError, match="could not be decrypted"):
        fb.get("anthropic_api_key")


def test_tampered_or_swapped_entries_fail(tmp_path):
    fb = _file_backend(tmp_path)
    fb.set("anthropic_api_key", API_KEY)
    fb.set("imap_password", PASSWORD)
    path = Path(fb.path)
    original = json.loads(path.read_text())

    # Flip one byte of the ciphertext.
    doc = json.loads(json.dumps(original))
    ct = bytearray(base64.b64decode(doc["secrets"]["anthropic_api_key"]["ct"]))
    ct[0] ^= 0x01
    doc["secrets"]["anthropic_api_key"]["ct"] = base64.b64encode(bytes(ct)).decode()
    path.write_text(json.dumps(doc))
    with pytest.raises(sec.SecretStoreError, match="could not be decrypted"):
        fb.get("anthropic_api_key")

    # Swap the two entries: each is bound to its name, so neither decrypts.
    doc = json.loads(json.dumps(original))
    s = doc["secrets"]
    s["anthropic_api_key"], s["imap_password"] = s["imap_password"], s["anthropic_api_key"]
    path.write_text(json.dumps(doc))
    with pytest.raises(sec.SecretStoreError, match="could not be decrypted"):
        fb.get("anthropic_api_key")
    with pytest.raises(sec.SecretStoreError, match="could not be decrypted"):
        fb.get("imap_password")


def test_garbage_key_file_is_refused(tmp_path):
    key_path = tmp_path / "conf" / "secrets.key"
    key_path.parent.mkdir()
    key_path.write_text("not a key at all\n")
    os.chmod(key_path, 0o600)
    fb = _file_backend(tmp_path)
    with pytest.raises(sec.SecretStoreError, match="does not hold a 256-bit key"):
        fb.set("anthropic_api_key", API_KEY)


def test_unparseable_secrets_file_is_not_clobbered(tmp_path):
    fb = _file_backend(tmp_path)
    Path(fb.path).parent.mkdir(parents=True)
    Path(fb.path).write_text("{not json")
    with pytest.raises(sec.SecretStoreError, match="not a Smylte secrets file"):
        fb.set("anthropic_api_key", API_KEY)
    assert Path(fb.path).read_text() == "{not json"


def test_create_key_file_refuses_to_overwrite(tmp_path):
    path = tmp_path / "k" / "secrets.key"
    sec.create_key_file(str(path))
    before = path.read_bytes()
    assert _mode(path) == 0o600
    assert len(before.strip()) == 64
    with pytest.raises(sec.SecretStoreError, match="already exists"):
        sec.create_key_file(str(path))
    assert path.read_bytes() == before


def test_insecure_key_makes_backend_unavailable_without_raising(tmp_path):
    store = _store(tmp_path, choice="file")
    store.set("anthropic_api_key", API_KEY)
    store.reset()
    os.chmod(tmp_path / "conf" / "secrets.key", 0o644)

    ok, err = store.file_backend.available()
    assert ok is False and "chmod 600" in err
    status = store.backend_status()
    assert status == {"name": "file", "choice": "file", "available": False, "error": err}
    assert store.status("anthropic_api_key") == sec.SecretStatus(False, None, None)


# -- SecretStore ---------------------------------------------------------------

def test_env_overrides_the_store(tmp_path):
    env_key = "sk-ant-api03-FROMENVIRONMENT9876"
    store = _store(tmp_path, choice="file", env={"anthropic_api_key": env_key})
    assert store.get("anthropic_api_key") == env_key
    st = store.status("anthropic_api_key")
    assert st == sec.SecretStatus(True, "…9876", "env")

    store.set("anthropic_api_key", API_KEY)
    assert store.file_backend.get("anthropic_api_key") == API_KEY
    assert store.get("anthropic_api_key") == env_key


def test_status_hints(tmp_path):
    store = _store(tmp_path, choice="file")
    assert store.status("anthropic_api_key").as_dict() == {"set": False, "hint": None, "source": None}
    store.set("anthropic_api_key", API_KEY)
    assert store.status("anthropic_api_key").as_dict() == {"set": True, "hint": "…1234",
                                                           "source": "store"}
    store.set("imap_password", "abc12345")
    assert store.status("imap_password").hint == "…"
    assert sec.hint_for("x" * 11) == "…"
    assert sec.hint_for("x" * 8 + "abcd") == "…abcd"


def test_statuses_never_contain_a_value(tmp_path):
    store = _store(tmp_path, choice="file", env={"imap_password": PASSWORD})
    store.set("anthropic_api_key", API_KEY)
    text = json.dumps(store.statuses(), ensure_ascii=False)
    assert API_KEY not in text and PASSWORD not in text
    assert set(store.statuses()) == set(sec.SECRET_NAMES)


def test_auto_prefers_a_usable_keyring_and_pins_it(tmp_path):
    marker: dict = {}
    fake = _fake_keyring()
    store = _store(tmp_path, module=fake, marker=marker)
    assert store.backend().name == "keyring"
    store.set("anthropic_api_key", API_KEY)
    assert marker["v"] == "keyring"
    assert fake.store == {("smylte/test", "anthropic_api_key"): API_KEY}
    assert not Path(store.file_backend.path).exists()


def test_auto_falls_back_to_file_without_a_real_keyring(tmp_path):
    marker: dict = {}
    store = _store(tmp_path, module=_failing_keyring(), marker=marker)
    ok, err = store.keyring_backend.available()
    assert ok is False and "headless" in err
    assert store.backend().name == "file"
    store.set("anthropic_api_key", API_KEY)
    assert marker["v"] == "file"


def test_auto_honours_the_marker_over_a_usable_keyring(tmp_path):
    store = _store(tmp_path, module=_fake_keyring(), marker={"v": "file"})
    assert store.backend().name == "file"


def test_keyring_backend_rejects_plaintext_and_null_backends():
    plaintext = type("PlaintextKeyring", (), {"priority": 5, "__module__": "keyrings.alt.file"})
    chainer = SimpleNamespace(backends=[plaintext()])
    kb = sec.KeyringBackend(module=_fake_keyring(chainer))
    assert kb.available()[0] is False

    class Raising:
        @property
        def priority(self):
            raise RuntimeError("no dbus")

    assert sec.KeyringBackend(module=_fake_keyring(Raising())).available()[0] is False
    chainer = SimpleNamespace(backends=[Raising(), FakeOSKeyring()])
    assert sec.KeyringBackend(module=_fake_keyring(chainer)).available() == (True, None)


def test_keyring_delete_of_missing_entry_is_not_an_error():
    kb = sec.KeyringBackend(module=_fake_keyring())
    kb.delete("imap_password")


def test_keyring_error_is_wrapped_and_redacted():
    fake = _fake_keyring()

    def boom(service, name, value):
        raise RuntimeError(f"cannot store {value}")

    fake.set_password = boom
    store = sec.SecretStore(choice="keyring", file_backend=None,
                            keyring_backend=sec.KeyringBackend(module=fake), env=None,
                            marker_get=lambda: None, marker_set=lambda v: None)
    with pytest.raises(sec.SecretStoreError) as ei:
        store.set("anthropic_api_key", API_KEY)
    assert "refused the write" in str(ei.value)
    assert API_KEY not in str(ei.value)


def test_migrate_from_keyring_to_file(tmp_path):
    marker: dict = {}
    fake = _fake_keyring()
    store = _store(tmp_path, module=fake, marker=marker)
    store.set("anthropic_api_key", API_KEY)
    store.set("imap_password", PASSWORD)
    assert marker["v"] == "keyring"

    moved = store.migrate("file")
    assert moved == ["anthropic_api_key", "imap_password"]
    assert fake.store == {}
    assert marker["v"] == "file"
    assert store.backend().name == "file"
    assert store.get("anthropic_api_key") == API_KEY

    # A fresh store (the next process) reads from the file because of the marker.
    again = sec.SecretStore(choice="auto", file_backend=store.file_backend,
                            keyring_backend=store.keyring_backend, env=None,
                            marker_get=lambda: marker.get("v"), marker_set=lambda v: None)
    assert again.get("imap_password") == PASSWORD
    assert store.migrate("file") == []


def test_set_rejects_bad_values_and_names(tmp_path):
    store = _store(tmp_path, choice="file")
    with pytest.raises(sec.SecretStoreError, match="line break"):
        store.set("imap_password", "abc\ndefghij")
    with pytest.raises(sec.SecretStoreError, match="too long"):
        store.set("imap_password", "x" * (sec.MAX_SECRET_LEN + 1))
    with pytest.raises(ValueError, match="unknown secret"):
        store.set("telegram_token", "whatever-value")
    with pytest.raises(ValueError, match="unknown secret"):
        store.get("telegram_token")
    with pytest.raises(ValueError):
        sec.SecretStore(choice="vault", file_backend=None, keyring_backend=None, env=None,
                        marker_get=lambda: None, marker_set=lambda v: None)


def test_set_empty_deletes(tmp_path):
    store = _store(tmp_path, choice="file")
    store.set("imap_password", PASSWORD)
    store.set("imap_password", "   ")
    assert store.get("imap_password") is None


def test_values_are_registered_for_redaction(tmp_path):
    store = _store(tmp_path, choice="file")
    store.set("imap_password", PASSWORD)
    assert PASSWORD not in redact.redact("x " + PASSWORD)
    assert "<redacted>" in redact.redact("x " + PASSWORD)

    redact.forget_all_for_tests()
    assert store.get("imap_password") == PASSWORD
    assert "<redacted>" in redact.redact("x " + PASSWORD)


def test_default_paths(tmp_path, monkeypatch):
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert sec.default_key_path() == str(tmp_path / "xdg" / "smylte" / "secrets.key")

    creds = tmp_path / "creds"
    creds.mkdir()
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(creds))
    assert sec.default_key_path() == str(tmp_path / "xdg" / "smylte" / "secrets.key")
    (creds / sec.KEY_FILE_ENV_CREDENTIAL).write_text("x")
    assert sec.default_key_path() == str(creds / sec.KEY_FILE_ENV_CREDENTIAL)

    assert sec.default_secrets_path(str(tmp_path / "a.db")) == str(tmp_path / "secrets.enc")


def test_build_secret_store_reads_settings(tmp_path):
    settings = SimpleNamespace(
        db_path=str(tmp_path / "a.db"), secrets_file="", secrets_key_file=str(tmp_path / "k.key"),
        secrets_namespace="default", secrets_backend="file",
        anthropic_api_key="", mail_imap_password="  env-password-4321 ")
    store = sec.build_secret_store(settings, lambda: None, lambda v: None)
    assert store.file_backend.path == str(tmp_path / "secrets.enc")
    assert store.keyring_backend._service == "smylte/default"
    assert redact.redact("x env-password-4321") == "x <redacted>"   # registered at build time
    assert store.get("imap_password") == "env-password-4321"
    assert store.status("imap_password").source == "env"
    assert store.status("anthropic_api_key").source is None
