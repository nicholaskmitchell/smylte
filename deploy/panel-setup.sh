#!/usr/bin/env bash
# Install, update or remove the Smylte desk panel on this box.
#
#   sudo ~/smylte/deploy/panel-setup.sh                 install, or update after a pull
#   sudo ~/smylte/deploy/panel-setup.sh --rotate-token  store a new display token
#   sudo ~/smylte/deploy/panel-setup.sh --selftest      power the panel up and down, no refresh
#   sudo ~/smylte/deploy/panel-setup.sh --clear         paint it white (for storage) and stop
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
set -euo pipefail

REPO=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
SRC=$REPO/firmware/pi_epaper_7in5
LIB=/usr/local/lib/smylte-panel
UNIT_NAME=smylte-panel.service
UNIT_SRC=$REPO/deploy/$UNIT_NAME
UNIT=/etc/systemd/system/$UNIT_NAME
CREDSTORE=/etc/credstore
CRED=$CREDSTORE/smylte-panel-token
# Optional, and only for a Driver HAT: SMYLTE_PANEL_PWR_PIN=18. The unit reads
# it as its EnvironmentFile, and the one-off runs below are given it too.
PANEL_ENV=/etc/default/smylte-panel
PY=/usr/bin/python3
FILES="panel.py epd7in5_v2.py"

die() { echo "panel-setup: $*" >&2; exit 1; }
say() { echo "== $* =="; }

# The PWR pin in $PANEL_ENV, read as the unit's EnvironmentFile= reads it: the
# last assignment wins and quotes are dropped. Empty when there is none.
pwr_setting() {
  local v=
  if [ -r "$PANEL_ENV" ]; then
    v=$(sed -n 's/^[[:space:]]*SMYLTE_PANEL_PWR_PIN[[:space:]]*=//p' "$PANEL_ENV" | tail -n 1)
  fi
  v=${v//[\"\'[:space:]]/}
  printf '%s' "$v"
}

[ "$(id -u)" -eq 0 ] || die "run with sudo"

# ── preflight ────────────────────────────────────────────────────────────────
# Each check prints its fix. Nothing is written until all of them pass.
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
  v=$(pwr_setting)
  if [ -z "$v" ]; then
    echo "  ✓ no PWR pin (right for the Pico module; a Driver HAT sets one in $PANEL_ENV)"
  elif [[ $v =~ ^[0-9]{1,2}$ ]]; then
    echo "  ✓ PWR pin BCM$v, from $PANEL_ENV"
  else
    echo "  ✗ SMYLTE_PANEL_PWR_PIN in $PANEL_ENV is '$v', not a BCM pin number"; bad=1
  fi
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

# The token goes to Python on stdin, never on a command line.
probe_token() {
  local out
  out=$(printf '%s' "$TOKEN" | "$PY" -I -c '
import http.client, sys
t = sys.stdin.read()
c = http.client.HTTPConnection("127.0.0.1", 8080, timeout=10)
try:
    c.request("HEAD", "/api/public/display/%s.bin?invert=1&w=800&h=480" % t)
    r = c.getresponse()
    print(r.status, r.getheader("X-Display-Format") or "-")
except OSError as e:
    print("down", type(e).__name__)
finally:
    c.close()
' 2>/dev/null || echo "down probe-failed")
  case "$out" in
    "200 mono-hlsb-inverted") echo "  ✓ the server knows ${TOKEN:0:4}… and serves this panel's format" ;;
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

run_oneoff() {   # $1: --selftest or --clear
  local rc=0
  systemd-run --quiet --wait --pipe --collect \
    --unit="smylte-panel-${1#--}" \
    -p DynamicUser=yes -p "SupplementaryGroups=gpio spi" \
    -p StateDirectory=smylte-panel -p StateDirectoryMode=0700 \
    -p DevicePolicy=closed -p "DeviceAllow=char-spi rw" -p "DeviceAllow=char-gpiochip rw" \
    -p NoNewPrivileges=yes -p ProtectSystem=strict -p ProtectHome=yes \
    -p "EnvironmentFile=-$PANEL_ENV" \
    "$PY" -I -B "$LIB/panel.py" "$1" || rc=$?
  SMYLTE_PANEL_PWR_PIN=$(pwr_setting) "$PY" -I -B "$LIB/panel.py" --power-off || true
  return "$rc"
}

drift() {   # prints the files whose installed copy differs from the checkout
  local f out=
  for f in $FILES; do cmp -s "$SRC/$f" "$LIB/$f" || out="$out $f"; done
  cmp -s "$UNIT_SRC" "$UNIT" || out="$out $UNIT_NAME"
  echo "${out# }"
}

show_service() {
  systemctl --no-pager --lines=0 status "$UNIT_NAME" || true
  journalctl --no-pager -u "$UNIT_NAME" -n 20 || true
}

install_files() {
  say "code -> $LIB, unit -> $UNIT"
  install -d -m 0755 -o root -g root "$LIB"
  for f in $FILES; do install -m 0644 -o root -g root "$SRC/$f" "$LIB/$f"; done
  install -m 0644 -o root -g root "$UNIT_SRC" "$UNIT"
  systemd-analyze verify "$UNIT" || echo "  ! systemd-analyze verify complained (above); continuing"
  systemctl daemon-reload
}

MODE=${1:-install}
NO_SELFTEST=no
if [ "$MODE" = "--no-selftest" ]; then MODE=install; NO_SELFTEST=yes; fi
[ $# -le 1 ] || die "one option at a time"

case "$MODE" in
  install)
    say "preflight"
    preflight || die "fix the ✗ lines above, then run this again"
    install_files
    say "display token"
    if [ -s "$CRED" ]; then
      echo "  ✓ $CRED exists (--rotate-token to replace it)"
    else
      read_token; probe_token; store_token
    fi
    if [ "$NO_SELFTEST" = no ]; then
      say "self-test (power up, power down, no refresh)"
      stop_service
      if ! run_oneoff --selftest; then
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
    show_service
    echo
    echo "The first refresh comes once the clock has synced and the 180 s floor has"
    echo "passed: up to about five minutes. Watch: journalctl -u $UNIT_NAME -f"
    ;;
  --rotate-token)
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
    [ -f "$LIB/panel.py" ] || die "not installed — run this script without options first"
    say "${MODE#--}"
    stop_service
    rc=0; run_oneoff "$MODE" || rc=$?
    if [ "$MODE" = --clear ]; then
      # Stopped on purpose, so it should read "inactive" even if it had failed
      # before the clear: --rotate-token then leaves a stored panel stopped.
      systemctl reset-failed "$UNIT_NAME" 2>/dev/null || true
      if [ "$rc" -eq 0 ]; then echo "  ✓ cleared to white"; else
        echo "  ✗ the clear failed (above); the glass may still show a frame"; fi
      echo "  The service is stopped and the panel is unpowered. It starts again at boot,"
      echo "  or now with: sudo systemctl start $UNIT_NAME"
    elif [ "$WAS_ACTIVE" = yes ]; then
      start_service start
    fi
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
    say "service"
    show_service
    ;;
  --uninstall)
    say "stopping"
    systemctl disable --now "$UNIT_NAME" 2>/dev/null || true
    if [ -f "$LIB/panel.py" ]; then
      say "clearing the glass to white"
      run_oneoff --clear || echo "  ! clear failed; continuing with the removal"
    fi
    say "removing"
    # Including what `systemctl edit` added and the PWR setting, so a later
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
