#!/usr/bin/env bash
# Install, update or remove the Smylte desk panel on this box.
#
#   sudo ~/smylte/deploy/panel-setup.sh                 install, or update after a pull
#   sudo ~/smylte/deploy/panel-setup.sh --rotate-token  store a new display token
#   sudo ~/smylte/deploy/panel-setup.sh --selftest      power the panel up and down, no refresh
#   sudo ~/smylte/deploy/panel-setup.sh --clear         paint it white (for storage) and stop
#   sudo ~/smylte/deploy/panel-setup.sh --keytest       print what the view key's presses would do
#   sudo ~/smylte/deploy/panel-setup.sh --reset-refresh turn fast and partial refresh back on
#   sudo ~/smylte/deploy/panel-setup.sh --update        update after a pull, unattended (what the desk key runs)
#   sudo ~/smylte/deploy/panel-setup.sh --status        checks, drift, service state
#   sudo ~/smylte/deploy/panel-setup.sh --uninstall     stop, clear, and remove everything
#   sudo ~/smylte/deploy/panel-setup.sh --no-selftest   install without the self-test
#
# Separate from setup.sh on purpose: setup.sh installs the server, CI executes
# it with a handful of commands stubbed out, and most boxes have no panel.
# Wiring, the Settings step and what the journal lines mean are in
# firmware/README.md.
#
# The client runs from a root-owned COPY in /usr/local/lib/smylte-panel, never
# from this checkout, so autopull cannot change the code driving the glass. The
# cost is this script: after pulling a change to firmware/pi_epaper_7in5/ or
# deploy/smylte-panel.service, run it again. `--status` shows whether you need to.
#
# The desk key can do that too: smylte-panel-update.service runs autopull, then
# this script's --update, which installs only what drifted and never prompts.
# It exits 3 when it refuses before changing anything. From the key update's
# snapshot of the panel to the end of its watch, every option but --status
# refuses to start; earlier in the run, the updater waits up to 10 min for a
# run started by hand.
#
# --keytest refuses until logind has been told to ignore the power key (an
# install does that), because otherwise the first press would power the box
# off. --keytest and --reset-refresh stop the service around themselves and
# start it again if it was running, like --selftest and --clear.
set -euo pipefail

REPO=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
SRC=$REPO/firmware/pi_epaper_7in5
LIB=/usr/local/lib/smylte-panel
UNIT_NAME=smylte-panel.service
UNIT_SRC=$REPO/deploy/$UNIT_NAME
UNIT=/etc/systemd/system/$UNIT_NAME
CREDSTORE=/etc/credstore
CRED=$CREDSTORE/smylte-panel-token
# The four settings (PWR pin, refresh mode, idle return, key), written once with
# their defaults. The unit reads it as its EnvironmentFile, and the one-off runs
# below are given it too.
PANEL_ENV=/etc/default/smylte-panel
KEY_GROUP=smylte-panel-key
RULES_SRC=$REPO/deploy/70-smylte-panel-key.rules
RULES=/etc/udev/rules.d/70-smylte-panel-key.rules
PATH_SRC=$REPO/deploy/smylte-panel-poweroff.path
PATH_UNIT=/etc/systemd/system/smylte-panel-poweroff.path
OFF_SRC=$REPO/deploy/smylte-panel-poweroff.service
OFF_UNIT=/etc/systemd/system/smylte-panel-poweroff.service
LOGIND_SRC=$REPO/deploy/logind-smylte-panel.conf
LOGIND=/etc/systemd/logind.conf.d/50-smylte-panel.conf
UPD_PATH_SRC=$REPO/deploy/smylte-panel-update.path
UPD_PATH_UNIT=/etc/systemd/system/smylte-panel-update.path
UPD_SRC=$REPO/deploy/smylte-panel-update.service
UPD_UNIT=/etc/systemd/system/smylte-panel-update.service
UPDATER_SRC=$REPO/deploy/smylte-panel-update.sh
UPDATER=$LIB/update.sh
UPDATE_RUN=/run/smylte-panel-update
RESULT=$UPDATE_RUN/result
SETUP_LOCK=/run/smylte-panel-setup.lock
PY=/usr/bin/python3
PWRKEY=/usr/bin/pwrkey
FILES="panel.py epd7in5_v2.py"

die() { echo "panel-setup: $*" >&2; exit 1; }
say() { echo "== $* =="; }

