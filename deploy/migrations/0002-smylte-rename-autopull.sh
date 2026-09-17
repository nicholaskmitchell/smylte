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
  local cur new
  cur="$(crontab -u "$RUN_USER" -l 2>/dev/null || true)"
  if printf '%s\n' "$cur" | grep -q 'tasks-autopull'; then
    new="$(printf '%s\n' "$cur" | sed "s#[^ ]*tasks-autopull\.sh#$RUN_HOME/smylte-autopull.sh#g")"
    if [ "$DRY" = 1 ]; then
      printf '  would: rewrite crontab line to %s/smylte-autopull.sh\n' "$RUN_HOME"
    else
      printf '%s\n' "$new" | crontab -u "$RUN_USER" -
    fi
  fi

  # 3. Retire the old copy and its lock. The new script flocks
  #    ~/.smylte-autopull.lock, so the stale one guards nothing and would only
  #    ever confuse whoever finds it.
  [ -f "$RUN_HOME/tasks-autopull.sh" ] && run rm -f "$RUN_HOME/tasks-autopull.sh"
  [ -f "$RUN_HOME/.tasks-autopull.lock" ] && run rm -f "$RUN_HOME/.tasks-autopull.lock"

  # The old log is left where it is. It is the record of every deploy before the
  # rename, it costs nothing, and deleting somebody's logs is not a migration's
  # business.
  return 0
}
