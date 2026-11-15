#!/usr/bin/env bash
# Update Smylte at the desk panel's request. Installed by panel-setup.sh as
# /usr/local/lib/smylte-panel/update.sh and run as root by
# smylte-panel-update.service, never by hand.
#
# What it does, in order: autopull's steps as the owner of the checkout that
# smylte.service runs, a restart of smylted that waits for /healthz, then the
# PULLED deploy/panel-setup.sh --update as root. A panel that does not stay up
# for WATCH_S afterwards gets its previous code and unit back.
#
# The panel waits on the result line, `<request id> <boot time> <state>`, in
# $RESULT. It is written `running` first and rewritten at every end, a crash
# included (the EXIT trap), so the glass never waits on a run that is gone.
#
# Everything goes to stdout, which is the journal. Its own lines start
# "update: ", and the autopull log lines it adds start "update: autopull log: ".
# Autopull's outcome line and panel-setup.sh --update's output appear as those
# scripts print them. The display token is never read here.
#
# panel-setup.sh --update replaces this very file while it runs. bash reads a
# script as it goes, so everything is in functions and the last line calls
# main: by then the whole file has been read.
set -u

LIB=/usr/local/lib/smylte-panel
OUT=/run/smylte-panel-update
REQ=$OUT/request
RESULT=$OUT/result
PANEL_REQ=/run/smylte-panel/update
PANEL=smylte-panel.service
PANEL_UNIT=/etc/systemd/system/$PANEL
SERVER=smylte.service
SETUP_LOCK=/run/smylte-panel-setup.lock
HEALTH_URL=http://127.0.0.1:8080/healthz
HEALTH_S=300
# The panel's first paint after a restart (PAINT_MAX_S, 90 s) plus its
# watchdog (60 s): a new client that cannot paint, or stops pinging, has failed
# by then.
WATCH_S=150
# Leaves room for the panel step and a rollback inside TimeoutStartSec (30 min).
BUDGET_S=1500

id=0.000
WORK=
OWNER=
OWNER_UID=
OWNER_GID=
REPO=
HEAD1=
PULL=
PANEL_CHANGED=
INV0=
SNAP=()
SNAPPED=0
VERIFIED=0
RESTORED=0
DONE=0

say() { printf 'update: %s\n' "$*"; }

# Ends the run. The EXIT trap writes the result.
fail() {
  say "$*"
  exit 1
}

# ── the outside world, one small function each, so the tests can stub it ─────

pause() { sleep "$1"; }

# Boot time (CLOCK_BOOTTIME), the clock the panel compares the result with.
now_bt() {
  python3 -I -c 'import time; print("%.3f" % time.clock_gettime(time.CLOCK_BOOTTIME))'
}

# Whether smylted answers. Only a 2xx counts.
health_ok() {
  python3 -I -c '
import sys, urllib.request
with urllib.request.urlopen(sys.argv[1], timeout=2) as r:
    r.read()
' "$HEALTH_URL" >/dev/null 2>&1
}

unit_prop() {   # $1: unit, $2: property
  systemctl show -P "$2" "$1" 2>/dev/null
}

system_state() {
  systemctl is-system-running 2>/dev/null
}

# Without fd 8, the setup lock: nothing the owner runs holds it.
as_owner() {
  runuser -u "$OWNER" -- "$@" 8>&-
}

stat_of() {   # prints "<uid> <gid> <octal mode>"
  stat -c '%u %g %a' -- "$1" 2>/dev/null
}

# Whether an ACL on $1 lets an account other than root or $2 write it: exit 0
# if so, 1 if not (no ACL, or one that grants no such write), 2 if it cannot be
# read. stat shows an ACL's mask as the group bits, so the mode check cannot
# see a named user or group the ACL lets write; the mask still limits what
# they get. An ACL that only lets others read is fine: one on /home is common.
# A default ACL grants nothing on the directory itself, and every file it would
# reach is checked on its own. A filesystem without ACLs (ENOTSUP) has none.
acl_lets_write() {   # $1: path, $2: the owner's uid
  python3 -I -c '
import errno, os, struct, sys
path, owner = sys.argv[1], int(sys.argv[2])
try:
    raw = os.getxattr(path, "system.posix_acl_access", follow_symlinks=False)
except OSError as e:
    sys.exit(1 if e.errno in (errno.ENODATA, errno.ENOTSUP, errno.EOPNOTSUPP) else 2)
if len(raw) < 4 or (len(raw) - 4) % 8 or struct.unpack_from("<I", raw)[0] != 2:
    sys.exit(2)
entries = [struct.unpack_from("<HHI", raw, 4 + 8 * i) for i in range((len(raw) - 4) // 8)]
mask = next((perm for tag, perm, _ in entries if tag == 0x10), 7)
for tag, perm, who in entries:
    if not perm & mask & 2:
        continue
    if tag == 0x02 and who not in (0, owner):    # a named user
        sys.exit(0)
    if tag == 0x08:                             # a named group
        sys.exit(0)
sys.exit(1)
' "$1" "$2" 2>/dev/null
}

no_acl_write() {   # $1: path, $2: the owner's uid
  acl_lets_write "$1" "$2"
  case $? in
    0) fail "$1 has an ACL that lets another account write it" ;;
    1) ;;
    *) fail "the ACL of $1 cannot be read" ;;
  esac
}

