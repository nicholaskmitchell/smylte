# Deployment

Smylte runs as a systemd service next to Radicale, behind a reverse proxy that
sends `/dav` to Radicale and everything else to the app. The app signs in to
Radicale over localhost, so Radicale is only reachable through `/dav`.

```
                 HTTPS (your proxy, or a Cloudflare tunnel)
                                  │
                       ┌──────────┴──────────┐
             /dav/* ──►│  Caddy path split    │──► everything else
                       └──────────┬──────────┘
                     ▼                         ▼
          Radicale 127.0.0.1:5232     smylted 127.0.0.1:8080 ──► Radicale
            (device sync)               (web app)
```

This guide uses `smylte.example.com` as the hostname, `<user>` as the account
that runs the service, and `~/smylte` as the checkout. The templates in
`deploy/` are filled in for one particular deployment. Before installing, edit
`User=`, `Group=`, `WorkingDirectory=` and `ExecStart=` in `deploy/smylte.service`,
`USER_NAME` in `deploy/setup.sh`, and the hostnames in
`deploy/Caddyfile.snippet` and `deploy/smylte.env.example`.

## Requirements

- A Linux host with systemd, and Radicale already running on `127.0.0.1:5232`.
- **Python 3.12 or 3.13.** CI tests exactly these (`.github/workflows/ci.yml`),
  and `setup.sh` refuses anything else.
- Node.js, to build the frontend.
- Caddy (or another reverse proxy), and optionally `cloudflared`.

## 1. Build the frontend

```bash
cd ~/smylte/frontend && npm install && npm run build   # -> dist/
```

**Restart the service after every rebuild** (`sudo systemctl restart smylte`).
The Content-Security-Policy includes a hash of the SPA's inline pre-paint script,
read from `dist/index.html` at startup. A stale hash blocks the script, and the
page loads blank.

## 2. Install the app

`setup.sh` doesn't create the venv. Create it with a supported Python, and
rebuild it if an OS upgrade moves `python3` to an untested version:

```bash
cd ~/smylte/backend
python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -V    # must be 3.12.x or 3.13.x
```

Then:

```bash
sudo ~/smylte/deploy/setup.sh
curl -s localhost:8080/healthz
```

`setup.sh` asks for the Radicale password and a new app password (stored as an
scrypt hash), generates the session and hook secrets, writes
`/etc/smylte/smylte.env` and `/etc/smylte/hook-secret` (both 0600), installs
`/usr/local/bin/smylte-notify` and `smylte.service`, and starts the app on
`127.0.0.1:8080`. It leaves an existing env file untouched.

The database is at `/var/lib/smylte/smylte.db`, created by
`StateDirectory=smylte` in the unit. It is kept outside the source tree so the
service has no write access to its own code or venv.

## 3. Reverse proxy

Append `deploy/Caddyfile.snippet` to `/etc/caddy/Caddyfile`, then:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy
```

This adds a loopback site on `:9080`: `/dav*` goes to Radicale (prefix stripped,
`X-Script-Name: /dav`) and everything else to the app. Don't set a second
Content-Security-Policy in the proxy; the app sends its own.

The snippet also answers **RFC 6764 discovery**: `/.well-known/caldav`,
`/.well-known/carddav` and DAV methods on `/` redirect to `/dav/`. Apple's
clients need this because they take a hostname, not a URL. Browsers loading the
app aren't affected. `smylted` answers the same probes itself, so discovery
works behind other proxies too. If `/dav` moves, change both the snippet and
`SMYLTE_DAV_URL`.

## 4. Cloudflare tunnel (optional)

1. In Cloudflare Zero Trust, go to **Networks → Tunnels → Create tunnel** and
   copy the token.
2. Copy `deploy/smylte-cloudflared.env.example` to
   `deploy/smylte-cloudflared.env`, paste the token, and start the connector:
   ```bash
   cd ~/smylte/deploy && docker compose -f smylte-cloudflared.compose.yml up -d
   ```
3. On the tunnel's **Public Hostname** tab, add `smylte.example.com` with service
   type `HTTP` and URL `localhost:9080`. The port goes in the service field, not
   in DNS. Cloudflare creates the DNS record.

## 5. Radicale storage hook

Add this under `[storage]` in Radicale's config, then restart Radicale:

```
hook = /usr/local/bin/smylte-notify %(path)s
```

The hook tells the app about changes from other clients within about a second.
Without it, they appear on the 30-second poll. The hook's request is synchronous
on purpose (`curl --max-time 2`): Radicale kills the hook's process group as soon
as it returns, so a backgrounded request never connects. Optionally add
`use_mtime_and_size_for_item_cache = True`, which helps on slow storage.

## 6. Device clients

**Clients that take a URL** (DAVx⁵, Thunderbird, jtx Board, Evolution):

    https://smylte.example.com/dav

with your Radicale username and password.

**Apple clients take a hostname only.** Enter `smylte.example.com` with no
`https://` and no `/dav`. Discovery finds the rest.

