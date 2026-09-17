# 0001 — move the system half of the deployment from "tasks" to "smylte".
#
# /etc/tasks -> /etc/smylte, /var/lib/tasks -> /var/lib/smylte, ~/tasks ->
# ~/smylte, tasks.service -> smylte.service, tasks-notify -> smylte-notify, and
# the TASKS_* variables inside the env file to SMYLTE_*.
#
# Every step is guarded, so a run interrupted half way resumes rather than
# half-applying. The env file is REWRITTEN IN PLACE, never regenerated: it holds
# the session secret, the scrypt password hash and the Telegram token, and
# setup.sh deliberately refuses to touch an env file that already exists.
#
# Ordering is not arbitrary. The service stops first (nothing moves a database
# out from under a live writer), the checkout moves before the unit is installed
# (the unit names absolute paths inside it), and the service starts last.
NEEDS_ROOT=yes

describe() { echo "system paths, checkout, unit and env file: tasks -> smylte"; }

applies() {
  [ -d /etc/tasks ] || [ -d /var/lib/tasks ] \
    || [ -f /etc/systemd/system/tasks.service ] \
    || [ -x /usr/local/bin/tasks-notify ] \
    || [ -f /etc/sudoers.d/tasks-autopull ] \
    || { [ -d "$RUN_HOME/tasks" ] && [ ! -d "$RUN_HOME/smylte" ]; }
}

