#!/usr/bin/env bash
# Versioned migration runner for a Smylte deployment.
#
# Deploys arrive by `git pull` (see smylte-autopull.sh), which moves SOURCE and
# nothing else. Anything outside the tree — the systemd unit, /etc/smylte,
# /var/lib/smylte, the crontab — has to be moved by something, and doing it by
# hand from a runbook is how a box ends up in a state the runbook does not
# describe. This is that something.
#
# Each migration is a file in migrations/ named NNNN-slug.sh defining:
#
#   NEEDS_ROOT=yes|no   whether it touches anything outside $HOME
#   describe()          one line, for the log
#   applies()           exit 0 if there is still work to do  (the idempotency check)
#   apply()             do it; must be safe to re-run after a partial failure
#
# Inside apply(), EVERY side effect goes through `run`. That is what makes
# --dry-run a preview rather than a rehearsal: `run` prints under --dry-run and
# executes otherwise, and a migration that calls `mv` or `sed -i` directly will
# do it to /etc on a box somebody was only inspecting. The runner cannot tell a
# side effect from a guard, so the rule is enforced by a test instead —
# backend/tests/test_migrate_runner.py::test_every_side_effect_goes_through_run.
#
# They run in order, and the runner STOPS at the first one it cannot apply
# rather than skipping ahead — so a root-needing migration blocks the
# unprivileged ones behind it instead of letting them land out of order.
#
#   ./migrate.sh --status     what is applied, what is pending, what needs root
#   ./migrate.sh --dry-run    print every action, change nothing
#   ./migrate.sh --auto       apply only what needs no root   (autopull uses this)
#   sudo ./migrate.sh         apply everything pending        (you, once)
#
# The applied level is a single integer in ~/.smylte-migration-level. It lives in
# $HOME rather than the state directory on purpose: /var/lib/smylte does not
# exist until the very migration that creates it, and a state file that cannot
# be read until after the thing it gates is not a state file.
set -euo pipefail

# ── Re-exec from a copy, always ─────────────────────────────────────────────
# A migration is allowed to move the repository out from under us (0002 does
# exactly that), and bash reads a script incrementally — it would resume reading
# a path that no longer exists, mid-function, with no error worth the name.
# Copying costs a few milliseconds and makes the whole class of problem go away,
# so it is unconditional rather than a flag somebody has to remember.
if [ "${SMYLTE_MIGRATE_DETACHED:-}" != "1" ]; then
  _src="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
  _tmp="$(mktemp -d "${TMPDIR:-/tmp}/smylte-migrate.XXXXXX")"
  cp "$_src/migrate.sh" "$_tmp/" 2>/dev/null || true
  cp -R "$_src/migrations" "$_tmp/" 2>/dev/null || true
  chmod +x "$_tmp/migrate.sh"
  export SMYLTE_MIGRATE_DETACHED=1
  export SMYLTE_REPO_DIR="${SMYLTE_REPO_DIR:-$(cd "$_src/.." && pwd -P)}"
  export SMYLTE_MIGRATE_TMP="$_tmp"
  trap 'rm -rf "$_tmp"' EXIT
  "$_tmp/migrate.sh" "$@"
  exit $?
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
MIGRATIONS="$HERE/migrations"
REPO_DIR="${SMYLTE_REPO_DIR:?repo dir not resolved}"

# The invoking human, even under sudo — the level file is theirs, not root's.
RUN_USER="${SUDO_USER:-$(id -un)}"
RUN_HOME="$(getent passwd "$RUN_USER" | cut -d: -f6)"
[ -n "$RUN_HOME" ] || RUN_HOME="$HOME"
LEVEL_FILE="${SMYLTE_MIGRATION_STATE:-$RUN_HOME/.smylte-migration-level}"

MODE=apply
DRY=0
for arg in "$@"; do
  case "$arg" in
    --status)  MODE=status ;;
    --dry-run) DRY=1 ;;
    --auto)    MODE=auto ;;
    # Print the header block itself, however long it grows — a hardcoded line
    # range silently truncates the help the moment the comment above changes.
    -h|--help) awk 'NR>1 { if ($0 !~ /^#/) exit; sub(/^# ?/, ""); print }' "$0"; exit 0 ;;
    *) echo "migrate: unknown option $arg" >&2; exit 2 ;;
  esac
done