- **macOS:** Calendar → Settings → Accounts → **+** → *Other CalDAV Account* →
  Account Type **Manual**.
- **iOS/iPadOS:** Settings → Apps → Calendar → Calendar Accounts → Add Account →
  Other → *Add CalDAV Account*.

To make the bare domain work too, add SRV and TXT records:

    _caldavs._tcp.example.com.  SRV  0 1 443 smylte.example.com.
    _caldavs._tcp.example.com.  TXT  "path=/dav/"

Apple's Reminders dropped CalDAV task support in iOS 13, so Apple devices show
calendars only. Use the web app, Tasks.org or jtx Board for tasks.

## 7. Auto-deploy from `main` (optional)

`deploy/smylte-autopull.sh` fast-forwards the checkout, reinstalls backend
dependencies if `requirements.txt` changed, rebuilds the frontend if
`frontend/` changed, applies pending unprivileged migrations, and restarts the
service. It never handles a non-fast-forward pull and uses `flock` so runs don't
overlap. Install a copy (not a symlink, since it pulls the tree it lives in) and
re-copy it when it changes:

```bash
cp ~/smylte/deploy/smylte-autopull.sh ~/smylte-autopull.sh && chmod +x ~/smylte-autopull.sh
echo "$(id -un) ALL=(root) NOPASSWD: /usr/bin/systemctl restart smylte.service" \
  | sudo tee /etc/sudoers.d/smylte-autopull && sudo chmod 440 /etc/sudoers.d/smylte-autopull
crontab -e     # * * * * * $HOME/smylte-autopull.sh
```

The log is `~/smylte-autopull.log`.

## 8. Upgrades and migrations

