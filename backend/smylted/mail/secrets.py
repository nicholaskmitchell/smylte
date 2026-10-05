"""Where the mail credentials live: the OS keyring, or a file encrypted at rest.

Smylte needs three secrets of its own — the Anthropic API key, the Bridge IMAP
password and the TypeSafe API key (for Jev, when it decides task or event) —
and the owner sets them from the settings page. They are
deliberately NOT stored in the SQLite cache: the cache is disposable by
construction, gets copied into bug reports and backups, and its schema header
promises that reading it yields no working credential.

There are two stores, and a setting (`SMYLTE_SECRETS_BACKEND`) chooses:

- **keyring** — the OS secret service (GNOME Keyring, KWallet, macOS Keychain)
  through the `keyring` package. Best on a desktop, where the secret is
  encrypted under the login session. On a headless server there is usually no
  Secret Service on D-Bus at all, and `keyring` quietly falls back to a "fail"
  backend, so `available()` checks what it would really get rather than trusting
  the import. `keyrings.alt` and the plaintext/null backends are refused: they
  would store the key in the clear while the settings page said "keyring".
- **file** — AES-256-GCM, one entry per secret, in `secrets.enc` next to the
  database, under a 256-bit key kept elsewhere (`~/.config/smylte/secrets.key`,
  or a systemd `LoadCredential=`). The key file is refused when other users can
  read it, when another user owns it, and when it sits inside the source tree —
  the one place a key is most likely to be committed by accident. The secret's
  name is the cipher's associated data, so an entry copied under the other name
  fails to decrypt instead of quietly swapping the two credentials.

`auto` prefers the keyring when one is reachable, but only until the first
write: after that a marker in the database pins the store that holds the
secrets, so a keyring that is reachable today and not tomorrow (a desktop
session that ended) cannot make the secrets silently "disappear" by switching
stores. `migrate()` moves them on purpose, verifying each copy before deleting
the original.

Environment variables (`SMYLTE_ANTHROPIC_API_KEY`, `SMYLTE_MAIL_IMAP_PASSWORD`,
`SMYLTE_TYPESAFE_API_KEY`) override both stores and are never written anywhere — for operators who already
manage secrets in their unit files.

Nothing in this module logs, prints, or puts a secret value in an exception
message. Every value read or written is registered with `redact`, so a value
that escapes through someone else's error text is still scrubbed.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import secrets
import stat
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .redact import redact_exc, register_secret

log = logging.getLogger("smylted.mail")

SECRET_NAMES: tuple[str, ...] = ("anthropic_api_key", "imap_password", "typesafe_api_key")
ENV_VARS: dict[str, str] = {"anthropic_api_key": "SMYLTE_ANTHROPIC_API_KEY",
                            "imap_password": "SMYLTE_MAIL_IMAP_PASSWORD",
                            "typesafe_api_key": "SMYLTE_TYPESAFE_API_KEY"}
# Longer than any real credential; a paste this long is a mistake (a whole
# file, a log), and storing it would only put more text through the redactor.
MAX_SECRET_LEN = 4096
KEY_FILE_ENV_CREDENTIAL = "smylte-secrets-key"   # name under $CREDENTIALS_DIRECTORY

_CHOICES = ("auto", "keyring", "file")
_FILE_VERSION = 1
_AAD_PREFIX = b"smylte-secret:v1:"
_NO_KEYRING = ("no OS keyring is reachable from this process (on a headless server there "
               "is no Secret Service); use the encrypted file store")
# Keyring backends that would accept a secret without protecting it: the
# "fail" and "null" placeholders, and keyrings.alt's plaintext files.
_REJECTED_MODULES = ("keyring.backends.fail", "keyring.backends.null", "keyrings.alt")
_REJECTED_NAMES = ("Plaintext", "Null", "Fail")


class SecretStoreError(Exception):
    """A failure whose str() is safe to show the owner: it never contains a secret."""


@dataclass(frozen=True)
class SecretStatus:
    set: bool
    hint: str | None          # "…abcd" (last 4) when len >= 12, "…" when shorter, None when unset
    source: str | None        # "env" | "store" | None

    def as_dict(self) -> dict:
        return {"set": self.set, "hint": self.hint, "source": self.source}


def _check_name(name: str) -> None:
    if name not in SECRET_NAMES:
        raise ValueError(f"unknown secret {name!r}")


def hint_for(value: str) -> str:
    """Enough of a value to recognise it, and no more.

    Four characters of a long key tell the owner which key is saved; four of a
    short password would be a real share of it, so short values get none.
    """
    return "…" + value[-4:] if len(value) >= 12 else "…"


def default_key_path() -> str:
    """The systemd credential when the unit provides one, else ~/.config/smylte/secrets.key."""
    cred_dir = os.environ.get("CREDENTIALS_DIRECTORY")
    if cred_dir:
        candidate = os.path.join(cred_dir, KEY_FILE_ENV_CREDENTIAL)
        if os.path.exists(candidate):
            return candidate
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "smylte", "secrets.key")


def default_secrets_path(db_path: str) -> str:
    """`secrets.enc` in the database's directory — on the same backup path, never in the DB."""
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), "secrets.enc")