is_root() { [ "$(id -u)" -eq 0 ]; }
log()     { printf '%s migrate: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
run()     { if [ "$DRY" = 1 ]; then printf '  would: %s\n' "$*"; else "$@"; fi; }

level() {
  # Sanitised: an empty, whitespace-only or truncated level file (a crash
  # mid-write) would otherwise make $((10#$CURRENT)) an arithmetic error, which
  # abandons the whole migration loop while the script still exits 0 — every
  # pending migration silently skipped, --status reporting nothing pending.
  local v=""
  [ -f "$LEVEL_FILE" ] && v="$(cat "$LEVEL_FILE" 2>/dev/null || true)"
  v="$(printf '%s' "$v" | tr -cd '0-9')"
  printf '%s' "${v:-0}"
}

set_level() {
  [ "$DRY" = 1 ] && { printf '  would: record level %s\n' "$1"; return 0; }
  printf '%s\n' "$1" > "$LEVEL_FILE"
  # Written as root under sudo; hand it back or the next --auto run (as the app
  # user, from cron) cannot update it and every deploy re-reports the same work.
  if is_root && [ "$RUN_USER" != root ]; then
    chown "$RUN_USER" "$LEVEL_FILE" 2>/dev/null || true
  fi
}

mapfile -t FILES < <(find "$MIGRATIONS" -maxdepth 1 -name '[0-9][0-9][0-9][0-9]-*.sh' | sort)
CURRENT="$(level)"

# ── status ──────────────────────────────────────────────────────────────────
if [ "$MODE" = status ]; then
  echo "applied level : $CURRENT"
  echo "state file    : $LEVEL_FILE"
  echo "repo          : $REPO_DIR"
  pending=0
  for f in "${FILES[@]}"; do
    n="$(basename "$f" | cut -d- -f1)"
    [ "$((10#$n))" -le "$((10#$CURRENT))" ] && continue
    # shellcheck disable=SC1090
    ( NEEDS_ROOT=no; . "$f"
      if applies >/dev/null 2>&1; then
        printf '  PENDING %s  %s%s\n' "$n" "$(describe)" \
          "$([ "$NEEDS_ROOT" = yes ] && echo '   [needs root]')"
      else
        printf '  done    %s  %s (nothing to do)\n' "$n" "$(describe)"
      fi )
    pending=1
  done
  [ "$pending" = 0 ] && echo "  nothing pending"
  exit 0
fi

# ── apply ───────────────────────────────────────────────────────────────────
for f in "${FILES[@]}"; do
  n="$(basename "$f" | cut -d- -f1)"
  [ "$((10#$n))" -le "$((10#$CURRENT))" ] && continue

  NEEDS_ROOT=no
  # shellcheck disable=SC1090
  . "$f"

  # applies() FIRST, privilege second. Reversed, a root-needing migration that
  # has nothing left to do still stops an unprivileged run — so `--auto`, which
  # autopull runs every minute as the app user, would jam on it forever, never
  # record the level, and never reach any later migration. applies() only stats
  # paths, so it is safe to ask without privilege.
  if ! applies; then
    log "$n already satisfied: $(describe)"
    set_level "$n"
    continue
  fi

  # A dry run changes nothing, so it needs no privilege either — and the runbook
  # tells the operator to preview before escalating. Gating the preview behind
  # root made that instruction fail with an error whose remedy (`sudo migrate.sh`)
  # drops the --dry-run flag and performs the real migration.
  if [ "$NEEDS_ROOT" = yes ] && [ "$DRY" != 1 ] && ! is_root; then
    if [ "$MODE" = auto ]; then
      # Autopull's case. Say it loudly and stop — do NOT skip ahead to a later
      # migration, which would apply it against a box the earlier one has not
      # reached yet.
      log "MIGRATION $n PENDING AND NEEDS ROOT: $(describe)"
      log "run:  sudo $REPO_DIR/deploy/migrate.sh"
      exit 0
    fi
    log "migration $n needs root: $(describe)"
    log "re-run as:  sudo $REPO_DIR/deploy/migrate.sh"
    exit 1
  fi

  log "applying $n: $(describe)"
  apply
  set_level "$n"
  log "applied $n"
done

if [ "$DRY" = 1 ]; then
  log "dry run: nothing was changed"
  # Worth saying plainly, because the alternative is trusting an under-report:
  # steps are guarded on the state the PREVIOUS step would have produced, and in
  # a dry run that state never appears. So a chain like "move /etc/tasks, then
  # rename the env file inside it" shows only its first link. Every action is
  # still guarded and idempotent when it runs for real; this is a preview of the
  # first move in each chain, not a complete transcript.
  log "note: guarded follow-on steps are not shown — see --help"
fi
exit 0
