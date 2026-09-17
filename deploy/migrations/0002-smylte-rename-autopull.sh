# 0002 — repoint the autopull loop at the new names.
#
# Runs after 0001 because it depends on the checkout already having moved. The
# runner applies migrations in order and stops at the first it cannot apply, so
# `--auto` (which cannot do 0001) never reaches this one — it cannot land out of
# order even though it needs no root.
#
# Why this is separate at all: ~/smylte-autopull.sh is an installed COPY of the
# one in the tree, not a symlink, and docs/DEPLOY.md explains why — the script's
# job is to `git pull` the directory it would be symlinked into, and a script
# that rewrites itself mid-run is a failure mode nobody wants to debug at
# one-minute intervals. The cost of that choice is that a change to it needs the
# copy repeating, and a rename is the largest such change there is: the old copy
# hardcodes REPO_DIR="$HOME/tasks", so left alone it would `cd` into a directory
# that no longer exists, log one line, and stop deploying. Silently, forever.
NEEDS_ROOT=no

describe() { echo "autopull: installed copy, crontab and stale lock"; }

applies() {
  [ -f "$RUN_HOME/tasks-autopull.sh" ] \
    || [ ! -f "$RUN_HOME/smylte-autopull.sh" ] \
    || crontab -u "$RUN_USER" -l 2>/dev/null | grep -q 'tasks-autopull'
}

apply() {
  # 1. The new copy.
  run install -m 0755 "$REPO_DIR/deploy/smylte-autopull.sh" "$RUN_HOME/smylte-autopull.sh"
  if [ "$(id -u)" -eq 0 ] && [ "$RUN_USER" != root ]; then
    run chown "$RUN_USER" "$RUN_HOME/smylte-autopull.sh"
  fi

  # 2. The crontab line. Rewritten rather than appended, so this is idempotent
  #    and never leaves two loops racing each other on the same checkout.
  #
  #    `crontab -u <user>` requires root. This migration declares NEEDS_ROOT=no
  #    because everything else it does is under $HOME, and in the normal flow it
  #    runs in the same `sudo migrate.sh` as 0001 — but --auto can reach it
  #    unprivileged, so address the table the way the current identity is allowed
  #    to. Editing your own crontab needs no privilege; editing someone else's does.
  local cur new rewrote=0
  if [ "$(id -un)" = "$RUN_USER" ]; then
    cur="$(crontab -l 2>/dev/null || true)"
  else
    cur="$(crontab -u "$RUN_USER" -l 2>/dev/null || true)"
  fi
  if printf '%s\n' "$cur" | grep -q 'tasks-autopull'; then
    new="$(printf '%s\n' "$cur" | sed "s#[^ ]*tasks-autopull\.sh#$RUN_HOME/smylte-autopull.sh#g")"
    if [ "$DRY" = 1 ]; then
      printf '  would: rewrite crontab line to %s/smylte-autopull.sh\n' "$RUN_HOME"
      rewrote=1
    elif { [ "$(id -un)" = "$RUN_USER" ] && printf '%s\n' "$new" | crontab -; } \
      || { [ "$(id -un)" != "$RUN_USER" ] && printf '%s\n' "$new" | crontab -u "$RUN_USER" -; }; then
      rewrote=1
    else
      echo "migrate: WARNING — could not rewrite the crontab. It still runs" >&2
      echo "migrate: ~/tasks-autopull.sh, which will be left in place. Fix with:" >&2
      echo "migrate:   crontab -e   # point the line at $RUN_HOME/smylte-autopull.sh" >&2
    fi
  else
    rewrote=1   # nothing referenced the old script; nothing to rewrite
  fi

  # 3. Retire the old copy and its lock — but ONLY once nothing schedules it.
  #    Deleting a script cron still invokes turns a working deploy loop into a
  #    silent one: cron logs to mail nobody reads, and deploys simply stop.
  if [ "$rewrote" = 1 ]; then
    [ -f "$RUN_HOME/tasks-autopull.sh" ] && run rm -f "$RUN_HOME/tasks-autopull.sh"
    [ -f "$RUN_HOME/.tasks-autopull.lock" ] && run rm -f "$RUN_HOME/.tasks-autopull.lock"
  fi

  # The old log is left where it is. It is the record of every deploy before the
  # rename, it costs nothing, and deleting somebody's logs is not a migration's
  # business.
  return 0
}
