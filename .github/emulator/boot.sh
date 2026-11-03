#!/usr/bin/env bash
# Boots the emulator the smoke checks run on (smoke.py), for
# android-emulator.yml: installs the emulator and the API level's google_apis
# x86_64 image, creates an AVD, starts the emulator with no window, and returns
# once Android has finished booting. Shell only for booting; everything done on
# the booted device is smoke.py's.
#
# Environment:
#   API_LEVEL     the API level to boot (30, 35, ...); required
#   SMYLTE_DIAG   where the logs go (emulator.log, logcat-all.txt, ...); required
#   ANDROID_HOME  the Android SDK, as GitHub's ubuntu runners set it
#   EMULATOR_GPU  the -gpu mode, default "software" (`emulator -help-gpu`)
#   BOOT_TIMEOUT  seconds to wait for the boot, default 600
#
# Leaves the emulator (pid in emulator.pid) and a logcat capture of the whole
# run (logcat.pid) running; the workflow's last steps stop both.
set -euo pipefail

: "${API_LEVEL:?API_LEVEL is not set}"
: "${SMYLTE_DIAG:?SMYLTE_DIAG is not set}"
GPU=${EMULATOR_GPU:-software}
BOOT_TIMEOUT=${BOOT_TIMEOUT:-600}
SERIAL="emulator-5554"
AVD=smylte
IMAGE="system-images;android-${API_LEVEL};google_apis;x86_64"

mkdir -p "$SMYLTE_DIAG"

log() { printf '[boot %s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
fail() {
  printf '::error title=Emulator boot (API %s)::%s\n' "$API_LEVEL" "$*"
  if [ -f "$SMYLTE_DIAG/emulator.log" ]; then
    echo "--- the last 80 lines of emulator.log ---"
    tail -n 80 "$SMYLTE_DIAG/emulator.log" || true
  fi
  exit 1
}

case "$API_LEVEL" in
  '' | *[!0-9]*) fail "API_LEVEL must be a number, not '$API_LEVEL'" ;;
esac

sdk=${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}
[ -n "$sdk" ] && [ -d "$sdk" ] || fail "ANDROID_HOME does not name the Android SDK"
sdkmanager="$sdk/cmdline-tools/latest/bin/sdkmanager"
avdmanager="$sdk/cmdline-tools/latest/bin/avdmanager"
emulator="$sdk/emulator/emulator"
adb="$sdk/platform-tools/adb"
[ -x "$sdkmanager" ] || fail "no sdkmanager at $sdkmanager"
[ -x "$avdmanager" ] || fail "no avdmanager at $avdmanager"

# An x86_64 image boots in useful time only with KVM. The workflow's previous
# step opens /dev/kvm to the runner's user.
[ -e /dev/kvm ] || fail "this runner has no /dev/kvm, so the emulator cannot be accelerated"
{ [ -r /dev/kvm ] && [ -w /dev/kvm ]; } || fail "/dev/kvm is not usable by $(id -un): $(ls -l /dev/kvm)"

df -h > "$SMYLTE_DIAG/disk-before.txt" 2>&1 || true

log "accepting the SDK licences"
# Not `yes | sdkmanager --licenses`: under pipefail, yes dies of SIGPIPE when
# sdkmanager stops reading, and the pipeline fails with 141.
"$sdkmanager" --licenses < <(yes) > "$SMYLTE_DIAG/sdkmanager-licenses.txt" 2>&1 \
  || fail "sdkmanager --licenses failed: $(tail -n 5 "$SMYLTE_DIAG/sdkmanager-licenses.txt")"

log "installing the emulator, platform-tools and $IMAGE"
installed=no
for attempt in 1 2 3; do
  if "$sdkmanager" --install emulator platform-tools "$IMAGE" --channel=0 \
      > "$SMYLTE_DIAG/sdkmanager-install-$attempt.txt" 2>&1; then
    installed=yes
    break
  fi
  log "sdkmanager --install failed (try $attempt of 3): $(tail -n 3 "$SMYLTE_DIAG/sdkmanager-install-$attempt.txt")"
  [ "$attempt" = 3 ] || sleep $((attempt * 15))   # back off before downloading again
done
[ "$installed" = yes ] || fail "sdkmanager could not install $IMAGE in 3 tries"
[ -x "$emulator" ] || fail "no emulator at $emulator after the install"
[ -d "$sdk/system-images/android-${API_LEVEL}/google_apis/x86_64" ] \
  || fail "no $IMAGE directory after the install"