# ---------------------------------------------------------------------------
# OS keyring


class KeyringBackend:
    """The OS secret service, via the `keyring` package.

    `keyring` is imported inside each method, never at module import: on a
    headless box merely importing it can go looking for D-Bus, and building the
    app must not do that.
    """

    name = "keyring"

    def __init__(self, namespace: str = "default", *, module=None):
        self._service = f"smylte/{namespace}"
        self._module = module

    def _kr(self):
        if self._module is not None:
            return self._module
        try:
            import keyring
        except ImportError:
            raise SecretStoreError("the keyring package is not installed") from None
        return keyring

    def available(self) -> tuple[bool, str | None]:
        """Whether a backend that really protects secrets is reachable.

        `keyring` never says "no": without a Secret Service it hands back a
        chainer whose only member is the fail backend (priority 0), or a
        plaintext one if keyrings.alt is installed. So the answer is computed
        from the backends it would actually use.
        """
        try:
            module = self._kr()
        except SecretStoreError as e:
            return False, str(e)
        try:
            kr = module.get_keyring()
            if type(kr).__name__ == "ChainerBackend" or hasattr(kr, "backends"):
                candidates = list(kr.backends)
            else:
                candidates = [kr]
        except Exception:  # noqa: BLE001 — any failure here means "not usable"
            return False, _NO_KEYRING
        for b in candidates:
            if _usable(b):
                return True, None
        return False, _NO_KEYRING

    def get(self, name: str) -> str | None:
        _check_name(name)
        module = self._kr()
        try:
            return module.get_password(self._service, name)
        except Exception as exc:  # noqa: BLE001
            raise SecretStoreError(f"the OS keyring refused the read: {redact_exc(exc)}") from None

    def set(self, name: str, value: str) -> None:
        _check_name(name)
        module = self._kr()
        try:
            module.set_password(self._service, name, value)
        except Exception as exc:  # noqa: BLE001
            raise SecretStoreError(f"the OS keyring refused the write: {redact_exc(exc)}") from None

    def delete(self, name: str) -> None:
        _check_name(name)
        module = self._kr()
        not_found = getattr(getattr(module, "errors", None), "PasswordDeleteError", None)
        try:
            module.delete_password(self._service, name)
        except Exception as exc:  # noqa: BLE001
            # Deleting what is not there is what the caller wanted anyway.
            if (not_found is not None and isinstance(exc, not_found)) \
                    or type(exc).__name__ == "PasswordDeleteError":
                return
            raise SecretStoreError(f"the OS keyring refused the delete: {redact_exc(exc)}") from None


def _usable(backend) -> bool:
    """A keyring backend with positive priority that is not a fail/null/plaintext one."""
    try:
        if not backend.priority > 0:
            return False
    except Exception:  # noqa: BLE001 — `priority` raises when the backend cannot run here
        return False
    cls = type(backend)
    module = cls.__module__ or ""
    if any(module.startswith(m) for m in _REJECTED_MODULES):
        return False
    return not any(word in cls.__name__ for word in _REJECTED_NAMES)


# ---------------------------------------------------------------------------
# Encrypted file


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_key_path(key_path: str) -> str:
    """Absolute key path; refuses one inside the source checkout.

    A key next to the code is one `git add -A` away from being published along
    with it, and then the encrypted file protects nothing.
    """
    path = os.path.abspath(os.path.expanduser(key_path))
    root = _repo_root()
    if (root / ".git").exists() and Path(path).resolve().is_relative_to(root):
        raise SecretStoreError(
            f"refusing to use {path} as the secrets key: it is inside the source tree. "
            "Keep the key outside the repository (default: ~/.config/smylte/secrets.key).")
    return path


