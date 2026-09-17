#!/usr/bin/env bash
# Pull-only deploy sync for Smylte (mirrors notes-autopull.sh).
# Fast-forward only — never clobbers local. User content (smylte.db) and secrets
# (/etc/smylte) are gitignored / out-of-tree, so a pull only touches source.
set -u
export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"

# Resolve rather than hardcode: this script is installed as a COPY, so during
# the tasks -> smylte migration the copy on disk and the checkout on disk can
# disagree about which name is current for one cron tick. Preferring the new
# name and falling back to the old makes that tick a no-op instead of a gap.
REPO_DIR="$HOME/smylte"
[ -d "$REPO_DIR" ] || REPO_DIR="$HOME/tasks"
LOG="$HOME/smylte-autopull.log"
LOCK="$HOME/.smylte-autopull.lock"

exec 9>"$LOCK"
flock -n 9 || exit 0

ts() { date '+%Y-%m-%d %H:%M:%S'; }

# A pending root migration stops deploys taking effect, which is exactly the
# kind of thing that goes unnoticed in a log nobody is reading. Telegram is
# already configured for this deployment, so reuse it.
#
# ONCE, not once a minute. The check above runs on every tick by design, so an
# unguarded send here would be a message every sixty seconds until the migration
# is applied — which trains you to ignore it, the opposite of the point.
NOTIFIED="$HOME/.smylte-migration-notified"

notify_pending_migration() {
  [ -f "$NOTIFIED" ] && return 0
  local envfile token chat
  for envfile in /etc/smylte/smylte.env /etc/tasks/tasks.env; do
    [ -r "$envfile" ] || continue
    # Both spellings: this can fire either side of the env-file rewrite.
    token=$(sed -n 's/^[[:space:]]*\(SMYLTE\|TASKS\)_TELEGRAM_BOT_TOKEN=//p' "$envfile" | tail -1)
    chat=$(sed -n 's/^[[:space:]]*\(SMYLTE\|TASKS\)_TELEGRAM_CHAT_ID=//p' "$envfile" | tail -1)
    break
  done
  [ -n "${token:-}" ] && [ -n "${chat:-}" ] || return 0
  # -o /dev/null, and nothing from this call reaches $LOG: the bot token is in
  # the URL (Telegram gives no other option) and a log is the wrong place for it.
  curl -s -o /dev/null --max-time 10 \
    "https://api.telegram.org/bot${token}/sendMessage" \
    --data-urlencode "chat_id=${chat}" \
    --data-urlencode "text=Smylte: a deploy is waiting on a migration that needs root. Deploys will not restart the service until it is applied. Run: sudo ${REPO_DIR}/deploy/migrate.sh" \
    2>/dev/null || true
  touch "$NOTIFIED"
}
cd "$REPO_DIR" || { echo "$(ts) cd $REPO_DIR failed" >>"$LOG"; exit 1; }

BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null || echo main)
if ! git fetch --quiet origin "$BRANCH" 2>>"$LOG"; then
  echo "$(ts) fetch failed" >>"$LOG"; exit 1
fi

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")

PULLED=0
if [ "$LOCAL" != "$REMOTE" ]; then
  echo "$(ts) update $BRANCH ${LOCAL:0:7} -> ${REMOTE:0:7}" >>"$LOG"
  if ! git pull --ff-only --quiet 2>>"$LOG"; then
    echo "$(ts) pull failed (non-ff?) — left unchanged, fix by hand" >>"$LOG"; exit 1
  fi
  PULLED=1

  CHANGED=$(git diff --name-only "$LOCAL" "$REMOTE")

  # Backend deps changed -> reinstall.
  if echo "$CHANGED" | grep -q '^backend/requirements.txt'; then
    echo "$(ts) requirements changed -> pip install" >>"$LOG"
    backend/.venv/bin/pip install -q -r backend/requirements.txt >>"$LOG" 2>&1
  fi

  # Frontend changed -> rebuild dist (dist is gitignored).
  if echo "$CHANGED" | grep -q '^frontend/'; then
    echo "$(ts) frontend changed -> rebuild" >>"$LOG"
    if [ ! -d frontend/node_modules ] || echo "$CHANGED" | grep -qE '^frontend/package(-lock)?\.json'; then
      ( cd frontend && npm ci ) >>"$LOG" 2>&1
    fi
    ( cd frontend && npm run build ) >>"$LOG" 2>&1
  fi
fi

# Pending migrations — checked on EVERY tick, not only after a pull. A deploy
# moves source and nothing else: the unit, /etc, /var/lib and this script's own
# installed copy live outside the tree, and deploy/migrate.sh is what moves
# those. The migration that needs root arrives in one commit but is applied by a
# human minutes or days later, so gating this on "did we just pull" would mean
# mentioning it once and then falling silent for the whole window it matters in.
#
# Unprivileged migrations are applied here; anything needing root is REPORTED and
# left alone, because the sudoers rule grants exactly one command and widening it
# so a cron job could rewrite /etc would undo the reason it is that narrow.
if [ -x deploy/migrate.sh ]; then
  deploy/migrate.sh --auto >>"$LOG" 2>&1 \
    || echo "$(ts) migrate --auto failed (see above)" >>"$LOG"
  # Never restart into a box the migration has not finished with: a half-applied
  # rename means the unit and the env file disagree, and the service comes up
  # misconfigured or not at all. Leave the running one alone and say so.
  if deploy/migrate.sh --status 2>/dev/null | grep -q 'needs root'; then
    echo "$(ts) MIGRATION PENDING (needs root) — not restarting." >>"$LOG"
    echo "$(ts) run: sudo $REPO_DIR/deploy/migrate.sh" >>"$LOG"
    notify_pending_migration
    exit 0
  fi
  # No longer pending: arm the notice again for whatever migration comes next.
  rm -f "$NOTIFIED"
fi

# Nothing new and nothing blocking: done. (The check above still ran, so a
# pending migration is reported every tick rather than once.)
[ "$PULLED" = 1 ] || exit 0

# Restart the app (allowed passwordless via /etc/sudoers.d/smylte-autopull).
if sudo -n systemctl restart smylte.service >>"$LOG" 2>&1; then
  echo "$(ts) applied + restarted smylte.service" >>"$LOG"
else
  echo "$(ts) restart failed (sudoers rule?)" >>"$LOG"
fi