uid_of() { id -u -- "$1" 2>/dev/null; }
gid_of() { id -g -- "$1" 2>/dev/null; }

group_members() {   # $1: gid; prints the member list, comma-separated
  local line
  line=$(getent group "$1" 2>/dev/null) || return 1
  printf '%s\n' "${line##*:}"
}

# The accounts whose PRIMARY group is $1, one per line. `getent group` does not
# list those, and on a box without user-private groups (everyone in "users")
# they could write a group-writable checkout too.
primary_members() {   # $1: gid
  getent passwd 2>/dev/null | awk -F: -v g="$1" '$4 == g { print $1 }'
}

home_of() {
  local line
  line=$(getent passwd "$1" 2>/dev/null) || return 1
  line=${line%:*}
  printf '%s\n' "${line##*:}"
}

# ── the result ───────────────────────────────────────────────────────────────

# Written beside the result and renamed over it, so the panel reads a whole
# line or the previous one.
result() {   # $1: running, updated, up-to-date or update-failed
  printf '%s %s %s\n' "$id" "$(now_bt)" "$1" >"$RESULT.tmp" \
    && mv -f -- "$RESULT.tmp" "$RESULT"
}

# ── 1. the request ───────────────────────────────────────────────────────────

# ExecStartPre has moved the panel's request here, so this reads a file in a
# root-owned directory. It is still whatever the panel's user made it, so only
# a regular file is opened: a symlink or a FIFO never is.
take_request() {
  local line=
  rm -rf -- "$PANEL_REQ"
  id=0.000
  if [ -f "$REQ" ] && [ ! -L "$REQ" ]; then
    IFS= read -r -n 32 line <"$REQ" || true
    if [[ $line =~ ^[0-9]{1,10}\.[0-9]{3}$ ]]; then
      id=$line
    else
      say "the request was malformed"
    fi
  else
    say "started without a request"
  fi
  rm -rf -- "$REQ"
}

# ── 3. the checkout ──────────────────────────────────────────────────────────

