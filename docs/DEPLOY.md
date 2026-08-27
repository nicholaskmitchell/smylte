# Deployment — unified Tasks + Calendar at radicale.nicholaskmitchell.com

Public (no tailnet), gated by the app's own username/password. Raw CalDAV for
device clients moves to `radicale.nicholaskmitchell.com/dav`.

```
                              Cloudflare edge (TLS, your login is the app's own)
                                        │
                         cloudflared tunnel (dashboard-managed)
                                        │  http://127.0.0.1:9080
                              ┌─────────┴──────────┐  (public Caddy site)
                    /dav/* ──►│  Caddy path split   │──► everything else
              (X-Script-Name) │                     │
                              ▼                     ▼
                   Radicale 127.0.0.1:5232   tasksd 127.0.0.1:8080 ──► Radicale (localhost)
                     (device sync)              (web app)
```

The app authenticates to Radicale as you over localhost; Radicale is never
exposed except through the `/dav` path (Basic auth, HTTPS at the edge).

Legend: **[SAFE]** on-Pi, reversible · **[DASH]** you, in the Cloudflare dashboard
· **[PROD]** touches production Radicale/Caddy — do only with a go-ahead.

---

## 0. Build the frontend  **[SAFE]**
```bash
cd ~/tasks/frontend && npm install && npm run build   # -> dist/
```
⚠️ **Restart the service after a rebuild**: `sudo systemctl restart tasks`. The
Content-Security-Policy (below) carries a hash of the SPA's inline pre-paint
script, read from `dist/index.html` at startup — so a rebuild that changes that
script while the old process is still running leaves a stale hash, and the
browser blocks the script: a blank page. Everything else about a rebuild is
picked up without a restart, so this is the one new rule.

## A. Install the app  **[SAFE]**

### The Python the service runs on
**Supported: 3.12 and 3.13.** CI runs the full backend suite on exactly those
two (`.github/workflows/ci.yml`, job `backend`), and `setup.sh` refuses to
install onto anything else.

`setup.sh` does **not** create the venv. Its interpreter is whatever `python3`
was on the day someone ran `venv`, and it stays that version forever — including
across an OS upgrade that moves `python3` underneath it, which is exactly how
this drifted out of CI's coverage once already. A docstring defect that raises
at import on 3.13 and on no earlier version took the service down while CI, then
pinned to 3.12, was fully green.

Check what is there, and rebuild it if it is not on the list:
```bash
~/tasks/backend/.venv/bin/python -V
# if it is not 3.12.x or 3.13.x:
sudo systemctl stop tasks
cd ~/tasks/backend && rm -rf .venv
python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt
sudo systemctl start tasks && curl -s localhost:8080/healthz
```
Worth re-checking after any `apt full-upgrade` that moves the system Python.

### Run it
```bash
sudo ~/tasks/deploy/setup.sh
```
Prompts for the Radicale password and a new app login password (scrypt-hashed),
generates the session + hook secrets, writes `/etc/tasks/tasks.env` and
`/etc/tasks/hook-secret` (both 0600), installs `/usr/local/bin/tasks-notify` and
`tasks.service`, and starts it on `127.0.0.1:8080`. Check: `curl -s localhost:8080/healthz`.

The SQLite cache lives at `/var/lib/tasks/tasks.db`, which `StateDirectory=tasks`
in the unit creates and owns. It is deliberately outside the source tree: the
unit used to grant `ReadWritePaths=~/tasks/backend`, which is where `.venv` and
`tasksd` live, so a write primitive in the internet-reachable parse path could
drop a `.pth` into site-packages and survive every restart.