# A setting in $PANEL_ENV, read as the unit's EnvironmentFile= reads it: the
# last assignment wins and quotes and spaces are dropped. Empty or absent means
# the default, which is what the client uses too.
setting() {   # $1: NAME, $2: DEFAULT
  local v=
  if [ -r "$PANEL_ENV" ]; then
    v=$(sed -n "s/^[[:space:]]*$1[[:space:]]*=//p" "$PANEL_ENV" | tail -n 1)
  fi
  v=${v//[\"\'[:space:]]/}
  printf '%s' "${v:-$2}"
}

# The effective PWR pin: 18 (the Driver HAT) unless set; `none` passes through.
pwr_setting() {
  setting SMYLTE_PANEL_PWR_PIN 18
}

[ "$(id -u)" -eq 0 ] || die "run with sudo"

# One run at a time, the key's update included. The updater holds this lock
# from its snapshot of the panel to the end of its watch, and runs --update
# under it with SMYLTE_PANEL_SETUP_LOCKED=1. A run by hand inside that window
# could be undone by the update's rollback, so it refuses instead. The lock
# file is root's alone, as the updater makes it: an account that could open it
# could hold it. It is never replaced, since a new one would not conflict with
# a holder of the old.
take_lock() {
  local um
  if [ "${SMYLTE_PANEL_SETUP_LOCKED:-}" = 1 ]; then return 0; fi
  um=$(umask)
  umask 077
  exec 8>>"$SETUP_LOCK"
  umask "$um"
  chmod 0600 -- "$SETUP_LOCK" || true
  flock -n 8 || die "an update from the key is running (journalctl -u smylte-panel-update -f); run this again when it is done"
}

# The checkout the key updates: the one smylte.service runs, as the updater
# reads it from the unit. Nothing when smylte.service is not installed.
server_checkout() {
  local wd
  [ "$(systemctl show -P LoadState smylte.service 2>/dev/null || true)" = loaded ] || return 0
  wd=$(systemctl show -P WorkingDirectory smylte.service 2>/dev/null || true)
  printf '%s\n' "${wd%/backend}"
}

# ── preflight ────────────────────────────────────────────────────────────────
# Each check prints its fix. Nothing is written until all of them pass.

# The four settings in $PANEL_ENV, each printed with its effective value.
check_settings() {
  local bad=0 v
  v=$(pwr_setting)
  if [ "${v,,}" = none ]; then
    echo "  ✓ PWR pin: none (right for the Pico module)"
  elif [[ $v =~ ^[0-9]{1,2}$ ]] && (( 10#$v >= 2 && 10#$v <= 27 )) && [[ ! " 7 8 9 10 11 17 24 25 " == *" $((10#$v)) "* ]]; then
    echo "  ✓ PWR pin: BCM$v"
  else
    echo "  ✗ SMYLTE_PANEL_PWR_PIN in $PANEL_ENV is '$v' — set none or a free BCM pin: 2-27, but not 7-11, 17, 24 or 25 (sudoedit $PANEL_ENV)"; bad=1
  fi
  v=$(setting SMYLTE_PANEL_REFRESH fast)
  case "$v" in
    fast|full) echo "  ✓ refresh: $v" ;;
    *) echo "  ✗ SMYLTE_PANEL_REFRESH in $PANEL_ENV is '$v' — set fast or full (sudoedit $PANEL_ENV)"; bad=1 ;;
  esac
  v=$(setting SMYLTE_PANEL_IDLE_RETURN_S 0)
  if [[ $v =~ ^[0-9]{1,5}$ ]] && { [ $((10#$v)) -eq 0 ] || { [ $((10#$v)) -ge 60 ] && [ $((10#$v)) -le 86400 ]; }; }; then
    echo "  ✓ idle return: $v s"
  else
    echo "  ✗ SMYLTE_PANEL_IDLE_RETURN_S in $PANEL_ENV is '$v' — set 0, or a number of seconds from 60 to 86400 (sudoedit $PANEL_ENV)"; bad=1
  fi
  v=$(setting SMYLTE_PANEL_KEY auto)
  case "$v" in
    auto|off) echo "  ✓ key: $v" ;;
    *) echo "  ✗ SMYLTE_PANEL_KEY in $PANEL_ENV is '$v' — set auto or off (sudoedit $PANEL_ENV)"; bad=1 ;;
  esac
  return "$bad"
}

# The desktop images act on the power key whatever logind says: labwc runs
# pwrkey on release, and a second press while its dialog is open shuts down.
# Only the key being on matters, and only a desktop that starts at boot is
# refused.
check_desktop() {
  [ "$(setting SMYLTE_PANEL_KEY auto)" != off ] && [ -x "$PWRKEY" ] || return 0
  if [ "$(systemctl get-default 2>/dev/null || true)" = graphical.target ]; then
    echo "  ✗ a desktop is installed and starts at boot: its labwc runs pwrkey on the power key (a press opens Shutdown options, a second press shuts down) whatever logind says — use Raspberry Pi OS Lite"
    return 1
  fi
  echo "  ! a desktop is installed but not started at boot; starting it makes a second press of the key shut down"
}

preflight() {
  local bad=0 v
  if [ ! -x "$PY" ]; then
    echo "  ✗ $PY missing"; bad=1
  else
    v=$("$PY" -I -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)
    # The same arm as setup.sh: the interpreters CI runs the client's tests on.
    case "$v" in
      3.12|3.13) echo "  ✓ $PY is $v" ;;
      *) echo "  ✗ $PY is '${v:-unreadable}', not 3.12 or 3.13 — use Raspberry Pi OS (Trixie), not Legacy"; bad=1 ;;
    esac
    if "$PY" -I -c 'import gpiod, spidev, sys; sys.exit(int(gpiod.__version__.split(".")[0]) < 2)' 2>/dev/null; then
      echo "  ✓ python3-libgpiod (v2) and python3-spidev"
    else
      echo "  ✗ gpiod v2 or spidev not importable — sudo apt install python3-libgpiod python3-spidev"; bad=1
    fi
  fi
  if [ -c /dev/spidev0.0 ]; then
    echo "  ✓ /dev/spidev0.0"
  else
    echo "  ✗ /dev/spidev0.0 missing — sudo raspi-config nonint do_spi 0, then reboot"; bad=1
  fi
  if grep -qE '^ *[0-9]+ spi$' /proc/devices && grep -qE '^ *[0-9]+ gpiochip$' /proc/devices; then
    echo "  ✓ /proc/devices lists spi and gpiochip (the unit's DeviceAllow names)"
  else
    echo "  ✗ /proc/devices lacks spi or gpiochip — the unit's DeviceAllow lines would match nothing"; bad=1
  fi
  for g in gpio spi; do
    if getent group "$g" >/dev/null; then echo "  ✓ group $g"; else
      echo "  ✗ no group $g — this does not look like Raspberry Pi OS"; bad=1; fi
  done
  if command -v gpiodetect >/dev/null; then
    if [ "$(gpiodetect 2>/dev/null | grep -c '\[pinctrl-rp1\]')" -eq 1 ]; then
      echo "  ✓ one GPIO chip labelled pinctrl-rp1"
    else
      echo "  ✗ gpiodetect does not show exactly one [pinctrl-rp1] — is this a Pi 5?"; bad=1
    fi
  else
    echo "  ? gpiodetect not installed (sudo apt install gpiod) — chip not checked"
  fi
  check_settings || bad=1
  check_desktop || bad=1
  return "$bad"
}

# ── the token ────────────────────────────────────────────────────────────────
# Read without echo. A pasted URL is accepted and cut down to the token. Only
# the first four characters are ever printed, as the server's own log does.
TOKEN=
read_token() {
  local raw tok
  echo "Paste the display's token, or its whole URL (Settings → Displays)."
  IFS= read -rsp "Token: " raw; echo
  case "$raw" in
    */display/*) tok=${raw#*/display/}; tok=${tok%%[.?/#]*} ;;
    *) tok=$raw ;;
  esac
  tok=${tok//[[:space:]]/}
  [[ $tok =~ ^[A-Za-z0-9_-]{22,128}$ ]] || die "that is not a display token (22–128 of A–Z a–z 0–9 _ -)"
  TOKEN=$tok
}

# The token goes to Python on stdin, never on a command line. The request is
# the client's own view target, so the answer says whether Desk key is on for
# this display and whether smylted is new enough to have it.
probe_token() {
  local out
  out=$(printf '%s' "$TOKEN" | "$PY" -I -c '
import http.client, sys
t = sys.stdin.read()
c = http.client.HTTPConnection("127.0.0.1", 8080, timeout=10)
try:
    c.request("HEAD", "/api/public/display/%s.bin?invert=1&w=800&h=480&mode=habits&tabs=1" % t)
    r = c.getresponse()
    print(r.status, r.getheader("X-Display-Mode") or "-",
          r.getheader("X-Display-Error") or "-",
          r.getheader("X-Display-Format") or "-")
except OSError as e:
    print("down", type(e).__name__)
finally:
    c.close()
' 2>/dev/null || echo "down probe-failed")
  # out is: status, X-Display-Mode, X-Display-Error, X-Display-Format
  case "$out" in
    "200 habits - mono-hlsb-inverted") echo "  ✓ the server knows ${TOKEN:0:4}… and serves this panel's format, and Desk key is on" ;;
    "422 "*" views-off "*) echo "  ! Desk key is off for this display: turn it on in Settings → Displays (the panel shows the display's own view until then)" ;;
    "200 - "*) echo "  ! smylted is too old for the desk key: pull and restart it ($out)" ;;
    404*) echo "  ! the server does not know ${TOKEN:0:4}… (404) — check Settings → Displays; the panel will keep retrying" ;;
    down*) echo "  ! smylted is not answering on 127.0.0.1:8080 ($out) — the panel will retry until it does" ;;
    *) echo "  ! unexpected answer from the server: $out" ;;
  esac
}