Changes outside the source tree (the unit, `/etc/smylte`, Radicale's hook line)
are applied by `deploy/migrate.sh`. Preview before running anything as root:

```bash
cd ~/smylte
./deploy/migrate.sh --status     # what is pending, and what needs root
./deploy/migrate.sh --dry-run    # print the actions, change nothing
sudo ./deploy/migrate.sh         # apply
```

Back up first (see [Backups](#backups)). Re-running is a no-op, and an
interrupted run resumes. Progress is kept in `~/.smylte-migration-level`.
Autopull runs `migrate.sh --auto`, which applies migrations that don't need
root. For one that does, it logs the command, leaves the old service running
instead of restarting, and sends one Telegram message if notifications are set
up. New migrations go in `deploy/migrations/` as `NNNN-slug.sh`, defining
`NEEDS_ROOT`, `describe()`, `applies()` and `apply()`.

**Installs from before the rename** (`tasks.service`, `/etc/tasks`,
`/var/lib/tasks`, `~/tasks`, `TASKS_*` variables) are moved by migrations 0001
and 0002. Run the commands above from `~/tasks`, and don't migrate by hand. The
old autopull script doesn't call `migrate.sh`, so it won't prompt you. Until you
migrate, a `tasksd` shim and the `TASKS_*` fallback in `config.py` keep the old
unit working.

## 9. Verify

```bash
S=https://smylte.example.com
curl -sI -X PROPFIND $S/.well-known/caldav | head -1   # 301
curl -sI -X PROPFIND $S/                   | head -1   # 301
curl -s -X PROPFIND $S/dav/ -u <user>:PASSWORD -H 'Depth: 0' \
  -H 'Content-Type: application/xml' \
  --data '<propfind xmlns="DAV:"><prop><current-user-principal/></prop></propfind>'
# -> <current-user-principal><href>/dav/<user>/</href>
curl -sI -X OPTIONS $S/dav/<user>/ -u <user>:PASSWORD | grep -i '^dav:'
# -> DAV: 1, 2, 3, calendar-access   (Apple refuses the account without it)
```

- `$S` shows the login page, and tasks and calendars load after signing in.
- A `200` with HTML instead of a `301` means the Caddy snippet is out of date.
- A change made on a phone appears within about a second (hook) or 30 seconds
  (poll).

## Optional features

### Claude connector (MCP)

1. In `/etc/smylte/smylte.env`:
   ```
   SMYLTE_MCP_ENABLED=true
   SMYLTE_PUBLIC_URL=https://smylte.example.com
   ```
   `SMYLTE_PUBLIC_URL` is required because OAuth metadata needs absolute URLs
   and tokens are bound to it. The app won't start without it, without app auth,
   or without `SMYLTE_SESSION_SECRET`.
2. `sudo systemctl restart smylte`. No proxy change is needed.
3. In Claude → Settings → Connectors → **Add custom connector**, enter
   `https://smylte.example.com/mcp` and leave the client ID and secret blank
   (dynamic client registration). The consent screen asks for the app password
   and offers read-only or full access.
4. Manage connections in **Settings → Account → Connected apps**.

Anthropic's requests come from `160.79.104.0/21`. A WAF or Cloudflare Access in
front of the app must let that range reach `/mcp` and `/.well-known/oauth-*`.

Check:

```bash
curl -s $S/.well-known/oauth-protected-resource | jq .resource   # "$S/mcp"
curl -s $S/.well-known/oauth-authorization-server | jq .issuer    # "$S"
curl -sI -X POST $S/mcp -H 'Content-Type: application/json' -d '{}' | grep -i www-authenticate
```

If `resource` doesn't exactly match the URL given to Claude, the connection
fails even though the server is reachable.

### Telegram notifications

1. Create a bot with [@BotFather](https://t.me/BotFather) and send it a message
   (a bot can't start a conversation).
2. In **Settings → Notifications**, enter the token and your chat id, turn it on
   and press **Send a test message**. Alternatively set
   `SMYLTE_TELEGRAM_BOT_TOKEN` and `SMYLTE_TELEGRAM_CHAT_ID` in the env file;
   values set in the app take precedence. `SMYLTE_NOTIFY_ENABLED=false` disables
   notifications entirely.
3. **Allow egress.** The unit is loopback-only (`IPAddressDeny=any`). Add
   Telegram's ranges as `IPAddressAllow=` lines above the deny, as shown in the
   comments in `deploy/smylte.service`. Don't remove the deny: the service parses
   untrusted iCalendar, and open egress would turn a parser bug into an
   exfiltration channel.
4. `sudo systemctl daemon-reload && sudo systemctl restart smylte`. The scheduler
   runs once at startup.

Rules, the digest time and lead times are account settings, edited in the app.
`GET /api/notifications/recent` lists what was sent. The bot token is stored in
the database in plain text (it has to be reused to send), so it is in every
backup. It is never returned over HTTP. Put it in the env file to keep it out of
the database. Telegram isn't end-to-end encrypted, so messages carry no error
details.

### Email suggestions

Configured in **Settings → Email**. Changes apply on the next scan. Nothing is
sent to Anthropic until it is switched on and both secrets are set.
`SMYLTE_MAIL_ENABLED=false` disables it. The pipeline is described in
`backend/smylted/mail/pipeline.py`.

**Where it runs.** The pipeline runs inside `smylted` and needs an IMAP
connection to Proton Mail Bridge. Either:

- run `smylted` on the machine with Bridge (`127.0.0.1:1143`), with its own
  `SMYLTE_DB` and `RADICALE_URL` pointing at Radicale's own origin, for example
  through `ssh -N -L 5232:127.0.0.1:5232 <server>`. A `/dav` path prefix doesn't
  work there; or
- tunnel Bridge to the server with `ssh -N -R 1143:127.0.0.1:1143 <server>`, or
  run Bridge headless on the server. The unit's `IPAddressAllow=localhost`
  already admits it.

**Bridge setup.**

1. In Bridge's mailbox configuration, note the IMAP username and password
   (Bridge's own, not your Proton login).
2. Export the certificate (**Settings → Advanced settings → Export TLS
   certificates**) and paste `cert.pem` under **Certificate → Pinned
   certificate**. The app checks its SHA-256 before sending the password.
   "Don't check" is allowed for localhost only.
3. Use port `1143` with **STARTTLS**, then **Test connection**. It lists the
   folders and says whether recent INBOX mail carries `Authentication-Results`
   from a trusted server. If none do, always-read senders are treated as
   ordinary mail.

Smylte opens folders read-only (`EXAMINE`, `BODY.PEEK[]`), so it doesn't mark,
move or delete anything, and it can share Bridge with Thunderbird.
`Authentication-Results` are trusted only from `protonmail.ch` and
`*.protonmail.ch`. DKIM and SPF are read from the topmost trusted header, and
every trusted DMARC result must pass, so a forged header lower down can't
override Proton's verdict.

**Egress.** Allow Anthropic's ranges above the deny in the unit:

    IPAddressAllow=160.79.104.0/23
    IPAddressAllow=2607:6bc0::/48

A Bridge on another machine needs its address allowed too. A TypeSafe key also
needs `api.typesafe.ai`, which is served from Cloudflare's shared anycast
addresses, so allowing it opens a slice of everything Cloudflare serves. If
that's not acceptable, leave the TypeSafe key empty. A blocked Jev call just
leaves the decision to Claude. Measurements are in
`backend/dev/mail_eval/README.md`.

**Secrets.** The Anthropic key, Bridge password and TypeSafe key are write-only.
They're never returned, never logged (`smylted/mail/redact.py`), and never written
to `smylte.db` or any config file in the repository. They're stored in one of:

- **the OS keyring**, when one is available (Secret Service, Windows Credential
  Manager);
- **an encrypted file**, `secrets.enc` next to the database, using AES-256-GCM
  under the key in `SMYLTE_SECRETS_KEY_FILE` (default
  `~/.config/smylte/secrets.key`) or the systemd credential
  `smylte-secrets-key`. The key file is refused if other users can read it, if
  someone other than its user or root owns it, or if it's inside the source tree.

The choice is made once and recorded (`meta.secrets_backend`).
`SMYLTE_SECRETS_BACKEND=keyring|file` forces it. `SMYLTE_ANTHROPIC_API_KEY`,
`SMYLTE_MAIL_IMAP_PASSWORD` and `SMYLTE_TYPESAFE_API_KEY` override stored values.

Under the hardened unit the home directory is read-only, so pass the key as a
credential and leave `SMYLTE_SECRETS_KEY_FILE` unset:

    sudo ~/smylte/backend/.venv/bin/python -m smylted secrets init-key --path /etc/smylte/secrets.key
    # in deploy/smylte.service, [Service]:
    LoadCredential=smylte-secrets-key:/etc/smylte/secrets.key

The `secrets` CLI has `status`, `set NAME`, `clear NAME`, `init-key` and
`migrate --to file`. Run it with the service's user, environment and credential,
or it will read a different database and key:

    sudo systemd-run --pipe --wait --quiet -p User=<user> \
        -p EnvironmentFile=/etc/smylte/smylte.env \
        -p LoadCredential=smylte-secrets-key:/etc/smylte/secrets.key \
        -p WorkingDirectory=/home/<user>/smylte/backend \
        /home/<user>/smylte/backend/.venv/bin/python -m smylted secrets status

Save Bridge's server settings before setting `imap_password`. The password is
bound to the host, port, encryption, certificate and username it was saved for,
and changing any of them clears it. While `SMYLTE_MAIL_IMAP_PASSWORD` is set,
the server settings can't be changed in the app. Unset it and restart, change
them, then set it again.

**Moving to another machine.** Either re-enter the secrets in Settings, or run
`secrets migrate --to file`, copy `secrets.enc` and the key file separately
(keep them 0600), and point `SMYLTE_SECRETS_FILE` and `SMYLTE_SECRETS_KEY_FILE`
(or `LoadCredential=`) at them. Copy the mail tables too (see
[Backups](#backups)), or the first scan re-proposes the last week of mail.

### Displays

Pair a display in **Settings → Displays**. Each one has a token and these URLs:

| URL | For |
| --- | --- |
| `/display/<token>` | A browser: a Raspberry Pi kiosk, an old tablet, a Boox |
| `/api/public/display/<token>.bin` | A microcontroller: the packed 1-bit framebuffer (see `firmware/README.md`) |
| `/api/public/display/<token>.png`, `.bmp` | A board with an image decoder. `?w=&h=`, `?rotate=` and `?palette=` override per request |
| `/api/public/display/<token>` | The frame as JSON (about 30 KB for a typical month, up to about 130 KB) |

- **Set a home timezone** in Settings → General if the server isn't in your
  zone. Without one, displays use the server's zone.
- Renders are limited to 4,000,000 pixels. Larger requests get a 422.
- `.bin` is always 1-bit and always drawn in the e-ink palette, and its
  `X-Display-Refresh-Seconds` is never below 180. `.png` and `.bmp` are 1-bit
  only while the display is set to e-ink. In colour mode the same URL serves
  24-bit BGR (1,152,054 bytes at 800×480).
- The PNG uses adaptive row filtering (needs zlib and all five unfilters), and
  the BMP is bottom-up with padded rows. On a Pico-class board, use `.bin`.
- E-ink refresh is limited to every 180 seconds. Existing e-ink displays set
  lower are raised on first start. Colour displays can refresh every 60 seconds.
- Every format answers 304 to a matching `If-None-Match`. The ETag excludes the
  timestamp, so it changes only when the picture does.
- The month needs at least about 360×260 (`render.py::month_grid_fits`). Smaller
  panels get a notice instead.
- Greyscale and colour e-paper panels aren't supported as their own palettes
  yet; use `eink`.
- The token gives read access to your events and habits. Use **New URL** if it
  leaks. MicroPython doesn't verify TLS certificates by default (see
  `firmware/README.md`).
- **Settings → Developer** previews every mode at real panel sizes through
  `GET /api/displays/preview.png`, without creating a display or token.

The renderer needs Pillow and the fonts in `backend/smylted/display/fonts/`.
Rebuild them with `python -m dev.build_display_fonts` (needs `fonttools` and
`brotli`) if the frontend's fonts change. Displays need no outbound network.

## Content-Security-Policy

The app sends one on every response (`backend/smylted/csp.py`).

| Directive | Why it isn't tighter |
|---|---|
| `script-src 'self' 'sha256-…'` | The hash is the SPA's inline pre-paint script, read from `dist/index.html` at startup (see step 1). |
| `style-src … 'unsafe-inline' fonts.googleapis.com` | Calendar and list colours are inline styles, and the MCP consent screen uses a `<style>` block. Some Appearance font choices load a Google stylesheet. |
| `font-src 'self' fonts.gstatic.com` | Where that stylesheet loads fonts from. The built-in fonts are local. |

Choosing a Google-hosted font means every page load, including the public booking
page, sends the reader's IP to Google.

If the policy breaks something, set this in the env file and restart:

```
SMYLTE_CSP=report-only    # log violations, block nothing
SMYLTE_CSP=off            # no header
```

Any other value enforces. The active policy is logged at startup
(`journalctl -u smylte | grep csp:`).

## If the password leaks — signing out everywhere

Sessions are JWTs and stay valid until they expire. Their lifetime is the **Stay
signed in** setting (Settings → Account). `SMYLTE_SESSION_TTL` is only the
default until that's set. Logging out ends only the current session.

1. **Change the password.** Generate a hash with
   `cd ~/smylte/backend && .venv/bin/python -m smylted hash-password` (it must be
   run from the backend directory), set `SMYLTE_AUTH_PASSWORD_HASH` in the env
   file, and restart. Every existing session is refused from then on. Changing
   `SMYLTE_AUTH_USER` has the same effect.
2. **Rotate `SMYLTE_SESSION_SECRET`** if the secret itself may have leaked, since
   it can mint sessions without the password. Generate one with
   `python -c 'import secrets;print(secrets.token_hex(32))'` and restart. Every
   session ends, including yours.

Either one also ends every MCP grant. Reconnect MCP clients afterwards. An
ordinary restart signs nobody out.

## Rollback

`sudo systemctl disable --now smylte.service`, remove the Caddy snippet and
reload Caddy, delete the tunnel's public hostname, and remove the Radicale
`hook` line and restart Radicale. None of this changes Radicale's data.

## Backups

Back up both:

- **Radicale's collections** (the `.ics` files), which are the source of truth.
- **The sidecar tables** in `/var/lib/smylte/smylte.db`. They exist nowhere
  else, and a resync can't rebuild them (`docs/phase0-findings.md`). Only the
  cache tables (items, collections, sync_state, FTS) are disposable.

| Table | Holds |
|---|---|
| `sidecar` | Per-task app state: manual order, pins, estimates, reminder leads, parking, and original due dates |
| `list_settings` | Per-list settings |
| `completions` | Completion records |
| `attachments` | Attachments |
| `booking_links`, `bookings` | Booking link settings, and bookings with client names, emails and notes |
| `day_plan` | Each day's rows: what was added, ticked, estimated, worked, moved or dropped |
| `day_plan_opened` | Which days were opened |
| `day_ritual` | What you said about each day: capacity, start, shutdown, how far over at commit, and your note |
| `habits` | Habit rules. Losing them stops habits recurring; past rows stay in `day_plan` |
| `focus_session` | The running focus session. Worked time already credited is in `day_plan` |
| `notification_deliveries` | What has been sent. Without it, a restore re-sends anything inside the catch-up window |
| `displays` | Paired displays and their tokens. Losing it unpairs every screen |
| `mail_ledger`, `mail_cursors`, `mail_suggestions`, `mail_threads`, `mail_rejections` | What mail was read, scan positions, pending suggestions, thread links and dismissals. Without them the next scan re-proposes the last week of mail |

Email secrets aren't in the database; carry them separately (see
[Email suggestions](#email-suggestions)).
