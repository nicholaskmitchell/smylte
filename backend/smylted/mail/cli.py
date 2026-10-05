"""`python -m smylted secrets ...` — manage the mail credentials from a shell.

For the operator who would rather not type a key into a web form, and for the
one-off jobs a web form should not do: creating the file store's key with the
right mode, and moving the secrets between the keyring and the file.

Values are read with `getpass`, never from argv: an argument is visible to
every user on the box in `ps` and lands in shell history. Nothing here prints a
value — `status` shows the same four-character hint the settings page does.

It opens the same database as the server, only to read and write which store
holds the secrets (the marker `auto` relies on), and closes it again. Running
it beside a live server is fine: SQLite in WAL mode with a busy timeout, and a
one-row write.
"""
from __future__ import annotations

import argparse
import getpass
import sys

from ..config import Settings
from ..db import store
from .redact import redact
from .secrets import (
    SECRET_NAMES,
    SecretStoreError,
    build_secret_store,
    create_key_file,
    default_key_path,
)
from .settings import SECRETS_MARKER_KEY


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


def _run(args: argparse.Namespace, settings: Settings) -> int:
    if args.cmd == "init-key":
        path = args.path or settings.secrets_key_file or default_key_path()
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
        )
        if args.cmd == "status":
            b = secrets.backend_status()
            line = f"backend: {b['name'] or 'none'} (choice {b['choice']})"
            if not b["available"]:
                line += f" — unavailable: {b['error']}"
            print(line)
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
            return 0
        if args.cmd == "clear":
            secrets.delete(args.name)
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