"$sdkmanager" --list_installed > "$SMYLTE_DIAG/sdk-installed.txt" 2>&1 || true
"$emulator" -version > "$SMYLTE_DIAG/emulator-version.txt" 2>&1 || true
log "$(head -n 1 "$SMYLTE_DIAG/emulator-version.txt")"
df -h > "$SMYLTE_DIAG/disk-after-install.txt" 2>&1 || true

"$emulator" -accel-check > "$SMYLTE_DIAG/accel-check.txt" 2>&1 \
  || fail "the emulator cannot use KVM: $(cat "$SMYLTE_DIAG/accel-check.txt")"

log "creating the AVD"
export ANDROID_AVD_HOME="$HOME/.android/avd"
mkdir -p "$ANDROID_AVD_HOME"
# "no" answers avdmanager's question about a custom hardware profile.
"$avdmanager" create avd --force --name "$AVD" --package "$IMAGE" --device pixel_6 \
  <<< no > "$SMYLTE_DIAG/avdmanager.txt" 2>&1 \
  || fail "avdmanager could not create the AVD: $(tail -n 5 "$SMYLTE_DIAG/avdmanager.txt")"
config="$ANDROID_AVD_HOME/$AVD.avd/config.ini"
[ -f "$config" ] || fail "avdmanager wrote no $config"
set_config() {
  if grep -q "^$1[[:space:]]*=" "$config"; then
    sed -i "s|^$1[[:space:]]*=.*|$1=$2|" "$config"
  else
    printf '%s=%s\n' "$1" "$2" >> "$config"
  fi
}
# A hardware keyboard, so that no soft keyboard opens over Server settings
# (pushing its lock switch off the screen) or takes the first Back meant for
# the system's prompt. smoke.py also sets show_ime_with_hard_keyboard to 0.
set_config hw.keyboard yes
cp "$config" "$SMYLTE_DIAG/avd-config.ini"

log "starting the emulator (API $API_LEVEL, -gpu $GPU)"
export ANDROID_HOME="$sdk" ANDROID_SDK_ROOT="$sdk"
boot_started=$SECONDS
setsid nohup "$emulator" -avd "$AVD" -port 5554 -no-window -no-audio -no-boot-anim \
  -no-snapshot -no-metrics -gpu "$GPU" -camera-back none -camera-front none \
  -memory 2048 -cores 2 -accel on \
  > "$SMYLTE_DIAG/emulator.log" 2>&1 < /dev/null &
emulator_pid=$!
echo "$emulator_pid" > "$SMYLTE_DIAG/emulator.pid"

"$adb" start-server > "$SMYLTE_DIAG/adb-start-server.txt" 2>&1 || fail "adb could not start its server"
deadline=$((SECONDS + BOOT_TIMEOUT))
still_booting() {
  kill -0 "$emulator_pid" 2>/dev/null || fail "the emulator exited while booting ($1)"
  [ "$SECONDS" -lt "$deadline" ] || fail "the emulator did not boot within ${BOOT_TIMEOUT}s: $1"
  sleep 2
}

log "waiting for adb to see $SERIAL"
while :; do
  state=$(timeout 15 "$adb" -s "$SERIAL" get-state 2>/dev/null || true)
  [ "$state" = device ] && break
  still_booting "adb never saw $SERIAL as a device (last state: '${state}')"
done

# The whole run's logcat, from here to the workflow's stop step. smoke.py
# scans it for the app's crashes at the end.
setsid nohup "$adb" -s "$SERIAL" logcat -b all -v threadtime \
  > "$SMYLTE_DIAG/logcat-all.txt" 2>&1 < /dev/null &
echo $! > "$SMYLTE_DIAG/logcat.pid"

log "waiting for sys.boot_completed"
while :; do
  done_flag=$(timeout 15 "$adb" -s "$SERIAL" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r' || true)
  [ "$done_flag" = 1 ] && break
  still_booting "sys.boot_completed never became 1"
done

log "waiting for the package manager"
while :; do
  pm_path=$(timeout 15 "$adb" -s "$SERIAL" shell pm path android 2>/dev/null | tr -d '\r' || true)
  case "$pm_path" in package:*) break ;; esac
  still_booting "the package manager never answered"
done

running=$(timeout 15 "$adb" -s "$SERIAL" shell getprop ro.build.version.sdk | tr -d '\r') \
  || fail "could not read ro.build.version.sdk from the booted emulator"
[ "$running" = "$API_LEVEL" ] || fail "the emulator runs API '$running', not $API_LEVEL"
timeout 30 "$adb" -s "$SERIAL" shell getprop > "$SMYLTE_DIAG/getprop.txt" 2>&1 || true
df -h > "$SMYLTE_DIAG/disk-after-boot.txt" 2>&1 || true
log "booted API $running in $((SECONDS - boot_started))s"
