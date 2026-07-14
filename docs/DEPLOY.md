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
DAVx⁵ / Thunderbird base URL: `https://radicale.nicholaskmitchell.com/dav`
(user `nicholaskmitchell`, your Radicale password).

## Verify
- `https://radicale.nicholaskmitchell.com` → login → tasks + calendar.
- `PROPFIND https://radicale.nicholaskmitchell.com/dav/nicholaskmitchell/` returns 207.
- Change a task on the phone → appears in the web UI within ~1s (hook) or ~30s (poll).

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