def _no_key_message(path: str, strerror: str | None = None) -> str:
    created = f" and it could not be created ({strerror})" if strerror is not None else ""
    return (f"no secrets key at {path}{created}. "
            f"Create one with: python -m smylted secrets init-key --path {path}")


def _write_new_key(path: str) -> None:
    """Create `path` holding a fresh random key, mode 0600; FileExistsError if present."""
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        if os.name != "nt":
            os.fchmod(fd, 0o600)  # the mode argument is masked by umask; this is not
        os.write(fd, (secrets.token_hex(32) + "\n").encode("ascii"))
        os.fsync(fd)
    finally:
        os.close(fd)


def create_key_file(path: str) -> None:
    """Create a new key file at `path` (the CLI's `init-key`). Never overwrites."""
    resolved = _resolve_key_path(path)
    try:
        _write_new_key(resolved)
    except FileExistsError:
        raise SecretStoreError(f"{resolved} already exists") from None
    except OSError as exc:
        raise SecretStoreError(_no_key_message(resolved, exc.strerror)) from None


def _parse_key(data: bytes, path: str) -> bytes:
    """64 hex characters (trailing whitespace allowed), or exactly 32 raw bytes."""
    if len(data) == 32:
        return data
    text = data.rstrip()
    if len(text) == 64:
        try:
            return bytes.fromhex(text.decode("ascii"))
        except (UnicodeDecodeError, ValueError):
            pass
    raise SecretStoreError(f"{path} does not hold a 256-bit key")


def _dir_creatable(directory: str) -> bool:
    """Whether `directory` exists and is writable, or its nearest existing ancestor is."""
    d = os.path.abspath(directory)
    while not os.path.exists(d):
        parent = os.path.dirname(d)
        if parent == d:
            return False
        d = parent
    return os.path.isdir(d) and os.access(d, os.W_OK | os.X_OK)


