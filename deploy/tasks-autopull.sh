#!/usr/bin/env bash
# Pull-only deploy sync for the Tasks app (mirrors notes-autopull.sh).
# Fast-forward only — never clobbers local. User content (tasks.db) and secrets
# (/etc/tasks) are gitignored / out-of-tree, so a pull only touches source.
set -u
export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"

REPO_DIR="$HOME/tasks"
LOG="$HOME/tasks-autopull.log"
LOCK="$HOME/.tasks-autopull.lock"

exec 9>"$LOCK"
flock -n 9 || exit 0

ts() { date '+%Y-%m-%d %H:%M:%S'; }
cd "$REPO_DIR" || { echo "$(ts) cd $REPO_DIR failed" >>"$LOG"; exit 1; }

BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null || echo main)
if ! git fetch --quiet origin "$BRANCH" 2>>"$LOG"; then
  echo "$(ts) fetch failed" >>"$LOG"; exit 1
fi

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")
[ "$LOCAL" = "$REMOTE" ] && exit 0

echo "$(ts) update $BRANCH ${LOCAL:0:7} -> ${REMOTE:0:7}" >>"$LOG"
if ! git pull --ff-only --quiet 2>>"$LOG"; then
  echo "$(ts) pull failed (non-ff?) — left unchanged, fix by hand" >>"$LOG"; exit 1
fi

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

# Restart the app (allowed passwordless via /etc/sudoers.d/tasks-autopull).
if sudo -n systemctl restart tasks.service >>"$LOG" 2>&1; then
  echo "$(ts) applied + restarted tasks.service" >>"$LOG"
else
  echo "$(ts) restart failed (sudoers rule?)" >>"$LOG"
fi