# Group write is allowed only for the owner's own group with no other member,
# which is what a user-private group is. Anything else that could write here
# could choose what root runs.
check_writable() {   # $1: path, $2: its gid, $3: its octal mode
  local members m who
  if (( 8#$3 & 8#002 )); then
    fail "$1 is writable by everyone"
  fi
  if (( 8#$3 & 8#020 )); then
    [ "$2" = "$OWNER_GID" ] || fail "$1 is group-writable, and its group is not $OWNER's own"
    members=$(group_members "$2") || fail "$1 is group-writable, and its group cannot be read"
    IFS=, read -ra m <<<"$members"
    for who in "${m[@]}"; do
      [ "$who" = "$OWNER" ] || fail "$1 is group-writable, and its group has $who in it too"
    done
    while IFS= read -r who; do
      [ -z "$who" ] || [ "$who" = "$OWNER" ] \
        || fail "$1 is group-writable, and $who has it as their own group too"
    done < <(primary_members "$2")
  fi
}

check_owned() {   # $1: path, $2: uid, $3: dir or file
  local st owner group mode
  [ ! -L "$1" ] || fail "$1 is a symlink"
  case "$3" in
    dir) [ -d "$1" ] || fail "$1 is not a directory" ;;
    *) [ -f "$1" ] || fail "$1 is not a file" ;;
  esac
  st=$(stat_of "$1") || fail "$1 cannot be read"
  read -r owner group mode <<<"$st"
  [ "$owner" = "$2" ] || fail "$1 is owned by uid $owner, not $OWNER ($2)"
  check_writable "$1" "$group" "$mode"
  no_acl_write "$1" "$2"
}

# Everything in the checkout that root runs or installs: the five paths the
# update itself needs, then whatever of panel-setup.sh's sources exists. The
# pull can bring in new files, so this runs again under the setup lock.
check_sources() {
  local f
  check_owned "$REPO" "$OWNER_UID" dir
  check_owned "$REPO/.git" "$OWNER_UID" dir
  check_owned "$REPO/deploy" "$OWNER_UID" dir
  check_owned "$REPO/deploy/panel-setup.sh" "$OWNER_UID" file
  check_owned "$REPO/deploy/smylte-autopull.sh" "$OWNER_UID" file
  for f in firmware firmware/pi_epaper_7in5; do
    if [ -e "$REPO/$f" ] || [ -L "$REPO/$f" ]; then
      check_owned "$REPO/$f" "$OWNER_UID" dir
    fi
  done
  for f in firmware/pi_epaper_7in5/panel.py firmware/pi_epaper_7in5/epd7in5_v2.py \
      deploy/smylte-panel.service deploy/70-smylte-panel-key.rules \
      deploy/smylte-panel-poweroff.path deploy/smylte-panel-poweroff.service \
      deploy/smylte-panel-update.path deploy/smylte-panel-update.service \
      deploy/smylte-panel-update.sh deploy/logind-smylte-panel.conf; do
    if [ -e "$REPO/$f" ] || [ -L "$REPO/$f" ]; then
      check_owned "$REPO/$f" "$OWNER_UID" file
    fi
  done
}

# Every directory above the checkout, from / down: one that someone else could
# write, by its mode or an ACL, could have the checkout swapped for theirs.
check_ancestors() {   # $1: uid
  local part parts st owner group mode p=
  IFS=/ read -ra parts <<<"${REPO#/}"
  unset 'parts[${#parts[@]}-1]'
  for part in "" "${parts[@]}"; do
    p=${p%/}/$part
    st=$(stat_of "$p") || fail "$p cannot be read"
    read -r owner group mode <<<"$st"
    [ "$owner" = 0 ] || [ "$owner" = "$1" ] || fail "$p is owned by uid $owner, not root or $OWNER"
    check_writable "$p" "$group" "$mode"
    no_acl_write "$p" "$1"
  done
}

# The checkout and its owner come from the root-owned server unit, never from
# the panel or the request: the key updates what smylte.service runs.
find_checkout() {
  local wd
  [ "$(unit_prop "$SERVER" LoadState)" = loaded ] \
    || fail "the key updates the checkout smylte.service runs, and it is not installed"
  OWNER=$(unit_prop "$SERVER" User)
  wd=$(unit_prop "$SERVER" WorkingDirectory)
  [ -n "$OWNER" ] || fail "smylte.service has no User="
  [ -n "$wd" ] || fail "smylte.service has no WorkingDirectory="
  [ "$OWNER" != root ] || fail "smylte.service runs as root; the key updates only a user's checkout"
  case "$wd" in
    */backend) ;;
    *) fail "smylte.service's WorkingDirectory $wd does not end in /backend" ;;
  esac
  REPO=${wd%/backend}
  OWNER_UID=$(uid_of "$OWNER") || fail "$OWNER, smylte.service's User=, does not exist"
  [[ $OWNER_UID =~ ^[0-9]+$ ]] && [ "$OWNER_UID" -ne 0 ] \
    || fail "$OWNER has uid '$OWNER_UID'; the key updates only a user's checkout"
  OWNER_GID=$(gid_of "$OWNER") || fail "$OWNER has no primary group"
  case "$REPO" in
    /*) ;;
    *) fail "$REPO is not an absolute path" ;;
  esac
  [ ! -L "$REPO" ] || fail "$REPO is a symlink"
  [ "$(realpath -e -- "$REPO" 2>/dev/null)" = "$REPO" ] || fail "$REPO is not its own real path"
  check_sources
  check_ancestors "$OWNER_UID"
  say "checkout $REPO, owner $OWNER"
}

# ── 4. the pull, as the owner ────────────────────────────────────────────────

# The script runs as text, not as the file: the pull rewrites the file.
pull() {
  local autopull home logf size rc outcome
  autopull=$(as_owner cat -- "$REPO/deploy/smylte-autopull.sh") \
    || fail "cannot read $REPO/deploy/smylte-autopull.sh as $OWNER"
  home=$(home_of "$OWNER") || fail "$OWNER has no home directory"
  [ -n "$home" ] || fail "$OWNER has no home directory"
  logf=$home/smylte-autopull.log
  size=$(as_owner stat -c %s -- "$logf" 2>/dev/null) || size=0
  [[ $size =~ ^[0-9]+$ ]] || size=0
  as_owner env SMYLTE_AUTOPULL_REPO="$REPO" SMYLTE_AUTOPULL_REPORT=1 SMYLTE_AUTOPULL_NO_RESTART=1 \
    bash -c "$autopull" smylte-autopull </dev/null 2>&1 | tee "$WORK/autopull.out"
  rc=${PIPESTATUS[0]}
  as_owner tail -c +"$((size + 1))" -- "$logf" 2>/dev/null | sed 's/^/update: autopull log: /'
  outcome=$(grep '^autopull: ' "$WORK/autopull.out" | tail -n 1)
  outcome=${outcome#autopull: }
  case "$outcome" in
    current|updated) PULL=$outcome ;;
    blocked) fail "a migration needs root: sudo $REPO/deploy/migrate.sh" ;;
    "failed "*) fail "autopull failed: ${outcome#failed } (see above)" ;;
    *) fail "autopull gave no outcome (exit $rc)" ;;
  esac
  HEAD1=$(as_owner git -C "$REPO" rev-parse HEAD 2>/dev/null)
  [ -n "$HEAD1" ] || fail "cannot read HEAD in $REPO"
  say "autopull: $PULL at ${HEAD1:0:7}"
}

# ── 5. the server ────────────────────────────────────────────────────────────

restart_server() {
  local end state
  say "restarting $SERVER"
  systemctl restart "$SERVER" || say "systemctl restart $SERVER failed"
  end=$((SECONDS + HEALTH_S))
  while :; do
    state=$(unit_prop "$SERVER" ActiveState)
    case "$state" in
      active|activating|reloading)
        if health_ok; then
          say "smylted answers /healthz"
          return 0
        fi ;;
      *) fail "smylte.service is $state after the restart (journalctl -u smylte)" ;;
    esac
    (( SECONDS < end )) || fail "smylted did not answer /healthz within $HEALTH_S s"
    pause 2
  done
}

# ── 7.–9. the lock, the HEAD check, the snapshot ─────────────────────────────

# Held until exit, so that panel-setup.sh by hand cannot run between the
# snapshot and the end of the watch, where the rollback would undo it.
# flock(2) does not care how the file was opened, so an account that could
# open it could hold it: it is root's alone. The file is never replaced, since
# a new one would not conflict with a holder of the old. The wait ends with
# the time budget.
take_setup_lock() {
  local um left
  um=$(umask)
  umask 077
  exec 8>>"$SETUP_LOCK" || { umask "$um"; fail "cannot open $SETUP_LOCK"; }
  umask "$um"
  chmod 0600 -- "$SETUP_LOCK" || true
  left=$((BUDGET_S - SECONDS))
  (( left > 0 )) || fail "ran out of time before the panel step"
  flock -w "$(( left < 600 ? left : 600 ))" 8 \
    || fail "panel-setup.sh is running by hand; press again when it is done"
}

check_head() {
  local head
  head=$(as_owner git -C "$REPO" rev-parse HEAD 2>/dev/null)
  [ "$head" = "$HEAD1" ] || fail "the checkout moved during the update; press again"
}

# The client's two files and its unit: what the rollback puts back.
snapshot() {
  local f
  SNAP=("$LIB/panel.py" "$LIB/epd7in5_v2.py" "$PANEL_UNIT")
  mkdir -- "$WORK/snap" || fail "cannot make $WORK/snap"
  for f in "${SNAP[@]}"; do
    if [ -e "$f" ] || [ -L "$f" ]; then
      cp -a -- "$f" "$WORK/snap/${f##*/}" || fail "cannot copy $f"
    else
      : >"$WORK/snap/${f##*/}.absent" || fail "cannot record that $f is absent"
    fi
  done
  INV0=$(unit_prop "$PANEL" InvocationID)
  SNAPPED=1
}