class EncryptedFileBackend:
    """Secrets encrypted with AES-256-GCM in one JSON file, under a key kept elsewhere."""

    name = "file"

    def __init__(self, path: str, key_path: str, *, create_key: bool = True):
        self.path = os.path.abspath(os.path.expanduser(path))
        self.key_path = key_path
        self.create_key = create_key
        # Serialises read-modify-write: two settings saves in two worker threads
        # must not each write back a file missing the other's entry.
        self._lock = threading.Lock()

    # -- key ---------------------------------------------------------------

    def _load_key(self) -> bytes:
        path = _resolve_key_path(self.key_path)
        try:
            st = os.stat(path)
        except FileNotFoundError:
            raise SecretStoreError(_no_key_message(path)) from None
        except OSError as exc:
            raise SecretStoreError(f"could not read the secrets key {path} ({exc.strerror})") from None
        if not stat.S_ISREG(st.st_mode):
            raise SecretStoreError(f"{path} is not a regular file")
        if os.name != "nt":
            # Group access is refused too, not just "world": the key should be
            # the service user's alone, which is what 0600 says.
            if st.st_mode & 0o077:
                raise SecretStoreError(
                    f"refusing to load the secrets key: {path} is readable or writable by other "
                    f"users (mode {oct(st.st_mode & 0o777)}). Fix it with: chmod 600 {path}")
            if st.st_uid not in (os.geteuid(), 0):
                raise SecretStoreError(
                    f"refusing to load the secrets key: {path} is owned by another user")
        try:
            with open(path, "rb") as f:
                data = f.read(4096)
        except OSError as exc:
            raise SecretStoreError(f"could not read the secrets key {path} ({exc.strerror})") from None
        return _parse_key(data, path)

    def _ensure_key(self) -> bytes:
        path = _resolve_key_path(self.key_path)
        if not os.path.exists(path):
            if not self.create_key:
                raise SecretStoreError(_no_key_message(path))
            try:
                _write_new_key(path)
            except FileExistsError:
                pass  # created by someone else in the meantime; load theirs
            except OSError as exc:
                raise SecretStoreError(_no_key_message(path, exc.strerror)) from None
            log.info("mail: created a new secrets key at %s", path)
        return self._load_key()

    def available(self) -> tuple[bool, str | None]:
        try:
            path = _resolve_key_path(self.key_path)
            if os.path.exists(path):
                self._load_key()
                return True, None
        except SecretStoreError as e:
            return False, str(e)
        if self.create_key and _dir_creatable(os.path.dirname(path)):
            return True, None
        return False, _no_key_message(path)

    # -- file --------------------------------------------------------------

    def _not_ours(self) -> SecretStoreError:
        return SecretStoreError(f"{self.path} is not a Smylte secrets file")

    def _read(self) -> dict[str, dict]:
        try:
            with open(self.path, "rb") as f:
                raw = f.read()
        except FileNotFoundError:
            return {}
        except OSError as exc:
            raise SecretStoreError(f"could not read {self.path} ({exc.strerror})") from None
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise self._not_ours() from None
        if not isinstance(doc, dict) or doc.get("version") != _FILE_VERSION \
                or not isinstance(doc.get("secrets"), dict):
            raise self._not_ours()
        entries = doc["secrets"]
        for entry in entries.values():
            if not isinstance(entry, dict) or not isinstance(entry.get("nonce"), str) \
                    or not isinstance(entry.get("ct"), str):
                raise self._not_ours()
        return entries

    def _write(self, entries: dict[str, dict]) -> None:
        """Replace the file atomically: a crash leaves the old file or the new, never half."""
        body = json.dumps({"version": _FILE_VERSION, "secrets": entries},
                          indent=2, sort_keys=True).encode("utf-8")
        tmp = self.path + ".tmp"
        try:
            os.makedirs(os.path.dirname(self.path), mode=0o700, exist_ok=True)
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                if os.name != "nt":
                    os.fchmod(fd, 0o600)  # umask-proof, and fixes a stale tmp's mode
                os.write(fd, body)
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(tmp, self.path)
        except OSError as exc:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise SecretStoreError(f"could not write {self.path} ({exc.strerror})") from None

    @staticmethod
    def _aad(name: str) -> bytes:
        return _AAD_PREFIX + name.encode()

    def get(self, name: str) -> str | None:
        _check_name(name)
        from cryptography.exceptions import InvalidTag
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        entry = self._read().get(name)
        if entry is None:
            return None
        key = self._load_key()
        try:
            nonce = base64.b64decode(entry["nonce"], validate=True)
            ct = base64.b64decode(entry["ct"], validate=True)
        except ValueError:
            raise self._not_ours() from None
        try:
            plain = AESGCM(key).decrypt(nonce, ct, self._aad(name))
        except (InvalidTag, ValueError):
            raise SecretStoreError(
                f"the secrets file {self.path} could not be decrypted with "
                f"{_resolve_key_path(self.key_path)} (wrong key, or the file was altered)") from None
        try:
            return plain.decode("utf-8")
        except UnicodeDecodeError:
            raise self._not_ours() from None

    def set(self, name: str, value: str) -> None:
        _check_name(name)
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        key = self._ensure_key()
        with self._lock:
            entries = self._read()   # refuses a file it cannot parse rather than clobbering it
            nonce = os.urandom(12)
            ct = AESGCM(key).encrypt(nonce, value.encode("utf-8"), self._aad(name))
            entries[name] = {"nonce": base64.b64encode(nonce).decode("ascii"),
                             "ct": base64.b64encode(ct).decode("ascii")}
            self._write(entries)

    def delete(self, name: str) -> None:
        _check_name(name)
        with self._lock:
            entries = self._read()
            if name not in entries:
                return
            del entries[name]
            self._write(entries)


# ---------------------------------------------------------------------------
# The store the app uses


