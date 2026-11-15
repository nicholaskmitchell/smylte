#!/usr/bin/env bash
# Pull-only deploy sync for Smylte (mirrors notes-autopull.sh).
# Fast-forward only — never clobbers local. User content (smylte.db) and secrets
# (/etc/smylte) are gitignored / out-of-tree, so a pull only touches source.
#
# Cron runs it with none of these set, and then it prints nothing and logs as
# it always has, except that the rebuild diffs the range actually pulled
# (LOCAL..HEAD) rather than LOCAL..REMOTE. The two differ only when the pull
# does not land on origin/$BRANCH: a checkout ahead of origin, or a push between
# the fetch and the pull. The desk key's updater (deploy/smylte-panel-update.sh)
# sets:
#   SMYLTE_AUTOPULL_REPO=<checkout>   the checkout, instead of ~/smylte or ~/tasks
#   SMYLTE_AUTOPULL_NO_RESTART=1      leave the restart to the caller
#   SMYLTE_AUTOPULL_REPORT=1          wait for the lock, and print the outcome as
#                                     the last line: autopull: current | updated |
#                                     blocked | failed <cd|fetch|pull|pip|npm|migrate|busy>
set -u
export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"
REPORT=${SMYLTE_AUTOPULL_REPORT:-}
NO_RESTART=${SMYLTE_AUTOPULL_NO_RESTART:-}

# Resolve rather than hardcode: this script is installed as a COPY, so during
# the tasks -> smylte migration the copy on disk and the checkout on disk can
# disagree about which name is current for one cron tick. Preferring the new
# name and falling back to the old makes that tick a no-op instead of a gap.
if [ -n "${SMYLTE_AUTOPULL_REPO:-}" ]; then
  REPO_DIR=$SMYLTE_AUTOPULL_REPO
else
  REPO_DIR="$HOME/smylte"
  [ -d "$REPO_DIR" ] || REPO_DIR="$HOME/tasks"
fi
LOG="$HOME/smylte-autopull.log"
LOCK="$HOME/.smylte-autopull.lock"
# REPORT mode only. A pull moves HEAD before pip and npm run, so after one of
# them fails the next run finds nothing new and would skip the rebuild for
# good. This holds the commit the failed run pulled from, until a run that
# diffs from it gets through.
PENDING="$HOME/.smylte-autopull-pending"

# The outcome line, printed by the EXIT trap so it is the last thing on stdout
# whichever exit is taken. Set just before each exit; an exit nobody planned
# leaves it empty, and the caller reads that as no outcome.
OUTCOME=
if [ "$REPORT" = 1 ]; then
  trap '[ -z "$OUTCOME" ] || echo "autopull: $OUTCOME"' EXIT
fi

exec 9>"$LOCK"
if [ "$REPORT" = 1 ]; then
  # Someone pressed the key and is waiting: wait out a cron run's rebuild.
  flock -w 900 9 || { OUTCOME="failed busy"; exit 1; }
else
  flock -n 9 || exit 0
fi

ts() { date '+%Y-%m-%d %H:%M:%S'; }

# REPORT mode: stop before the migrations, keeping the base to rebuild from.
# The oldest base wins, so a second failure does not narrow the diff. Cron
# mode carries on, as it always has.
rebuild_failed() {   # $1: pip or npm
  [ "$REPORT" = 1 ] || return 0
  [ -e "$PENDING" ] || echo "$LOCAL" >"$PENDING"
  OUTCOME="failed $1"
  exit 1
}

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
  # The URL carries the bot token, and Telegram offers no alternative — so it
  # goes in on STDIN as a curl config file rather than on the command line,
  # where /proc/<pid>/cmdline would expose it to every local user for the life
  # of the request. Nothing here reaches $LOG either, for the same reason.
  #
  # --fail so a 4xx/5xx is a non-zero exit, and the marker is set ONLY on a send
  # that actually landed. Marking a failed send as delivered would permanently
  # suppress the one notice this exists to deliver — the failure mode this whole
  # function was written to prevent, reintroduced one line lower.
  local msg="Smylte: a deploy is waiting on a migration that needs root. Deploys will not restart the service until it is applied. Run: sudo ${REPO_DIR}/deploy/migrate.sh"
  if printf 'url = "https://api.telegram.org/bot%s/sendMessage"\ndata-urlencode = "chat_id=%s"\ndata-urlencode = "text=%s"\n' \
       "$token" "$chat" "$msg" \
     | curl -sS --fail -o /dev/null --max-time 10 --config - 2>/dev/null; then
    touch "$NOTIFIED"
  fi
}
cd "$REPO_DIR" || { echo "$(ts) cd $REPO_DIR failed" >>"$LOG"; OUTCOME="failed cd"; exit 1; }

BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null || echo main)
if ! git fetch --quiet origin "$BRANCH" 2>>"$LOG"; then
  echo "$(ts) fetch failed" >>"$LOG"; OUTCOME="failed fetch"; exit 1
fi

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")

# What the rebuild diffs from: this run's HEAD before the pull, or in REPORT
# mode the base a failed run left, which also makes a run with nothing new
# rebuild and report updated.
BASE=$LOCAL
RETRY=0
if [ "$REPORT" = 1 ] && [ -e "$PENDING" ]; then
  pending=$(head -n 1 -- "$PENDING" 2>/dev/null || true)
  if [[ $pending =~ ^[0-9a-f]{40}$ ]] && git merge-base --is-ancestor "$pending" HEAD 2>/dev/null; then
    BASE=$pending
    RETRY=1
    echo "$(ts) an earlier rebuild failed -> again from ${BASE:0:7}" >>"$LOG"
  else
    rm -f "$PENDING"
  fi
fi

PULLED=0
if [ "$LOCAL" != "$REMOTE" ]; then
  echo "$(ts) update $BRANCH ${LOCAL:0:7} -> ${REMOTE:0:7}" >>"$LOG"
  if ! git pull --ff-only --quiet 2>>"$LOG"; then
    echo "$(ts) pull failed (non-ff?) — left unchanged, fix by hand" >>"$LOG"; OUTCOME="failed pull"; exit 1
  fi
  PULLED=1
fi
[ "$RETRY" = 0 ] || PULLED=1

if [ "$PULLED" = 1 ]; then
  CHANGED=$(git diff --name-only "$BASE" HEAD)

  # Backend deps changed -> reinstall.
  if echo "$CHANGED" | grep -q '^backend/requirements.txt'; then
    echo "$(ts) requirements changed -> pip install" >>"$LOG"
    backend/.venv/bin/pip install -q -r backend/requirements.txt >>"$LOG" 2>&1 || rebuild_failed pip
  fi

  # Frontend changed -> rebuild dist (dist is gitignored).
  if echo "$CHANGED" | grep -q '^frontend/'; then
    echo "$(ts) frontend changed -> rebuild" >>"$LOG"
    if [ ! -d frontend/node_modules ] || echo "$CHANGED" | grep -qE '^frontend/package(-lock)?\.json'; then
      ( cd frontend && npm ci ) >>"$LOG" 2>&1 || rebuild_failed npm
    fi
    ( cd frontend && npm run build ) >>"$LOG" 2>&1 || rebuild_failed npm
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
  if ! deploy/migrate.sh --auto >>"$LOG" 2>&1; then
    echo "$(ts) migrate --auto failed (see above)" >>"$LOG"
    if [ "$REPORT" = 1 ]; then OUTCOME="failed migrate"; exit 1; fi
  fi
  # Never restart into a box the migration has not finished with: a half-applied
  # rename means the unit and the env file disagree, and the service comes up
  # misconfigured or not at all. Leave the running one alone and say so.
  if deploy/migrate.sh --status 2>/dev/null | grep -q 'needs root'; then
    echo "$(ts) MIGRATION PENDING (needs root) — not restarting." >>"$LOG"
    echo "$(ts) run: sudo $REPO_DIR/deploy/migrate.sh" >>"$LOG"
    notify_pending_migration
    OUTCOME=blocked
    exit 0
  fi
  # No longer pending: arm the notice again for whatever migration comes next.
  rm -f "$NOTIFIED"
fi

# Nothing new and nothing blocking: done. (The check above still ran, so a
# pending migration is reported every tick rather than once.)
OUTCOME=current
[ "$PULLED" = 1 ] || exit 0

# A checkout ahead of origin "pulls" without moving HEAD: nothing was updated.
if [ "$REPORT" != 1 ] || [ "$RETRY" = 1 ] || [ "$(git rev-parse HEAD)" != "$LOCAL" ]; then
  OUTCOME=updated
fi
[ "$REPORT" != 1 ] || rm -f "$PENDING"
# Restart the app (allowed passwordless via /etc/sudoers.d/smylte-autopull),
# unless the caller restarts it itself.
if [ "$NO_RESTART" = 1 ]; then
  echo "$(ts) applied; the restart is left to the caller" >>"$LOG"
elif sudo -n systemctl restart smylte.service >>"$LOG" 2>&1; then
  echo "$(ts) applied + restarted smylte.service" >>"$LOG"
else
  echo "$(ts) restart failed (sudoers rule?)" >>"$LOG"
fi