store_token() {
  local tmp
  install -d -m 0700 -o root -g root "$CREDSTORE"
  tmp=$(umask 077 && mktemp "$CREDSTORE/.smylte-panel-token.XXXXXX")
  printf '%s\n' "$TOKEN" >"$tmp"
  chown root:root "$tmp"
  chmod 0600 "$tmp"
  mv -f "$tmp" "$CRED"
  echo "  ✓ stored ${TOKEN:0:4}… in $CRED (root, 0600; the unit loads it as a credential)"
}

# ── one-off runs under the service's own sandbox ─────────────────────────────
# --selftest and --clear need the GPIO lines, so the service is stopped first.
# They run as a transient unit with the same identity, device rules and PWR
# setting as the service, then the lines are driven low again whatever
# happened.
WAS_ACTIVE=no
# The transient unit that is running right now, so that a Ctrl-C can stop it
# before the service is started again (systemd-run does not pass SIGINT on).
ONEOFF=
stop_service() {
  local state
  state=$(systemctl show -P ActiveState "$UNIT_NAME" 2>/dev/null || true)
  case "$state" in
    # A unit waiting out RestartSec after a fault reads "activating", not
    # "active", and only a stop cancels the restart it is waiting to make.
    active|activating|reloading|refreshing) WAS_ACTIVE=yes ;;
    deactivating) ;;    # a stop is under way: wait for it below
    *) return 0 ;;      # inactive or failed: nothing holds the lines
  esac
  echo "  stopping $UNIT_NAME (it finishes any refresh first)"
  systemctl stop "$UNIT_NAME"
}