# A venv records absolute paths in the shebang of every console script it
# installed (pip above all). `bin/python -m smylted` survives a move because it
# resolves its prefix from the interpreter's own path, but `bin/pip` does not —
# and autopull runs `.venv/bin/pip install -r requirements.txt` whenever
# requirements.txt moves. Left unrepaired this breaks a deploy weeks later, for
# a reason nobody will connect back to a directory rename.
_repair_venv() {
  local venv="$1" old="$2" new="$3" f
  [ -d "$venv/bin" ] || return 0
  for f in "$venv"/bin/*; do
    [ -f "$f" ] || continue
    head -c2 "$f" 2>/dev/null | grep -q '#!' || continue
    grep -q "$old" "$f" 2>/dev/null || continue
    run sed -i "s#${old}#${new}#g" "$f"
  done
  [ -f "$venv/pyvenv.cfg" ] && grep -q "$old" "$venv/pyvenv.cfg" 2>/dev/null \
    && run sed -i "s#${old}#${new}#g" "$venv/pyvenv.cfg"
  return 0
}

apply() {
  local unit_old=/etc/systemd/system/tasks.service
  local unit_new=/etc/systemd/system/smylte.service

  # 1. Stop the old unit. Everything below moves files it has open.
  if systemctl is-active --quiet tasks.service 2>/dev/null; then
    run systemctl stop tasks.service
  fi

  # 2. Config.
  if [ -d /etc/tasks ] && [ ! -d /etc/smylte ]; then
    run mv /etc/tasks /etc/smylte
  fi
  if [ -f /etc/smylte/tasks.env ] && [ ! -f /etc/smylte/smylte.env ]; then
    run mv /etc/smylte/tasks.env /etc/smylte/smylte.env
  fi
  if [ -f /etc/smylte/smylte.env ] && grep -q '^[[:space:]]*TASKS_' /etc/smylte/smylte.env; then
    # Keep a copy. This file cannot be regenerated: the session secret and the
    # password hash exist nowhere else, and losing them logs everyone out and
    # locks you out respectively.
    run cp -a /etc/smylte/smylte.env "/etc/smylte/smylte.env.pre-rename.$(date +%Y%m%d%H%M%S)"
    # Anchored to the start of the line so only variable NAMES are rewritten —
    # a value that happens to contain "TASKS_" is left alone.
    run sed -i 's/^\([[:space:]]*\)TASKS_/\1SMYLTE_/' /etc/smylte/smylte.env
    # Two values move as well: the database path and the checkout path.
    run sed -i 's#/var/lib/tasks/tasks\.db#/var/lib/smylte/smylte.db#g' /etc/smylte/smylte.env
    run sed -i 's#\(/home/[^/]*\)/tasks/#\1/smylte/#g' /etc/smylte/smylte.env
  fi

  # 3. State. The sidecar tables here — parked tasks, day plans, habits, booking
  #    client details, display pairings — exist nowhere on the wire and a resync
  #    cannot rebuild them. The -wal and -shm sidecars move WITH the database;
  #    the unit is stopped, so the three are consistent.
  if [ -d /var/lib/tasks ] && [ ! -d /var/lib/smylte ]; then
    run mv /var/lib/tasks /var/lib/smylte
  fi
  local s
  for s in "" "-wal" "-shm"; do
    if [ -f "/var/lib/smylte/tasks.db${s}" ] && [ ! -f "/var/lib/smylte/smylte.db${s}" ]; then
      run mv "/var/lib/smylte/tasks.db${s}" "/var/lib/smylte/smylte.db${s}"
    fi
  done

  # 4. The checkout — BEFORE the unit, which names absolute paths inside it.
  #    Safe to do while running because migrate.sh re-execs from a temp copy.
  if [ -d "$RUN_HOME/tasks" ] && [ ! -d "$RUN_HOME/smylte" ]; then
    run mv "$RUN_HOME/tasks" "$RUN_HOME/smylte"
    _repair_venv "$RUN_HOME/smylte/backend/.venv" "$RUN_HOME/tasks" "$RUN_HOME/smylte"
    REPO_DIR="$RUN_HOME/smylte"
  fi
  [ -d "$RUN_HOME/smylte" ] && REPO_DIR="$RUN_HOME/smylte"

  # 5. The Radicale storage hook. Install the new script before retiring the
  #    old: the app accepts BOTH header spellings, so an overlap is harmless
  #    while a gap means live sync silently stops.
  run install -m 0755 "$REPO_DIR/deploy/smylte-notify" /usr/local/bin/smylte-notify
  local radcfg
  for radcfg in /etc/radicale/config /etc/radicale/config.d/*.conf; do
    [ -f "$radcfg" ] || continue
    if grep -q 'tasks-notify' "$radcfg"; then
      run sed -i 's#/usr/local/bin/tasks-notify#/usr/local/bin/smylte-notify#g' "$radcfg"
      run systemctl restart radicale.service || true
    fi
  done
  [ -x /usr/local/bin/tasks-notify ] && run rm -f /usr/local/bin/tasks-notify

  # 6. The unit.
  run install -m 0644 "$REPO_DIR/deploy/smylte.service" "$unit_new"
  run systemctl daemon-reload
  if [ -f "$unit_old" ]; then
    run systemctl disable tasks.service || true
    run rm -f "$unit_old"
    run systemctl daemon-reload
  fi
  run systemctl enable smylte.service

  # 7. The autopull sudoers rule, which names the unit and so moves with it.
  #    Validated into place: a malformed file under /etc/sudoers.d does not
  #    break one rule, it breaks sudo, and you find out when you need it.
  if [ -f /etc/sudoers.d/tasks-autopull ] || [ ! -f /etc/sudoers.d/smylte-autopull ]; then
    # Staged inside the runner's own temp dir, which its EXIT trap already
    # removes — so there is no cleanup here to forget, or to skip on a failure.
    local tmp="${SMYLTE_MIGRATE_TMP:-/tmp}/sudoers.smylte-autopull"
    printf '%s ALL=(root) NOPASSWD: /usr/bin/systemctl restart smylte.service\n' \
      "$RUN_USER" > "$tmp"
    if visudo -cf "$tmp" >/dev/null; then
      run install -m 0440 "$tmp" /etc/sudoers.d/smylte-autopull
      run rm -f /etc/sudoers.d/tasks-autopull
    else
      echo "migrate: generated sudoers rule failed validation; left alone" >&2
    fi
  fi

  # 8. Up on the new name.
  run systemctl start smylte.service
}
