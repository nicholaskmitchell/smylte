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
    || { [ -d "$RUN_HOME/tasks" ] && [ ! -d "$RUN_HOME/smylte" ]; } \
    || [ -f "$RUN_HOME/smylte/deploy/tasks-cloudflared.env" ] \
    || [ -f "$RUN_HOME/tasks/deploy/tasks-cloudflared.env" ]
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
  # Guarded on the LAST thing the block does, not the first. Keyed on the TASKS_
  # names, an interruption between the three seds would leave the two path-value
  # rewrites permanently unapplied: the resuming run finds no TASKS_ left, skips
  # the whole block, and completes with SMYLTE_DB still pointing at /var/lib/tasks.
  if [ -f /etc/smylte/smylte.env ] \
     && grep -qE '^[[:space:]]*TASKS_|/var/lib/tasks/tasks\.db|/home/[^/]*/tasks/' /etc/smylte/smylte.env; then
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
  if [ -d /var/lib/tasks ] && [ -d /var/lib/smylte ]; then
    # Both present. Guessing here risks stranding the only copy of the sidecar
    # tables — parked tasks, day plans, habits, booking client details, display
    # pairings — which exist nowhere on the wire and no resync can rebuild. Stop
    # and let a human look, rather than skip the move, start the service on an
    # empty database and record the migration as done.
    echo "migrate: REFUSING TO CONTINUE — both /var/lib/tasks and /var/lib/smylte exist." >&2
    echo "migrate: /var/lib/tasks may hold the only copy of the sidecar tables." >&2
    echo "migrate: Inspect both, move the database you want to keep to" >&2
    echo "migrate: /var/lib/smylte/smylte.db, remove /var/lib/tasks, and re-run." >&2
    return 1
  fi
  if [ -d /var/lib/tasks ]; then
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
  fi
  [ -d "$RUN_HOME/smylte" ] && REPO_DIR="$RUN_HOME/smylte"
  # OUTSIDE the move, deliberately. The mv above falsifies its own guard, so a
  # run interrupted between the move and the repair would never come back to it
  # — and _repair_venv is itself idempotent (it only rewrites shebangs that
  # still name the old path), so calling it every time costs nothing.
  _repair_venv "$RUN_HOME/smylte/backend/.venv" "$RUN_HOME/tasks" "$RUN_HOME/smylte"

  # 5. The Radicale storage hook. Install the new script before retiring the
  #    old: the app accepts BOTH header spellings, so an overlap is harmless
  #    while a gap means live sync silently stops.
  run install -m 0755 "$REPO_DIR/deploy/smylte-notify" /usr/local/bin/smylte-notify

  # WHERE the hook line lives is deployment-specific, and getting it wrong here
  # is silent: Radicale fires the hook and ignores the result, so a config still
  # naming a script that no longer exists produces no error anywhere — live
  # phone->web sync just stops and the app quietly falls back to its 30s poll.
  # docs/DEPLOY.md puts this deployment's config at ~/radicale/config; the
  # /etc paths are the distro-package default. Search all of them.
  local radcfg repointed=0
  for radcfg in "$RUN_HOME/radicale/config" \
                /etc/radicale/config /etc/radicale/config.d/*.conf \
                /etc/xdg/radicale/config; do
    [ -f "$radcfg" ] || continue
    if grep -q 'tasks-notify' "$radcfg"; then
      run sed -i 's#/usr/local/bin/tasks-notify#/usr/local/bin/smylte-notify#g' "$radcfg"
      repointed=1
    fi
  done
  if [ "$repointed" = 1 ]; then
    run systemctl restart radicale.service || true
    # Only now is nothing pointing at the old script.
    [ -x /usr/local/bin/tasks-notify ] && run rm -f /usr/local/bin/tasks-notify
  elif grep -rqs 'tasks-notify' "$RUN_HOME/radicale" /etc/radicale /etc/xdg/radicale 2>/dev/null; then
    echo "migrate: WARNING — a Radicale config still names tasks-notify but was not" >&2
    echo "migrate: rewritten. Leaving /usr/local/bin/tasks-notify in place. Point the" >&2
    echo "migrate: hook at /usr/local/bin/smylte-notify by hand, then remove the old one." >&2
  else
    # Nothing references it anywhere we can see. Safe to retire.
    [ -x /usr/local/bin/tasks-notify ] && run rm -f /usr/local/bin/tasks-notify
  fi

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

  # 8. The cloudflared connector's env file. deploy/smylte-cloudflared.compose.yml
  #    now names smylte-cloudflared.env, so a deployment still carrying
  #    tasks-cloudflared.env would fail to bring the tunnel up on its next
  #    `docker compose up` — and the tunnel is the only public path to this box.
  #    It is gitignored (it holds TUNNEL_TOKEN), so only a rename is possible here.
  if [ -f "$REPO_DIR/deploy/tasks-cloudflared.env" ] \
     && [ ! -f "$REPO_DIR/deploy/smylte-cloudflared.env" ]; then
    run mv "$REPO_DIR/deploy/tasks-cloudflared.env" "$REPO_DIR/deploy/smylte-cloudflared.env"
  fi

  # 9. Up on the new name.
  run systemctl start smylte.service
}