# Every start this script makes is deliberate, so it clears the unit's start
# count first. StartLimitBurst counts manual starts too, and a bring-up that
# re-runs this script within the hour would otherwise be refused.
start_service() {   # $1: start or restart
  systemctl reset-failed "$UNIT_NAME" 2>/dev/null || true
  systemctl "$1" "$UNIT_NAME"
}

# Every arm that stops the service sets a trap on this just before the stop
# (WAS_ACTIVE is only set once the stop is under way), so that a failure or
# Ctrl-C, even during the stop itself, does not leave a running panel stopped.
# An arm that starts the service itself clears the trap first.
restart_if_was_active() {
  # A one-off still running holds the lines. Stop it (that waits for any
  # refresh), then do the --power-off that run_oneoff would have done.
  if [ -n "$ONEOFF" ]; then
    systemctl stop "$ONEOFF" 2>/dev/null || true
    SMYLTE_PANEL_PWR_PIN=$(pwr_setting) "$PY" -I -B "$LIB/panel.py" --power-off || true
    ONEOFF=
  fi
  [ "$WAS_ACTIVE" = yes ] || return 0
  systemctl is-active --quiet "$UNIT_NAME" || start_service start || true
}

# On a normal exit the EXIT trap restarts the panel. Ctrl-C or a TERM restart
# it too and then END the script (130/143): a bash trap that returns would
# otherwise let the arm run on after the signal.
arm_restart_trap() {
  trap 'restart_if_was_active' EXIT
  trap 'restart_if_was_active; trap - EXIT; exit 130' INT
  trap 'restart_if_was_active; trap - EXIT; exit 143' TERM
}
disarm_restart_trap() { trap - EXIT INT TERM; }

