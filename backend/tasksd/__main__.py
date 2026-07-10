"""CLI entrypoint.

  python -m tasksd hash-password    # generate a scrypt hash for TASKS_AUTH_PASSWORD_HASH
  python -m tasksd                  # run the server on 127.0.0.1:8080
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

    import uvicorn

    uvicorn.run(
        "tasksd.app:make",
        factory=True,
        host="127.0.0.1",
        port=8080,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