class SecretStore:
    """Environment overrides on top of one chosen backend.

    `marker_get` / `marker_set` read and write which backend holds the secrets
    (a row in the database's `meta` table); they are callables so this module
    does not need to know about the service lock.
    """

    def __init__(self, *, choice: str, file_backend, keyring_backend,
                 env: Mapping[str, str] | None,
                 marker_get: Callable[[], str | None], marker_set: Callable[[str], None]):
        if choice not in _CHOICES:
            raise ValueError(f"secrets backend must be one of {', '.join(_CHOICES)}")
        self.choice = choice
        self.file_backend = file_backend
        self.keyring_backend = keyring_backend
        self._env = dict(env or {})
        self._marker_get = marker_get
        self._marker_set = marker_set
        self._resolved = None

    def reset(self) -> None:
        """Forget the resolved backend, so the next call chooses again."""
        self._resolved = None

    def _choose(self):
        if self.choice == "keyring":
            return self.keyring_backend
        if self.choice == "file":
            return self.file_backend
        marker = self._marker_get()
        if marker == "keyring":
            return self.keyring_backend
        if marker == "file":
            return self.file_backend
        if self.keyring_backend.available()[0]:
            return self.keyring_backend
        return self.file_backend

    def backend(self):
        """The backend secrets are read from and written to; SecretStoreError if unusable."""
        if self._resolved is not None:
            return self._resolved
        chosen = self._choose()
        ok, err = chosen.available()
        if not ok:
            raise SecretStoreError(err)
        self._resolved = chosen
        return chosen

    def backend_status(self) -> dict:
        """What the settings page shows about the store. Never raises."""
        try:
            b = self.backend()
            return {"name": b.name, "choice": self.choice, "available": True, "error": None}
        except Exception as e:  # noqa: BLE001
            error = str(e) if isinstance(e, SecretStoreError) else redact_exc(e)
        try:
            name = self._choose().name
        except Exception:  # noqa: BLE001
            name = None
        return {"name": name, "choice": self.choice, "available": False, "error": error}

    def _env_value(self, name: str) -> str | None:
        v = self._env.get(name)
        return v if v else None

    def get(self, name: str) -> str | None:
        _check_name(name)
        v = self._env_value(name)
        if v:
            register_secret(v)
            return v
        v = self.backend().get(name)
        if v:
            register_secret(v)
        return v

    def status(self, name: str) -> SecretStatus:
        _check_name(name)
        v = self._env_value(name)
        if v:
            return SecretStatus(True, hint_for(v), "env")
        try:
            v = self.backend().get(name)
        except SecretStoreError:
            return SecretStatus(False, None, None)
        if v:
            register_secret(v)
        return SecretStatus(bool(v), hint_for(v) if v else None, "store" if v else None)

    def statuses(self) -> dict[str, dict]:
        return {name: self.status(name).as_dict() for name in SECRET_NAMES}

    def set(self, name: str, value: str) -> None:
        """Store `value` (stripped); an empty value deletes the secret."""
        _check_name(name)
        value = value.strip()
        if not value:
            self.delete(name)
            return
        if len(value) > MAX_SECRET_LEN:
            raise SecretStoreError("that value is too long to be a credential")
        if "\n" in value or "\r" in value:
            raise SecretStoreError("a credential cannot contain a line break")
        # Registered before the write, so a backend error that echoes the
        # value is already scrubbed when it is formatted.
        register_secret(value)
        b = self.backend()
        b.set(name, value)
        if self._marker_get() != b.name:
            self._marker_set(b.name)

    def delete(self, name: str) -> None:
        _check_name(name)
        self.backend().delete(name)

    def migrate(self, to: str) -> list[str]:
        """Move every stored secret to the `to` backend; returns the names moved.

        Copies all first and reads each copy back before deleting anything from
        the source, so a failure part-way leaves every secret readable from the
        backend the marker still names.
        """
        if to not in ("keyring", "file"):
            raise ValueError("migrate to 'keyring' or 'file'")
        src = self.backend()
        if src.name == to:
            return []
        dst = self.file_backend if to == "file" else self.keyring_backend
        ok, err = dst.available()
        if not ok:
            raise SecretStoreError(err)
        moved: list[str] = []
        for name in SECRET_NAMES:
            v = src.get(name)
            if not v:
                continue
            register_secret(v)
            dst.set(name, v)
            if dst.get(name) != v:
                raise SecretStoreError(f"verification failed after copying {name}")
            moved.append(name)
        for name in moved:
            src.delete(name)
        self._marker_set(to)
        self._resolved = dst
        log.info("mail: moved secrets %s from %s to %s", ", ".join(moved) or "(none)", src.name, to)
        return moved


def build_secret_store(settings, marker_get, marker_set) -> SecretStore:
    """The app's store, from `smylted.config.Settings`."""
    file_backend = EncryptedFileBackend(
        settings.secrets_file or default_secrets_path(settings.db_path),
        settings.secrets_key_file or default_key_path())
    keyring_backend = KeyringBackend(settings.secrets_namespace)
    env: dict[str, str] = {}
    for name, value in (("anthropic_api_key", settings.anthropic_api_key),
                        ("imap_password", settings.mail_imap_password),
                        ("typesafe_api_key", settings.typesafe_api_key)):
        value = (value or "").strip()
        if value:
            register_secret(value)
            env[name] = value
    return SecretStore(choice=settings.secrets_backend, file_backend=file_backend,
                       keyring_backend=keyring_backend, env=env,
                       marker_get=marker_get, marker_set=marker_set)