snap_differs() {   # $1: one of SNAP
  local s=$WORK/snap/${1##*/}
  if [ -e "$s.absent" ]; then
    [ -e "$1" ] || [ -L "$1" ]
  else
    ! cmp -s -- "$s" "$1"
  fi
}

# Puts the snapshot back, but only when something changed: a file, or the
# panel's process. A refusal that changed nothing leaves a running panel alone.
# When it acts it writes the result itself (RESTORED=1), before the old code
# starts; when it does not, the EXIT trap writes it. Runs at most once. Never
# exits.
restore_panel() {
  local f changed=()
  [ "$SNAPPED" = 1 ] && [ "$RESTORED" != 1 ] || return 0
  for f in "${SNAP[@]}"; do
    if snap_differs "$f"; then changed+=("$f"); fi
  done
  if [ "${#changed[@]}" -eq 0 ] && [ "$(unit_prop "$PANEL" InvocationID)" = "$INV0" ]; then
    return 0
  fi
  say "putting the panel's previous code and unit back"
  systemctl stop "$PANEL"
  for f in "${changed[@]}"; do
    if [ -e "$WORK/snap/${f##*/}.absent" ]; then
      rm -f -- "$f"
    else
      cp -a -- "$WORK/snap/${f##*/}" "$f" || say "could not put $f back"
    fi
  done
  systemctl daemon-reload
  # After the new code's last paint, so the panel that starts next reads it.
  result update-failed
  RESTORED=1
  if [ "$(system_state)" != stopping ]; then
    systemctl reset-failed "$PANEL"
    systemctl start "$PANEL"
  fi
}

# The EXIT trap writes the result when restore_panel had nothing to put back,
# so a failure that changed nothing still ends the panel's wait at once.
rollback() {
  say "$*"
  restore_panel
  exit 1
}

on_exit() {
  if [ "$DONE" != 1 ]; then
    if [ "$SNAPPED" = 1 ] && [ "$VERIFIED" != 1 ]; then
      restore_panel
    fi
    [ "$RESTORED" = 1 ] || result update-failed
  fi
  if [ -n "$WORK" ]; then
    rm -rf -- "$WORK"
  fi
}

# ── 10.–11. the panel ────────────────────────────────────────────────────────

install_panel() {
  local rc last
  SMYLTE_PANEL_SETUP_LOCKED=1 bash "$REPO/deploy/panel-setup.sh" --update </dev/null 2>&1 \
    | tee "$WORK/setup.out"
  rc=${PIPESTATUS[0]}
  last=$(tail -n 1 -- "$WORK/setup.out")
  # 3 is a refusal before anything was changed.
  if [ "$rc" -eq 3 ]; then
    fail "panel-setup.sh refused: $last"
  fi
  [ "$rc" -eq 0 ] || rollback "panel-setup.sh --update failed (exit $rc)"
  case "$last" in
    "panel: up to date") PANEL_CHANGED=no ;;
    "panel: updated") PANEL_CHANGED=yes ;;
    *) rollback "panel-setup.sh gave no outcome" ;;
  esac
}

