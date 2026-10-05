"""CLI entrypoint.

  python -m smylted hash-password    # generate a scrypt hash for SMYLTE_AUTH_PASSWORD_HASH
  python -m smylted secrets status   # which secret store is used, which mail secrets are set
  python -m smylted secrets init-key [--path P]   # create the file store's key (mode 0600)
  python -m smylted secrets set NAME              # store a secret (prompted, never argv)
  python -m smylted secrets clear NAME            # delete a stored secret
  python -m smylted secrets migrate --to file|keyring
  python -m smylted                  # run the server on 127.0.0.1:8080
"""
from __future__ import annotations

import getpass
import sys

from .auth import hash_password


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] == "hash-password":
        pw = getpass.getpass("Password: ")
        if pw != getpass.getpass("Confirm : "):
            print("passwords do not match", file=sys.stderr)
            return 1
        if len(pw) < 8:
            print("warning: password shorter than 8 characters", file=sys.stderr)
        print(hash_password(pw))
        return 0
    if args and args[0] == "secrets":
        from .mail.cli import secrets_main

        return secrets_main(args[1:])

    import uvicorn

    uvicorn.run(
        "smylted.app:make",
        factory=True,
        host="127.0.0.1",
        port=8080,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
