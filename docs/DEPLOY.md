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

## A. Install the app  **[SAFE]**
```bash
sudo ~/tasks/deploy/setup.sh
```
Prompts for the Radicale password and a new app login password (scrypt-hashed),
generates the session + hook secrets, writes `/etc/tasks/tasks.env` and
`/etc/tasks/hook-secret` (both 0600), installs `/usr/local/bin/tasks-notify` and
`tasks.service`, and starts it on `127.0.0.1:8080`. Check: `curl -s localhost:8080/healthz`.

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

## Backups (spec §9 — important)
Back up **both**:
- `~/radicale/collections` — the source of truth (all `.ics`).
- the app's **sidecar-class tables** from `~/tasks/backend/tasks.db`:
  `sidecar`, `list_settings`, `completions`, `attachments`, **`booking_links`**
  and **`bookings`** (every scheduling-link config plus client names/emails/
  notes — this exists nowhere on the wire). All of these are app-only state
  that a resync CANNOT rebuild (see docs/phase0-findings.md). Only the *cache*
  tables (items/collections/sync_state/FTS) are disposable — "the DB is a
  disposable cache" stopped being the whole truth when scheduling landed.

## Rollback
`sudo systemctl disable --now tasks.service`; remove the Caddy snippet + reload;
delete the tunnel's public hostname (DNS reverts); remove the Radicale `hook`
line + restart. Nothing in production Radicale's data is modified by any of this.