# The final result is written before the watch, so the new code's first paint
# is the notice: a client that cannot paint fails inside the window.
watch_panel() {
  local end inv
  inv=$(unit_prop "$PANEL" InvocationID)
  end=$((SECONDS + WATCH_S))
  while :; do
    [ "$(unit_prop "$PANEL" ActiveState)" = active ] && [ "$(unit_prop "$PANEL" InvocationID)" = "$inv" ] \
      || rollback "the new panel code stopped within $WATCH_S s"
    (( SECONDS < end )) || break
    pause 2
  done
}

main() {
  local final=up-to-date
  take_request
  trap on_exit EXIT
  result running
  WORK=$(mktemp -d "$OUT/work.XXXXXX") || fail "cannot make a work directory in $OUT"
  find_checkout
  pull
  restart_server
  if (( SECONDS > BUDGET_S )); then
    fail "ran out of time before the panel step"
  fi
  take_setup_lock
  # Again: the lock may have been waited for.
  (( SECONDS > BUDGET_S )) && fail "ran out of time before the panel step"
  check_head
  check_sources
  check_ancestors "$OWNER_UID"
  snapshot
  install_panel
  if [ "$PULL" = updated ] || [ "$PANEL_CHANGED" = yes ]; then
    final=updated
  fi
  if [ "$PANEL_CHANGED" = no ]; then
    result "$final"
    say "done: $final"
    DONE=1
    exit 0
  fi
  result "$final"
  say "watching the new panel for $WATCH_S s"
  watch_panel
  VERIFIED=1
  say "done: $final"
  DONE=1
  exit 0
}

main "$@"; exit $?