### Moving an existing install to /var/lib/tasks  **[PROD — one time]**
`setup.sh` leaves an existing `/etc/tasks/tasks.env` untouched, so an install
made before this change still points `TASKS_DB` at the old path — which the
narrowed sandbox no longer grants, and the service will fail to open its cache.
Move it by hand, once:
```bash
sudo systemctl stop tasks
sudo install -d -o nicholaskmitchell -g nicholaskmitchell -m 0700 /var/lib/tasks
sudo mv ~/tasks/backend/tasks.db     /var/lib/tasks/tasks.db
sudo mv ~/tasks/backend/tasks.db-wal /var/lib/tasks/ 2>/dev/null || true
sudo mv ~/tasks/backend/tasks.db-shm /var/lib/tasks/ 2>/dev/null || true
sudo chown nicholaskmitchell:nicholaskmitchell /var/lib/tasks/tasks.db*
sudo sed -i 's#^TASKS_DB=.*#TASKS_DB=/var/lib/tasks/tasks.db#' /etc/tasks/tasks.env
sudo systemctl start tasks && curl -s localhost:8080/healthz
```
Move the file rather than letting a fresh one be created: `tasks.db` holds the
sidecar-class tables under **Backups** below, and those are the one part of it a
resync cannot rebuild. Take the backup first.

## B. Public Caddy site (path split)  **[PROD — reload Caddy]**
Append `~/tasks/deploy/Caddyfile.snippet` to `/etc/caddy/Caddyfile`, then:
```bash
sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy
```
This adds an `http://127.0.0.1:9080` site: `/dav*` → Radicale (prefix stripped,
`X-Script-Name: /dav`), everything else → the app. The existing tailnet
`radicale.nkm.com { bind 100.99.99.49 }` vhost is untouched and can stay.

It also answers **RFC 6764 discovery** at the site root — `/.well-known/caldav`
and `/.well-known/carddav`, plus DAV verbs (`PROPFIND`/`REPORT`/…) on `/`, all
301 to `/dav/`. That is what makes clients which cannot be handed a path work:
Apple's CalDAV setup takes a *host*, not a URL, so it can only find `/dav` by
probing the root (step E). Only DAV methods are matched on `/`, so browsers
loading the app are unaffected. `tasksd` answers the same probes itself, so
discovery still works behind a different reverse proxy; if `/dav` ever moves,
change both this snippet and `TASKS_DAV_URL`.

## C. Tunnel + DNS  **[DASH]**
1. Zero Trust → **Networks → Tunnels → Create tunnel** (name `tasks`). Copy the token.
2. `cp ~/tasks/deploy/tasks-cloudflared.env.example ~/tasks/deploy/tasks-cloudflared.env`,
   paste the token, then:
   ```bash
   cd ~/tasks/deploy && docker compose -f tasks-cloudflared.compose.yml up -d
   ```
   (host-network connector so it can reach `127.0.0.1:9080`).