run_oneoff() {   # $1: --selftest, --clear or --reset-refresh
  local rc=0
  ONEOFF="smylte-panel-${1#--}.service"
  systemd-run --quiet --wait --pipe --collect \
    --unit="smylte-panel-${1#--}" \
    -p TimeoutStopSec=120 \
    -p DynamicUser=yes -p "SupplementaryGroups=gpio spi" \
    -p StateDirectory=smylte-panel -p StateDirectoryMode=0700 \
    -p DevicePolicy=closed -p "DeviceAllow=char-spi rw" -p "DeviceAllow=char-gpiochip rw" \
    -p NoNewPrivileges=yes -p ProtectSystem=strict -p ProtectHome=yes \
    -p "EnvironmentFile=-$PANEL_ENV" \
    "$PY" -I -B "$LIB/panel.py" "$1" || rc=$?
  ONEOFF=
  SMYLTE_PANEL_PWR_PIN=$(pwr_setting) "$PY" -I -B "$LIB/panel.py" --power-off || true
  return "$rc"
}

drift() {   # prints the files whose installed copy differs from the checkout
  local f out=
  for f in $FILES; do cmp -s "$SRC/$f" "$LIB/$f" || out="$out $f"; done
  cmp -s "$UNIT_SRC" "$UNIT" || out="$out $UNIT_NAME"
  cmp -s "$RULES_SRC" "$RULES" || out="$out ${RULES##*/}"
  cmp -s "$PATH_SRC" "$PATH_UNIT" || out="$out ${PATH_UNIT##*/}"
  cmp -s "$OFF_SRC" "$OFF_UNIT" || out="$out ${OFF_UNIT##*/}"
  cmp -s "$UPD_PATH_SRC" "$UPD_PATH_UNIT" || out="$out ${UPD_PATH_UNIT##*/}"
  cmp -s "$UPD_SRC" "$UPD_UNIT" || out="$out ${UPD_UNIT##*/}"
  cmp -s "$UPDATER_SRC" "$UPDATER" || out="$out ${UPDATER##*/}"
  if [ "$(setting SMYLTE_PANEL_KEY auto)" != off ]; then
    cmp -s "$LOGIND_SRC" "$LOGIND" || out="$out ${LOGIND##*/}"
  elif [ -e "$LOGIND" ]; then
    out="$out ${LOGIND##*/}(present, but KEY is off)"
  fi
  echo "${out# }"
}

