# Scratch Radicale

Disposable, isolated Radicale **3.7.4** (version-matched to production) for all
development, tests, and the §6 recurrence investigation.

**This is never production.** Production is `~/radicale` on `127.0.0.1:5232`.
This is `127.0.0.1:5233` with its own storage under `./data/collections` and a
throwaway user.

| | value |
|---|---|
| URL | `http://127.0.0.1:5233` |
| User | `testuser` |
| Password | `testpass` |
| Principal | `http://127.0.0.1:5233/testuser/` |
| Storage | `./data/collections` (host-owned, uid 1000) |

## Commands

```bash
docker compose up -d --build      # start (first run builds the image)
docker compose logs -f            # tail
docker compose down               # stop, keep data
./reset.sh                        # stop + wipe all collections (fresh box)
./drop-cache.sh                   # delete .Radicale.cache -> forces invalid sync token
```

`drop-cache.sh` exists to exercise invariant #6 (an invalid/pruned sync token
must fall back to a full resync, never crash, never lose sidecar data).