3. On the tunnel → **Public Hostname** tab → **Add a public hostname** (this is the
   same shape as notes' `notes.nkm.com → http://silverbullet:3000`):
   - **Subdomain** `radicale`, **Domain** `nicholaskmitchell.com`, Path empty
     — this is the DNS part; it has **no port**. Cloudflare auto-creates the CNAME.
   - **Service**: Type `HTTP`, URL `localhost:9080`
     — **the port goes HERE, in the Service field, never in a DNS record.**
   Do NOT hand-create a DNS record (that's why "you can't put a port in DNS" — you're
   not supposed to; the port lives in the tunnel's Service config).
   ⚠️ Adding this repoints `radicale.nkm.com` off the tailnet, through the tunnel.
   Device clients then use `.../dav` (step E).

## D. Radicale storage hook (live phone → web)  **[PROD — edit Radicale config + restart]**
This is the one sharp edge (spec §4/§10). Add to `~/radicale/config` under `[storage]`:
```
hook = /usr/local/bin/tasks-notify %(path)s
```
Optionally also `use_mtime_and_size_for_item_cache = True` (a Pi win, spec §9).
Then `sudo systemctl restart radicale`.

The hook POSTs **synchronously** (`curl --max-time 2`) and then exits — do NOT
"optimize" it into a backgrounded curl: Radicale SIGKILLs the hook's whole
process group the moment the script returns, so a backgrounded request dies
before it connects (see the header comment in `deploy/tasks-notify`). The
bounded max-time keeps the locked write from stalling more than ~2s even if
the app is down. **Søren note:** the restart briefly interrupts
Søren's calendar tools (transient); and Søren should be reloaded once so it picks
up its hardened `tools/radicale.py` (see the tasks-app-stack memory). Neither is
urgent.

Without this hook the app still works — phone changes just appear on the ~30s
poll instead of in ~1s.

## E. Point device clients at /dav  **[you, on each device]**

Which of the two forms a client wants depends on whether it accepts a **URL**
or only a **host**. Both work; they just take different fields.

**Clients that accept a full URL** — DAVx⁵, Thunderbird, jtx Board, Evolution:

    https://radicale.nicholaskmitchell.com/dav

user `nicholaskmitchell`, your Radicale password.

**Apple (macOS Calendar, iOS) — give it the host, not the URL.** Apple's CalDAV
setup has a *Server Address* field that takes a hostname and nothing else;
there is nowhere to put `/dav`, and pasting the full URL fails. This is not a
misconfiguration on our side — it is how the client works, and it is why the
server answers RFC 6764 discovery (section B): Apple probes
`/.well-known/caldav` and the bare root, gets a 301 to `/dav/`, and finds the
principal from there.

- **macOS** — Calendar → Settings → Accounts → **+** → *Other CalDAV Account* →
  Account Type **Manual** (Automatic wants an email address and will fail):
  - Username `nicholaskmitchell`
  - Password your Radicale password
  - Server Address `radicale.nicholaskmitchell.com` — **no `/dav`, no `https://`**
- **iOS/iPadOS** — Settings → Apps → Calendar → Calendar Accounts → Add Account
  → Other → *Add CalDAV Account*, same three fields.

Optional, so that bare `nicholaskmitchell.com` also resolves — RFC 6764 SRV
records in DNS (the TXT record carries the path, which is exactly the piece
Apple's field has no room for):

    _caldavs._tcp.nicholaskmitchell.com.  SRV  0 1 443 radicale.nicholaskmitchell.com.
    _caldavs._tcp.nicholaskmitchell.com.  TXT  "path=/dav/"

⚠️ **Apple shows calendars, not task lists.** iOS/macOS Reminders dropped
third-party CalDAV VTODO support in iOS 13, so an Apple account surfaces the
VEVENT calendars only. Tasks need the web app, Tasks.org/DAVx⁵, or jtx Board —
they are the same collections either way.

## F. Connect Claude (OPTIONAL)  **[PROD — edit env + restart]**

Off by default. Turning it on publishes an OAuth-protected MCP endpoint that
Claude can be added to as a custom connector.

1. In `/etc/tasks/tasks.env`:
   ```
   TASKS_MCP_ENABLED=true
   TASKS_PUBLIC_URL=https://radicale.nicholaskmitchell.com
   ```
   `TASKS_PUBLIC_URL` is required — the OAuth metadata has to state absolute
   URLs, and the value a token is bound to must match what the client was
   pointed at, so it is configured rather than read off the `Host` header. The
   app refuses to start if it is missing, or if app auth is off, or if
   `TASKS_SESSION_SECRET` is unset.
2. `sudo systemctl restart tasks`.
3. No Caddy change is needed. `/.well-known/oauth-*` and `/mcp` fall through the
   existing catch-all to the app; only `/dav*`, the two CalDAV well-knowns and
   `/internal*` are handled before it.
4. In Claude → Settings → Connectors → **Add custom connector**, give it
   `https://radicale.nicholaskmitchell.com/mcp`. Leave the OAuth Client ID and
   Secret blank: the server supports dynamic client registration, so Claude
   registers itself. A consent screen asks for your app username and password —
   that is the gate; knowing the URL is not enough — and lets you grant
   read-only instead of full access.
5. Manage or revoke connections at any time in the app: **Settings → Connected
   apps**. Disconnecting kills the access token and every refresh token from
   that approval immediately.

Anthropic's requests come from `160.79.104.0/21`; if you ever put a WAF or
Cloudflare Access in front of the app, that range needs to reach both `/mcp`
*and* the `/.well-known/oauth-*` documents, or discovery fails with the server
looking reachable.

## Verify
- `https://radicale.nicholaskmitchell.com` → login → tasks + calendar.
- `PROPFIND https://radicale.nicholaskmitchell.com/dav/nicholaskmitchell/` returns 207.
- Discovery, i.e. what Apple actually does (both must be `301` → `/dav/`):
  ```bash
  S=https://radicale.nicholaskmitchell.com
  curl -sI -X PROPFIND $S/.well-known/caldav | head -1   # HTTP/2 301
  curl -sI -X PROPFIND $S/                   | head -1   # HTTP/2 301
  curl -s -X PROPFIND $S/dav/ -u nicholaskmitchell:PASSWORD -H 'Depth: 0' \
    -H 'Content-Type: application/xml' \
    --data '<propfind xmlns="DAV:"><prop><current-user-principal/></prop></propfind>'
  # -> <current-user-principal><href>/dav/nicholaskmitchell/</href>
  ```
  A `200` with HTML instead of a `301` means the Caddy snippet is stale — the
  well-known blocks are missing and the request fell through to the web app.
- `curl -I -X OPTIONS $S/dav/nicholaskmitchell/ -u ...` advertises
  `DAV: 1, 2, 3, calendar-access` (Apple refuses the account without it).
- Change a task on the phone → appears in the web UI within ~1s (hook) or ~30s (poll).
- With the connector on, discovery answers and the endpoint challenges:
  ```bash
  S=https://radicale.nicholaskmitchell.com
  curl -s $S/.well-known/oauth-protected-resource | jq .resource   # "$S/mcp"
  curl -s $S/.well-known/oauth-authorization-server | jq .issuer    # "$S"
  curl -sI -X POST $S/mcp -H 'Content-Type: application/json' -d '{}' | grep -i www-authenticate
  # -> WWW-Authenticate: Bearer realm="smylte", resource_metadata="$S/.well-known/..."
  ```
  A `resource` that does not exactly match the URL you gave Claude — including
  the path — is the usual reason a reachable server still fails to connect.

## Content-Security-Policy

The app sets one on every response (`backend/tasksd/csp.py`). It is what bounds
where a page can fetch from at all — the field-level guards on collection colors
and appearance tokens only cover the fields they name, and this covers the rest.
Nothing to configure in Caddy; the snippet has a comment saying why it must not
set a second one.

What it allows, and why:

| Directive | Why it is not tighter |
|---|---|
| `script-src 'self' 'sha256-…'` | The hash is the SPA's inline pre-paint script (it applies your theme before first paint, so it cannot be a module). Derived from the served `dist/index.html` at startup — see the warning in §0. |
| `style-src … 'unsafe-inline' fonts.googleapis.com` | Every calendar and list color is an inline style, and the MCP consent screen is a `<style>` block, so `'unsafe-inline'` is unavoidable. The Google host is there because 13 of the Appearance font choices load a stylesheet from it. |
| `font-src 'self' fonts.gstatic.com` | Where that Google stylesheet then fetches its woff2. The shipped defaults (Fraunces/Inter/JetBrains Mono) are local and need neither host. |

Everything else is `'self'` or `'none'`. Note the privacy consequence of the two
Google entries: picking one of those font families means every page load — the
public booking page included, for visitors who are not you — tells Google the
reader's IP. Self-hosting those families would let both entries go.

**If it breaks something**, in `/etc/tasks/tasks.env`:

```
TASKS_CSP=report-only    # log violations in the browser console, block nothing
TASKS_CSP=off            # no header at all
```
then `sudo systemctl restart tasks`. Unset (or anything unrecognised) enforces —
a typo must not silently disable a security control. The policy in force is
logged at startup: `journalctl -u tasks | grep csp:`.

## If the password leaks — signing out everywhere

Sessions are JWTs, so they are valid until they expire whether or not the
browser still holds the cookie. How long that is comes from the **Stay signed
in** setting under Settings → Account (1 day / 7 days / 30 days / Never), NOT
from the env file: `TASKS_SESSION_TTL` is only the fallback used until the
account has chosen, so editing it does nothing once a choice has been stored. Logging out
withdraws one session *by name*; it cannot reach a session minted on someone
else's machine, whose id you have never seen.

Two levers, in the order to reach for them:

1. **Change the password.** Regenerate with `cd ~/tasks/backend && .venv/bin/python
   -m tasksd hash-password` — `tasksd` is not installed anywhere, so it resolves
   only from the backend directory and run from elsewhere this aborts on "No
   module named tasksd" — set `TASKS_AUTH_PASSWORD_HASH` in `/etc/tasks/tasks.env`, `sudo systemctl
   restart tasks`. Every existing session is refused from that moment: a token
   carries a fingerprint of the credentials it was minted under, so changing
   the password (or `TASKS_AUTH_USER`) invalidates all of them. This is the
   normal response, and it keeps the session secret stable.
2. **Rotate `TASKS_SESSION_SECRET`** if you have reason to think the secret
   itself leaked — it is the signing key, and anyone holding it can mint a
   valid session without the password. Set a fresh one (`python -c 'import
   secrets;print(secrets.token_hex(32))'`) and restart. Every session dies,
   including yours.

An ordinary restart signs nobody out; only a change to one of these does.

**MCP grants go with them.** Either lever also ends every OAuth grant on the
remote MCP endpoint: an access token stops answering at once and its refresh
token can no longer be exchanged, so a client cannot quietly re-arm another 30
days. Reconnect each MCP client afterwards — it will send you back through the
consent screen, which is the point. (This has not always been true: before the
`cv` column on `oauth_tokens`, both levers left every MCP grant working, and
"signing out everywhere" reached only the browser sessions.)

## Backups (spec §9 — important)
Back up **both**:
- `~/radicale/collections` — the source of truth (all `.ics`).
- the app's **sidecar-class tables** from `/var/lib/tasks/tasks.db`:
  `sidecar`, `list_settings`, `completions`, `attachments`, **`booking_links`**
  and **`bookings`** (every scheduling-link config plus client names/emails/
  notes — this exists nowhere on the wire), **`day_plan`** plus
  **`day_plan_opened`** (the Today tab's whole record: what the owner added to a
  day by hand, what they ticked, how long they expected each thing to take, what
  they moved to another day, what they dropped rather than did, and which days
  were opened at all), **`day_ritual`** (what the owner SAID about each day —
  how long they were willing to work, when they started it, when they shut it
  down, and the line they wrote about how it went; the reflections are the only
  prose in this database that exists nowhere else), and **`habits`** (the rules
  that put entries on a day — they are never PUT to Radicale and carry no RRULE,
  so the wire has no copy; losing them stops every habit recurring, though the
  occurrences already in `day_plan` keep their titles and stay readable). All of
  these are app-only
  state that a resync CANNOT rebuild (see docs/phase0-findings.md). Only the
  *cache* tables (items/collections/sync_state/FTS) are disposable — "the DB is a disposable
  cache" stopped being the whole truth when scheduling landed.

## Rollback
`sudo systemctl disable --now tasks.service`; remove the Caddy snippet + reload;
delete the tunnel's public hostname (DNS reverts); remove the Radicale `hook`
line + restart. Nothing in production Radicale's data is modified by any of this.
