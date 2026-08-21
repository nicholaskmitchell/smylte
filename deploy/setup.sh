#!/usr/bin/env bash
# App-side install for tasksd. Run on the Pi:  sudo ~/tasks/deploy/setup.sh
#
# This installs ONLY the app itself (env, secrets, hook script, systemd unit).
# It does NOT touch Radicale's config, Caddy, or the tunnel — those are separate,
# production-touching steps documented in docs/DEPLOY.md.
set -euo pipefail

USER_NAME=nicholaskmitchell
BACKEND=/home/$USER_NAME/tasks/backend
DEPLOY=/home/$USER_NAME/tasks/deploy
PY=$BACKEND/.venv/bin/python
[ -x "$PY" ] || { echo "backend venv missing at $PY — create it first"; exit 1; }
[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }

echo "== /etc/tasks =="
install -d -m 0700 -o "$USER_NAME" -g "$USER_NAME" /etc/tasks

ENVFILE=/etc/tasks/tasks.env
if [ -f "$ENVFILE" ]; then
  echo "$ENVFILE exists — leaving it untouched (delete it to regenerate)."
else
  SESSION=$(python3 -c "import secrets;print(secrets.token_hex(32))")
  HOOK=$(python3 -c "import secrets;print(secrets.token_hex(24))")
  read -rsp "Radicale password for $USER_NAME: " RADPW; echo
  # Guarded like $HASH below, and for the same reason — except that an empty
  # Radicale password fails QUIETER: the service starts, the app logs in, and
  # every CalDAV call 401s, so the UI shows an empty account. Re-running this
  # script repairs nothing, because the check at the top of the file sees an
  # existing env file and leaves it alone. Refuse before anything is written.
  if [ -z "$RADPW" ]; then
    echo "empty Radicale password — env file not written; re-run setup" >&2
    exit 1
  fi
  read -rp  "App login username [nick]: " AUSER; AUSER=${AUSER:-nick}
  echo "Set the APP login password:"
  # NB: a failing command substitution inside an assignment does NOT trip
  # `set -e` — check explicitly, or a mismatched/aborted prompt would write
  # an empty TASKS_AUTH_PASSWORD_HASH and the service would refuse to start.
  # `cd` into $BACKEND first: `python -m tasksd` resolves the package off the
  # interpreter's path, which contains only the working directory, so run from
  # anywhere else this aborts on "No module named tasksd" — after prompting for
  # every password and before writing the env file.
  if ! HASH=$(cd "$BACKEND" && sudo -u "$USER_NAME" "$PY" -m tasksd hash-password) \
     || [ -z "$HASH" ]; then
    echo "password hashing failed — env file not written; re-run setup" >&2
    exit 1
  fi
  # systemd's EnvironmentFile parser is NOT the shell, and it is what actually
  # reads this file. `parse_env_file_internal` (src/basic/env-file.c) gives
  # three characters meaning a `KEY=value` heredoc does not account for: right
  # after `=` a quote opens a quoted section, and a backslash escapes the next
  # character and disappears. Neither is an error — an unterminated quote is
  # pushed silently at EOF.
  #
  # So `pi\home2024` was stored as `pihome2024` (silent 401s forever), and a
  # password starting with `"` swallowed the remaining twelve lines of this
  # file into itself, leaving TASKS_AUTH_PASSWORD_HASH, TASKS_SESSION_SECRET
  # and TASKS_HOOK_SECRET unset and the service in a restart loop.
  #
  # Emit the two prompt-read values in systemd's double-quoted form instead,
  # with backslash and double-quote escaped — the DOUBLE_QUOTE_VALUE_ESCAPE
  # state understands exactly those. Everything else in the heredoc is either a
  # literal or a value this script generated (hex tokens, a scrypt hash), none
  # of which can contain a metacharacter.
  q() { printf '"%s"' "$(printf '%s' "$1" | sed 's/[\\"]/\\&/g')"; }
  RADPW_Q=$(q "$RADPW")
  AUSER_Q=$(q "$AUSER")

  umask 077
  cat > "$ENVFILE" <<EOF
RADICALE_URL=http://127.0.0.1:5232
RADICALE_USER=$USER_NAME
RADICALE_PASSWORD=$RADPW_Q
TASKS_DB=$BACKEND/tasks.db
TASKS_STATIC=/home/$USER_NAME/tasks/frontend/dist
TASKS_SYNC_INTERVAL=30
TASKS_AUTH_ENABLED=true
TASKS_AUTH_USER=$AUSER_Q
TASKS_AUTH_PASSWORD_HASH=$HASH
TASKS_SESSION_SECRET=$SESSION
TASKS_SESSION_TTL=604800
TASKS_COOKIE_SECURE=true
TASKS_HOOK_SECRET=$HOOK
TASKS_ACCESS_REQUIRED=false
EOF
  echo "$HOOK" > /etc/tasks/hook-secret
  chown "$USER_NAME:$USER_NAME" "$ENVFILE" /etc/tasks/hook-secret
  chmod 0600 "$ENVFILE" /etc/tasks/hook-secret
  echo "wrote $ENVFILE and /etc/tasks/hook-secret (0600)"
fi

echo "== hook notify script -> /usr/local/bin/tasks-notify =="
install -m 0755 "$DEPLOY/tasks-notify" /usr/local/bin/tasks-notify

echo "== systemd unit =="
install -m 0644 "$DEPLOY/tasks.service" /etc/systemd/system/tasks.service
systemctl daemon-reload
systemctl enable --now tasks.service
systemctl --no-pager --lines=6 status tasks.service || true

echo
echo "App installed on 127.0.0.1:8080. NEXT (docs/DEPLOY.md, production-touching):"
echo "  B) Caddy /dav site   C) cloudflared tunnel + DNS   D) Radicale storage hook"