# The last HandlePowerKey* line logind would read, from all of its configuration.
logind_setting() {   # $1: HandlePowerKey or HandlePowerKeyLongPress
  local v
  v=$(systemd-analyze cat-config systemd/logind.conf 2>/dev/null \
      | sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" | tail -n 1 || true)
  printf '%s\n' "${v//[[:space:]]/}"
}

# The same setting as the running logind has it, which is what acts on a press:
# the files are only what it reads on its next reload. Empty if it cannot be asked.
logind_running() {   # $1: HandlePowerKey or HandlePowerKeyLongPress
  busctl --value get-property org.freedesktop.login1 /org/freedesktop/login1 \
    org.freedesktop.login1.Manager "$1" 2>/dev/null || true
}

# Warns, never fails: the node can be missing on a board without the key.
check_key_node() {
  local d n dev g found=no
  for d in /sys/class/input/event*/device/name; do
    [ -r "$d" ] || continue
    n=$(cat "$d" 2>/dev/null || true)
    [ "$n" = pwr_button ] || continue
    found=yes
    dev=${d#/sys/class/input/}; dev=${dev%%/*}
    g=$(stat -c %G "/dev/input/$dev" 2>/dev/null || echo unknown)
    if [ "$g" = "$KEY_GROUP" ]; then
      echo "  ✓ /dev/input/$dev (pwr_button) is group $KEY_GROUP"
    else
      echo "  ! /dev/input/$dev is group $g, not $KEY_GROUP — the udev rule did not apply"
    fi
  done
  if [ "$found" = no ]; then
    echo "  ! no pwr_button input device (gpio_keys not loaded?)"
  fi
  return 0
}

# Told to ignore the key, logind no longer powers the box off on a press. The
# service is started after this, so a tap while it starts cannot power off.
apply_logind() {
  if systemctl reload systemd-logind; then
    echo "  ✓ logind reloaded"
  else
    echo "  ✗ logind did not reload: a press may still power the box off until the next boot"
  fi
}

# Only when the file is missing: it holds the owner's edits after that.
write_settings() {
  local tmp
  if [ -e "$PANEL_ENV" ]; then
    echo "  kept $PANEL_ENV (yours)"
    return 0
  fi
  tmp=$(umask 077 && mktemp "$PANEL_ENV.XXXXXX")
  cat >"$tmp" <<'EOF'
# Smylte desk panel settings. Edit with: sudoedit /etc/default/smylte-panel
# Then: sudo systemctl restart smylte-panel (and re-run panel-setup.sh if you change KEY).
#
# The e-Paper Driver HAT switches the panel's power on BCM18. The Pico module
# ignores it (GPIO18 is unconnected there). `none` turns it off.
SMYLTE_PANEL_PWR_PIN=18
# fast: partial and fast refreshes, key and routine alike, with a full one after every 5 (panels sold after Sept 2023). full: full refreshes only.
SMYLTE_PANEL_REFRESH=fast
# Seconds with no key before the screen goes back to Today. 0 is off; otherwise 60-86400.
SMYLTE_PANEL_IDLE_RETURN_S=0
# auto: use the key. off: leave it to the OS (a press powers the box off).
SMYLTE_PANEL_KEY=auto
EOF
  chown root:root "$tmp"
  chmod 0644 "$tmp"
  mv -f "$tmp" "$PANEL_ENV"
  echo "  wrote $PANEL_ENV (the defaults)"
}

show_service() {
  systemctl --no-pager --lines=0 status "$UNIT_NAME" || true
  journalctl --no-pager -u "$UNIT_NAME" -n 20 || true
}

# Written beside the old copy and renamed over it, so a crash or a power cut
# leaves the old file or the new one, never half of one. The key's update runs
# the client from these files.
put() {   # $1: mode, $2: source, $3: destination
  install -m "$1" -o root -g root -- "$2" "$3.new" && mv -f -- "$3.new" "$3"
}

install_files() {
  # The updater installed here is the one the next key press runs: one that
  # does not parse would leave the key unable to update anything again.
  bash -n "$UPDATER_SRC" || die "$UPDATER_SRC does not parse (above); nothing installed"
  say "group $KEY_GROUP, udev rule, power-off and update units, logind drop-in"
  getent group "$KEY_GROUP" >/dev/null || groupadd --system "$KEY_GROUP"
  put 0644 "$RULES_SRC" "$RULES"
  udevadm control --reload
  udevadm trigger --action=change --subsystem-match=input
  udevadm settle
  put 0644 "$PATH_SRC" "$PATH_UNIT"
  put 0644 "$OFF_SRC" "$OFF_UNIT"
  put 0644 "$UPD_PATH_SRC" "$UPD_PATH_UNIT"
  put 0644 "$UPD_SRC" "$UPD_UNIT"
  if [ "$(setting SMYLTE_PANEL_KEY auto)" != off ]; then
    install -d -m 0755 -o root -g root "${LOGIND%/*}"
    put 0644 "$LOGIND_SRC" "$LOGIND"
  else
    rm -f "$LOGIND"
  fi
  say "code -> $LIB, unit -> $UNIT"
  install -d -m 0755 -o root -g root "$LIB"
  for f in $FILES; do put 0644 "$SRC/$f" "$LIB/$f"; done
  # Run by bash, so it needs no execute bit.
  put 0644 "$UPDATER_SRC" "$UPDATER"
  put 0644 "$UNIT_SRC" "$UNIT"
  systemd-analyze verify "$UNIT" "$PATH_UNIT" "$OFF_UNIT" "$UPD_PATH_UNIT" "$UPD_UNIT" || echo "  ! systemd-analyze verify complained (above); continuing"
  systemctl daemon-reload
}

MODE=${1:-install}
NO_SELFTEST=no
if [ "$MODE" = "--no-selftest" ]; then MODE=install; NO_SELFTEST=yes; fi
[ $# -le 1 ] || die "one option at a time"

case "$MODE" in
  install)
    take_lock
    say "preflight"
    preflight || die "fix the ✗ lines above, then run this again"
    say "settings"
    write_settings
    install_files
    say "power key"
    check_key_node
    apply_logind
    say "power-off request unit"
    systemctl enable smylte-panel-poweroff.path
    systemctl start smylte-panel-poweroff.path
    say "update request unit"
    systemctl enable smylte-panel-update.path
    systemctl start smylte-panel-update.path
    sc=$(server_checkout)
    if [ -z "$sc" ]; then
      echo "  ! smylte.service is not installed: the key cannot update this box"
    elif [ "$sc" != "$REPO" ]; then
      echo "  ! smylte.service runs $sc: the key updates that checkout, not this one"
    fi
    say "display token"
    if [ -s "$CRED" ]; then
      echo "  ✓ $CRED exists (--rotate-token to replace it)"
      TOKEN=$(tr -d '\r\n' <"$CRED")
      probe_token
    else
      read_token; probe_token; store_token
    fi
    if [ "$NO_SELFTEST" = no ]; then
      say "self-test (power up, power down, no refresh)"
      arm_restart_trap
      stop_service
      if ! run_oneoff --selftest; then
        disarm_restart_trap
        echo "  ✗ self-test failed — the lines above say where. Wiring and power are in firmware/README.md."
        echo "    The service is installed but NOT started. Re-run this script once it is fixed,"
        echo "    or skip the test with --no-selftest."
        exit 1
      fi
    fi
    say "service"
    # restart, not enable --now: on an update the unit is already running the
    # old code, and `start` on an active unit does nothing (see setup.sh).
    systemctl enable "$UNIT_NAME"
    start_service restart
    disarm_restart_trap
    show_service
    echo
    echo "The first refresh comes once the clock has synced and the 180 s floor has"
    echo "passed: up to about five minutes. Watch: journalctl -u $UNIT_NAME -f"
    ;;
  --update)
    # Run by the key's updater, with nothing on stdin. The last line is the
    # outcome it reads. Exit 3: refused, and nothing was changed. It reads no
    # token, probes nothing and runs no self-test.
    take_lock
    say "preflight"
    if ! preflight; then
      echo "panel: refused: preflight failed (above)"
      exit 3
    fi
    if [ ! -s "$CRED" ]; then
      echo "panel: refused: no token stored — run panel-setup.sh"
      exit 3
    fi
    sc=$(server_checkout)
    if [ "$sc" != "$REPO" ]; then
      echo "panel: refused: smylte.service runs $sc, not $REPO"
      exit 3
    fi
    d=$(drift)
    if [ -z "$d" ]; then
      echo "panel: up to date"
      exit 0
    fi
    say "settings"
    write_settings
    install_files
    say "power key"
    check_key_node
    apply_logind
    say "request units"
    systemctl enable smylte-panel-poweroff.path
    systemctl start smylte-panel-poweroff.path
    systemctl enable smylte-panel-update.path
    systemctl start smylte-panel-update.path
    say "service"
    systemctl enable "$UNIT_NAME"
    start_service restart
    echo "panel: updated"
    ;;
  --rotate-token)
    take_lock
    say "display token"
    read_token; probe_token; store_token
    # The client reads the token once, at start. Restart it if it is running,
    # waiting to restart, or failed (a bad token fails it); leave a stopped one
    # stopped, such as a panel cleared for storage.
    state=$(systemctl show -P ActiveState "$UNIT_NAME" 2>/dev/null || true)
    case "$state" in
      active|activating|reloading|refreshing|failed)
        start_service restart
        echo "  ✓ restarted $UNIT_NAME" ;;
      *) echo "  $UNIT_NAME is not running; it reads the new token when it next starts" ;;
    esac
    ;;
  --selftest|--clear)
    take_lock
    [ -f "$LIB/panel.py" ] || die "not installed — run this script without options first"
    say "${MODE#--}"
    arm_restart_trap
    stop_service
    rc=0; run_oneoff "$MODE" || rc=$?
    if [ "$MODE" = --clear ]; then
      # Stopped on purpose, so it should read "inactive" even if it had failed
      # before the clear: --rotate-token then leaves a stored panel stopped.
      systemctl reset-failed "$UNIT_NAME" 2>/dev/null || true
      # A successful clear must stay stopped, so the trap must not restart it.
      if [ "$rc" -eq 0 ]; then disarm_restart_trap; fi
      if [ "$rc" -eq 0 ]; then echo "  ✓ cleared to white"
        echo "  The service is stopped and the panel is unpowered. It starts again at boot,"
        echo "  or now with: sudo systemctl start $UNIT_NAME"
      else
        echo "  ✗ the clear failed (above); the glass may still show a frame."
        echo "  The service is started again if it was running before."
      fi
    elif [ "$WAS_ACTIVE" = yes ]; then
      start_service start
      disarm_restart_trap
    fi
    exit "$rc"
    ;;
  --keytest)
    take_lock
    [ -f "$LIB/panel.py" ] || die "not installed — run this script without options first"
    say "keytest"
    # The first press would power the box off if the running logind still handled
    # the key, whatever its files say. An empty answer (busctl failed) refuses too.
    if [ "$(logind_running HandlePowerKey)" != ignore ]; then
      echo "  ✗ logind (running) would power the box off on the first press; run 'sudo systemctl reload systemd-logind', or this script without options"
      exit 1
    fi
    arm_restart_trap
    stop_service
    # Reads the key and nothing else: no gpio or spi, no state directory.
    rc=0
    ONEOFF=smylte-panel-keytest.service
    systemd-run --wait --pipe --collect \
      --unit=smylte-panel-keytest \
      -p DynamicUser=yes -p "SupplementaryGroups=$KEY_GROUP" \
      -p DevicePolicy=closed -p "DeviceAllow=char-input r" \
      -p NoNewPrivileges=yes -p ProtectSystem=strict -p ProtectHome=yes \
      -p "EnvironmentFile=-$PANEL_ENV" \
      "$PY" -I -B "$LIB/panel.py" --keytest || rc=$?
    ONEOFF=
    if [ "$WAS_ACTIVE" = yes ]; then
      start_service start
    fi
    disarm_restart_trap
    exit "$rc"
    ;;
  --reset-refresh)
    take_lock
    [ -f "$LIB/panel.py" ] || die "not installed — run this script without options first"
    say "reset-refresh"
    arm_restart_trap
    stop_service
    rc=0; run_oneoff --reset-refresh || rc=$?
    if [ "$WAS_ACTIVE" = yes ]; then
      start_service start
    fi
    disarm_restart_trap
    exit "$rc"
    ;;
  --status)
    say "preflight"
    preflight || true
    say "installed copy"
    if [ ! -f "$LIB/panel.py" ]; then
      echo "  not installed"
    else
      d=$(drift)
      if [ -z "$d" ]; then echo "  ✓ matches $REPO"; else
        echo "  ! differs from the checkout: $d — run this script to update"; fi
    fi
    if [ -s "$CRED" ]; then echo "  ✓ token stored"; else echo "  ✗ no token stored"; fi
    say "power key"
    for k in HandlePowerKey HandlePowerKeyLongPress; do
      r=$(logind_running "$k")
      echo "  logind $k=$(logind_setting "$k" | sed 's/^$/(unset)/') (file) / ${r:-unreadable} (running)"
    done
    echo "  smylte-panel-poweroff.path: enabled=$(systemctl is-enabled smylte-panel-poweroff.path 2>/dev/null || true)" \
         "active=$(systemctl is-active smylte-panel-poweroff.path 2>/dev/null || true)"
    check_key_node
    say "update from the key"
    echo "  smylte-panel-update.path: enabled=$(systemctl is-enabled smylte-panel-update.path 2>/dev/null || true)" \
         "active=$(systemctl is-active smylte-panel-update.path 2>/dev/null || true)"
    if [ -f "$RESULT" ] && [ ! -L "$RESULT" ]; then
      echo "  last result: $(head -n 1 -- "$RESULT")"
    fi
    journalctl --no-pager -u smylte-panel-update -n 15 || true
    # The pull's reasons are in the owner's log, not the journal. Read as the
    # owner, so a symlink there cannot show root's files.
    owner=$(systemctl show -P User smylte.service 2>/dev/null || true)
    if [ -n "$owner" ]; then
      home=$(getent passwd "$owner" | cut -d: -f6 || true)
      echo "  the end of $home/smylte-autopull.log:"
      runuser -u "$owner" -- tail -n 20 -- "$home/smylte-autopull.log" 2>/dev/null || echo "  (unreadable)"
    fi
    say "service"
    show_service
    ;;
  --uninstall)
    take_lock
    say "stopping"
    systemctl disable --now "$UNIT_NAME" 2>/dev/null || true
    if [ -f "$LIB/panel.py" ]; then
      say "clearing the glass to white"
      run_oneoff --clear || echo "  ! clear failed; continuing with the removal"
    fi
    say "removing the power key's files"
    systemctl disable --now smylte-panel-poweroff.path 2>/dev/null || true
    rm -f "$PATH_UNIT" "$OFF_UNIT"
    systemctl disable --now smylte-panel-update.path 2>/dev/null || true
    rm -f "$UPD_PATH_UNIT" "$UPD_UNIT"
    rm -rf "$UPDATE_RUN"
    # With the drop-in gone, logind's default is back: a press powers the box off.
    rm -f "$LOGIND"
    apply_logind
    rm -f "$RULES"
    udevadm control --reload
    udevadm trigger --action=change --subsystem-match=input
    udevadm settle
    groupdel "$KEY_GROUP" 2>/dev/null || true
    say "removing"
    # Including what `systemctl edit` added and the settings file, so a later
    # install starts from the shipped unit.
    rm -f "$UNIT" "$CRED" "$PANEL_ENV"
    rm -rf "$UNIT.d" "$LIB" /var/lib/private/smylte-panel
    rm -f /var/lib/smylte-panel
    systemctl daemon-reload
    echo "  Removed. Delete the display in Settings → Displays too, so its token stops working."
    ;;
  *)
    die "unknown option '$MODE' (see the top of this file)"
    ;;
esac
