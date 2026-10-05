"""`python -m smylted secrets ...` — manage the mail credentials from a shell.

For the operator who would rather not type a key into a web form, and for the
one-off jobs a web form should not do: creating the file store's key with the
right mode, and moving the secrets between the keyring and the file.

Values are read with `getpass`, never from argv: an argument is visible to
every user on the box in `ps` and lands in shell history. Nothing here prints a
value — `status` shows the same four-character hint the settings page does.

It opens the same database as the server, only to read and write which store
holds the secrets (the marker `auto` relies on) and the Bridge password's
binding (below), and closes it again. Running it beside a live server is
fine: SQLite in WAL mode with a busy timeout, and one-row writes.

A shell does not have the service's environment, and a CLI that quietly used
other paths would store a secret the service never reads. So every command
first prints the database, store and file paths it is using — from the same
`Settings` the service builds them from — and only `init-key` creates a key:
the other commands report a missing one instead of creating a second key
beside the service's.

The Bridge password is only ever sent to the server it was saved for (see
`settings.connection_binding`), and the service refuses a stored password with
no binding. So `set imap_password` binds it to the server settings saved in
the database at that moment, as saving it in Settings does, and says which
host and user that was — the shell operator is trusted as much as the
environment variable, which is bound the same way at startup. Refusing the
password here and pointing at Settings was the alternative; it would leave
the documented command storing a password that can never be used. The server
has to be set in Settings first: changing it afterwards forgets the password.
`clear imap_password` clears the binding with it.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys

from ..config import Settings
from ..db import store
from .redact import redact
from .secrets import (
    SECRET_NAMES,
    SecretStore,
    SecretStoreError,
    build_secret_store,
    create_key_file,
    default_key_path,
)
from .settings import MAIL_SETTINGS_KEY, SECRETS_MARKER_KEY, connection_binding, load


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m smylted secrets",
                                description="Manage the email-ingestion credentials.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="show which store is used and which secrets are set")
    init = sub.add_parser("init-key", help="create the encrypted file store's key (mode 0600)")
    init.add_argument("--path", default=None,
                      help="where to create it (default: SMYLTE_SECRETS_KEY_FILE or "
                           "~/.config/smylte/secrets.key)")
    setp = sub.add_parser("set", help="store a secret (the value is prompted for)")
    setp.add_argument("name", choices=SECRET_NAMES)
    clear = sub.add_parser("clear", help="delete a stored secret")
    clear.add_argument("name", choices=SECRET_NAMES)
    mig = sub.add_parser("migrate", help="move every stored secret to the other store")
    mig.add_argument("--to", required=True, choices=("file", "keyring"))
    return p


def _abspath(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _print_paths(settings: Settings, secrets: SecretStore) -> dict:
    """Print where this command reads and writes (paths only); the backend status."""
    b = secrets.backend_status()
    print(f"database: {_abspath(settings.db_path)}")
    print(f"backend: {b['name'] or 'none'} (choice {b['choice']})")
    print(f"secrets file: {secrets.file_backend.path}")
    print(f"key file: {_abspath(secrets.file_backend.key_path)}")
    return b


def _run(args: argparse.Namespace, settings: Settings) -> int:
    if args.cmd == "init-key":
        path = args.path or settings.secrets_key_file or default_key_path()
        print(f"key file: {_abspath(path)}")
        create_key_file(path)
        print(f"created {path} (mode 0600)")
        return 0

    conn = store.connect(settings.db_path)
    try:
        store.init_db(conn)
        secrets = build_secret_store(
            settings,
            lambda: store.get_meta(conn, SECRETS_MARKER_KEY),
            lambda v: store.set_meta(conn, SECRETS_MARKER_KEY, v),
            create_key=False,
        )
        b = _print_paths(settings, secrets)
        if args.cmd == "status":
            if not b["available"]:
                print(f"unavailable: {b['error']}")
            for name, st in secrets.statuses().items():
                state = "set" if st["set"] else "unset"
                extra = f" {st['hint']} from {st['source']}" if st["set"] else ""
                print(f"{name}: {state}{extra}")
            return 0
        if args.cmd == "set":
            value = getpass.getpass(f"{args.name}: ")
            if not value.strip():
                print("nothing entered; nothing stored (use `clear` to delete)", file=sys.stderr)
                return 1
            secrets.set(args.name, value)
            print(f"{args.name} stored in {secrets.backend().name}")
            if args.name == "imap_password":
                cfg = load(store.get_meta_json(conn, MAIL_SETTINGS_KEY))
                store.merge_meta_json(conn, MAIL_SETTINGS_KEY,
                                      {"imap_password_binding": connection_binding(cfg)})
                print(f"bound to {cfg.imap_host}:{cfg.imap_port} ({cfg.imap_tls}) as "
                      f"{cfg.imap_username or '(no username)'}; set the server in Settings "
                      "first — changing it later forgets the password")
            return 0
        if args.cmd == "clear":
            secrets.delete(args.name)
            if args.name == "imap_password":
                store.merge_meta_json(conn, MAIL_SETTINGS_KEY, {"imap_password_binding": ""})
            print(f"{args.name} cleared")
            return 0
        if args.cmd == "migrate":
            moved = secrets.migrate(args.to)
            print(f"moved to {args.to}: {', '.join(moved) or 'nothing'}")
            return 0
    finally:
        conn.close()
    return 1  # unreachable: argparse refuses an unknown command


def secrets_main(argv: list[str]) -> int:
    """Entry point for `python -m smylted secrets ARGS`; 0 on success, 1 on error."""
    args = _parser().parse_args(argv)
    try:
        return _run(args, Settings.from_env())
    except (SecretStoreError, ValueError, OSError) as e:
        print(f"error: {redact(str(e))}", file=sys.stderr)
        return 1
