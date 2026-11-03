#!/usr/bin/env python3
"""Smoke checks for the Android client on an emulator (android-emulator.yml).

Drives the debug build with adb on the emulator boot.sh started, through
first launch, the app lock and the start-up failure screen. The checks run in
order and each builds on the state the last one left; the first failure stops
the run. At the end of every check, and once more in any case, the app's
crashes and ANRs are looked for. Every uiautomator dump, dumpsys output,
screenshot and logcat taken goes under --diag, which the workflow uploads when
a check fails, so a failure can be read from the artifacts alone.

    smoke.py --apk android/build/outputs/apk/debug/smylte-android-debug.apk \\
             --diag "$SMYLTE_DIAG" --api 35

Standard library only. The parsing is in smoke_lib.py, tested without an
emulator by test_smoke_lib.py.
"""
from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

import smoke_lib as lib  # noqa: E402

PACKAGE = "com.nicholaskmitchell.smylte"
# What the launcher sends (the README's start command, without -W and -S).
LAUNCH = (
    "am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER "
    f"-n {PACKAGE}/.MainActivity"
)
# The throwaway emulator's screen lock, set in check 3. Not a secret.
PIN = "1234"
# SystemUI's AuthContainerView titles its window this (android11 to android16).
PROMPT_WINDOW = "BiometricPrompt"
# .invalid never resolves (RFC 2606). Check 8 never reaches it anyway: start-up
# talks only to GitHub, which is cut off first.
ORIGIN = "https://smylte.invalid"
# Updater.startUp's StartupFailure when GitHub cannot be reached (Updater.kt).
NO_GITHUB = "Could not reach GitHub"
REMOTE_DUMP = "/data/local/tmp/smylte-ui.xml"
REMOTE_PREFS = "/data/local/tmp/smylte-prefs.xml"

REPO = Path(__file__).resolve().parents[2]
APP_LOCK_KT = REPO / "android/src/main/kotlin/com/nicholaskmitchell/smylte/AppLock.kt"
HOST_PROTOCOL_KT = REPO / "android/src/main/kotlin/com/nicholaskmitchell/smylte/HostProtocol.kt"
STRINGS_XML = REPO / "android/src/main/res/values/strings.xml"

POLL_S = 1.0             # between probes of a wait
UI_TIMEOUT_S = 30        # a screen to show after a launch or a tap
PROMPT_TIMEOUT_S = 30    # the system's prompt to open
GONE_TIMEOUT_S = 15      # something to go away
QUIET_S = 10             # how long "nothing opens by itself" is watched for
SHORT_AWAY_S = 30        # the trip away that must not lock
AWAY_MARGIN_S = 30       # added to AppLock.AWAY_MS for the trip that must
FAILURE_SCREEN_TIMEOUT_S = 90   # start-up's failure (GitHub's timeouts are 15 s + 30 s)

# The views that must never be in a dump while the window is locked.
SETUP_CONTENT = ("setup_content", "server", "username", "password", "token", "save", "lock_switch")
MAIN_CONTENT = ("main_content", "web", "splash", "splash_text", "retry", "open_settings", "strip")


class CheckFailed(Exception):
    pass


def say(message: str) -> None:
    print(f"[smoke {time.strftime('%H:%M:%S')}] {message}", flush=True)


def decode(data: bytes | None) -> str:
    return (data or b"").decode("utf-8", "replace").replace("\r\n", "\n")


def annotate(message: str) -> str:
    """A GitHub workflow command's value, one line however long."""
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


# ── the device ──────────────────────────────────────────────────────────────


class Device:
    def __init__(self, adb: str, serial: str, diag: Path):
        self.adb = adb
        self.serial = serial
        self.diag = diag
        self.seq = 0
        self.latest: dict[str, str] = {}
        self.commands = open(diag / "adb-commands.log", "a", encoding="utf-8")

    # Files under --diag, numbered in the order they were taken.
    def save(self, label: str, ext: str, data: str | bytes) -> Path:
        self.seq += 1
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip("-")[:80]
        path = self.diag / f"{self.seq:04d}-{safe}.{ext}"
        if isinstance(data, bytes):
            path.write_bytes(data)
        else:
            path.write_text(data, encoding="utf-8")
        return path

    def keep(self, label: str) -> None:
        """Saves the last output of each dumpsys a wait read, then forgets them."""
        for kind, text in self.latest.items():
            self.save(f"{label}-{kind}", "txt", text)
        self.latest.clear()

    def run(self, args: list[str], *, timeout: float = 60, check: bool = True,
            stdin: bytes | None = None) -> subprocess.CompletedProcess:
        cmd = [self.adb, "-s", self.serial, *args]
        started = time.monotonic()
        try:
            proc = subprocess.run(cmd, input=stdin, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            self.commands.write(f"{time.strftime('%H:%M:%S')} TIMEOUT after {timeout}s: {shlex.join(args)}\n")
            self.commands.flush()
            raise CheckFailed(f"adb {shlex.join(args)} did not finish within {timeout:.0f}s")
        self.commands.write(
            f"{time.strftime('%H:%M:%S')} exit {proc.returncode} in {time.monotonic() - started:.1f}s: {shlex.join(args)}\n"
        )
        self.commands.flush()
        if check and proc.returncode != 0:
            output = (decode(proc.stdout) + decode(proc.stderr)).strip()
            raise CheckFailed(f"adb {shlex.join(args)} failed (exit {proc.returncode}): {output[-800:]}")
        return proc

    def shell(self, command: str, *, timeout: float = 60, check: bool = True) -> str:
        """Runs one command line on the device (passed to adb as ONE argument,
        so redirections and quotes are the device shell's) and returns stdout."""
        return decode(self.run(["shell", command], timeout=timeout, check=check).stdout)

    def key(self, name: str) -> None:
        self.shell(f"input keyevent {name}")

    def tap(self, target: lib.Node, what: str) -> None:
        if target.bounds is None:
            raise CheckFailed(f"{what} has no bounds in the dump: {target.attrs}")
        x, y = lib.centre(target.bounds)
        say(f"tap {what} at {x},{y}")
        self.shell(f"input tap {x} {y}")

    # ── state ──

    def focus(self) -> str | None:
        out = self.shell("dumpsys window displays", timeout=30)
        self.latest["window-displays"] = out
        return lib.parse_current_focus(out)

    def app_window(self) -> lib.WindowBlock | None:
        out = self.shell("dumpsys window visible-apps", timeout=30)
        self.latest["window-visible-apps"] = out
        return lib.app_window(lib.parse_window_blocks(out), PACKAGE)

    def activities(self) -> str:
        out = self.shell("dumpsys activity activities", timeout=30)
        self.latest["activity-activities"] = out
        return out

    def uptime(self) -> float:
        return lib.parse_uptime(self.shell("cat /proc/uptime", timeout=15))

    def pid(self) -> str:
        return self.shell(f"pidof {PACKAGE}", timeout=15, check=False).strip()

    def ui(self, label: str, *, attempts: int = 5, all_windows: bool = False) -> list[lib.Node] | None:
        """A uiautomator dump of the active window (every window with
        all_windows), retried; saved whether it worked or not. Raises after
        `attempts` failures, or returns None when attempts is 1."""
        why = ""
        for attempt in range(1, attempts + 1):
            self.shell(f"rm -f {REMOTE_DUMP}", timeout=15, check=False)
            proc = self.run(
                ["shell", f"uiautomator dump{' --windows' if all_windows else ''} {REMOTE_DUMP}"],
                timeout=60, check=False,
            )
            output = decode(proc.stdout) + decode(proc.stderr)
            xml = decode(self.run(["exec-out", "cat", REMOTE_DUMP], timeout=30, check=False).stdout)
            ok, why = lib.dump_ok(output, xml)
            suffix = "windows" if all_windows else "ui"
            if ok:
                self.save(f"{label}-{suffix}", "xml", xml)
                return lib.parse_ui_dump(xml)
            self.save(f"{label}-{suffix}-failed", "txt", f"{output}\n--- file ---\n{xml}")
            say(f"uiautomator dump failed ({why}); try {attempt} of {attempts}")
            if attempt < attempts:
                time.sleep(1.0)   # back off before the next try
        if attempts == 1:
            return None
        raise CheckFailed(f"uiautomator could not dump the screen in {attempts} tries: {why}")

    def screenshot(self, label: str) -> None:
        # A secure window (Smylte while locked, the prompt) comes out black.
        proc = self.run(["exec-out", "screencap", "-p"], timeout=30, check=False)
        if proc.stdout.startswith(b"\x89PNG"):
            self.save(label, "png", proc.stdout)
        else:
            self.save(f"{label}-screencap-failed", "txt", decode(proc.stdout) + decode(proc.stderr))


# ── waiting ─────────────────────────────────────────────────────────────────

Probe = Callable[[], "tuple[bool, str]"]


def wait_for(dev: Device, what: str, probe: Probe, *, timeout: float, label: str,
             interval: float = POLL_S) -> str:
    """Polls `probe` until it says yes. A probe that cannot read the state
    (ValueError) counts as a no; a CheckFailed from it ends the wait at once."""
    deadline = time.monotonic() + timeout
    started = time.monotonic()
    probes = 0
    detail = "not checked yet"
    while True:
        probes += 1
        try:
            ok, detail = probe()
        except ValueError as e:
            ok, detail = False, f"could not read the state: {e}"
        if ok:
            dev.keep(label)
            say(f"ok: {what} ({detail}; {time.monotonic() - started:.1f}s, {probes} probe(s))")
            return detail
        if time.monotonic() >= deadline:
            dev.keep(f"{label}-timeout")
            raise CheckFailed(f"{what}: not so within {timeout:.0f}s. Last seen: {detail}")
        time.sleep(interval)


def stays(dev: Device, what: str, bad: Callable[[], "str | None"], *, seconds: float, label: str) -> None:
    """Watches for `seconds` (the check is about elapsed time) and fails as
    soon as `bad` names something wrong."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            problem = bad()
        except ValueError as e:
            say(f"could not read the state ({e}); still watching")
            problem = None
        if problem:
            dev.keep(f"{label}-failed")
            raise CheckFailed(f"{what}: {problem}")
        time.sleep(POLL_S)
    dev.keep(label)
    say(f"ok: {what} (watched {seconds:.0f}s)")


# ── steps the checks share ──────────────────────────────────────────────────


@dataclass
class Context:
    dev: Device
    api: int
    strings: dict[str, str]
    away_ms: int
    apk: Path
    # HostProtocol.MIN_WEBVIEW_MAJOR: below it the app shows its outdated
    # WebView screen instead of starting up (check 8).
    min_webview: int
    notes: list[str] = field(default_factory=list)
    # Check 1's last dump, scrolled to the bottom of Server settings, for check 2.
    bottom: list[lib.Node] = field(default_factory=list)


def view(nodes: list[lib.Node], name: str) -> lib.Node | None:
    return lib.node(nodes, PACKAGE, name)


def shows(nodes: list[lib.Node], name: str) -> bool:
    return lib.has_id(nodes, PACKAGE, name)


def assert_hidden(nodes: list[lib.Node], content: tuple[str, ...], when: str) -> None:
    """While locked, none of the window's content may be in the accessibility tree."""
    leaked = [name for name in content if shows(nodes, name)]
    if leaked:
        raise CheckFailed(
            f"{when}: {', '.join(leaked)} in the accessibility tree while the app should be locked "
            "(either it did not lock, or LockScreen did not hide the content INVISIBLE and NO_HIDE_DESCENDANTS)"
        )


def launch(dev: Device) -> None:
    proc = dev.run(["shell", LAUNCH], timeout=30, check=False)
    out = (decode(proc.stdout) + decode(proc.stderr)).strip()   # am prints its errors on stderr
    say(out.replace("\n", " | "))
    if proc.returncode != 0 or "Error" in out:
        raise CheckFailed(f"am start failed (exit {proc.returncode}): {out}")


def force_stop(dev: Device, label: str) -> None:
    dev.shell(f"am force-stop {PACKAGE}")

    def gone() -> tuple[bool, str]:
        pid = dev.pid()
        return not pid, f"pidof: {pid or 'nothing'}"

    wait_for(dev, "the app's process has gone", gone, timeout=GONE_TIMEOUT_S, label=label)


def not_in_front(dev: Device) -> tuple[bool, str]:
    resumed = lib.parse_resumed_activity(dev.activities())
    if resumed is None:
        return False, "no resumed activity yet"
    return not resumed.startswith(PACKAGE + "/"), f"resumed: {resumed}"


def go_home(dev: Device, label: str) -> None:
    dev.key("KEYCODE_HOME")
    wait_for(dev, "Smylte has gone to the background", lambda: not_in_front(dev),
             timeout=GONE_TIMEOUT_S, label=label)


def prompt_up(dev: Device, label: str, *, dump: bool) -> tuple[bool, str]:
    """Whether the system's prompt is showing: its window has focus or, with
    `dump`, the active window's dump shows its PIN field."""
    title = dev.focus()
    if title == PROMPT_WINDOW:
        return True, "focus: BiometricPrompt"
    if dump:
        nodes = dev.ui(label, attempts=1)
        if nodes is not None and lib.prompt_shown(nodes):
            return True, f"the dump shows the prompt's PIN field (focus: {title})"
    return False, f"focus: {title}"


def wait_prompt(ctx: Context, what: str, label: str, content: tuple[str, ...]) -> None:
    """Waits for the prompt. Every dump of Smylte's window taken meanwhile must
    show none of `content`: nothing of the app shows before the prompt."""
    dev = ctx.dev

    def probe() -> tuple[bool, str]:
        title = dev.focus()
        if title == PROMPT_WINDOW:
            return True, "focus: BiometricPrompt"
        nodes = dev.ui(label, attempts=1)
        if nodes is None:
            return False, f"focus: {title}; the dump failed"
        if lib.prompt_shown(nodes):
            return True, f"the dump shows the prompt's PIN field (focus: {title})"
        mine = lib.app_nodes(nodes, PACKAGE)
        if mine:
            assert_hidden(mine, content, f"before the prompt opened ({what})")
        return False, f"focus: {title}; {'lock view' if lib.lock_shown(mine, PACKAGE) else 'no lock view'} in the dump"

    wait_for(dev, what, probe, timeout=PROMPT_TIMEOUT_S, label=label)


def prompt_gone(dev: Device, label: str) -> tuple[bool, str]:
    up, detail = prompt_up(dev, label, dump=True)
    return not up, detail


def cancel_prompt(dev: Device, label: str) -> None:
    """Back cancels the prompt. Pressed again only if the prompt is still up 5
    s later (a soft keyboard can take the first Back), never more than 3 times,
    so no Back reaches the app. Before pressing again it looks once more, in
    case the prompt closed just as the wait ended."""
    for press in range(1, 4):
        if press > 1:
            up, detail = prompt_up(dev, f"{label}-recheck{press}", dump=True)
            if not up:
                say(f"the prompt closed late after Back #{press - 1} ({detail})")
                return
        dev.key("KEYCODE_BACK")
        try:
            wait_for(dev, f"the prompt closes after Back #{press}", lambda: prompt_gone(dev, label),
                     timeout=5, label=f"{label}-back{press}")
            return
        except CheckFailed as e:
            say(f"{e}")
    raise CheckFailed("Back did not close the system's prompt in 3 presses")


def pin_field_ready(dev: Device, label: str) -> tuple[bool, str]:
    nodes = dev.ui(label, attempts=1)
    if nodes is None:
        return False, "the dump failed"
    field_node = lib.pin_field(nodes)
    if field_node is None:
        return False, "no lockPassword field in the dump"
    return field_node.flag("focused"), f"lockPassword focused={field_node.attrs.get('focused')}"


def enter_pin(dev: Device, label: str) -> None:
    """Types the PIN into the prompt and confirms it. Typing waits for the PIN
    field to have focus (keys typed before it has are lost); if the dump never
    shows the field, the PIN is typed anyway, since the prompt's window has
    focus. One retry, after clearing the field, if the prompt stays up."""
    try:
        wait_for(dev, "the prompt's PIN field has focus", lambda: pin_field_ready(dev, label),
                 timeout=10, label=f"{label}-field")
    except CheckFailed as e:
        say(f"warning: {e}; typing the PIN anyway")
    for attempt in (1, 2):
        dev.shell(f"input text {PIN}")
        dev.key("KEYCODE_ENTER")
        try:
            wait_for(dev, "the prompt closes after the PIN", lambda: prompt_gone(dev, label),
                     timeout=GONE_TIMEOUT_S, label=f"{label}-pin{attempt}")
            return
        except CheckFailed:
            dev.screenshot(f"{label}-prompt-after-pin{attempt}")
            if attempt == 2:
                raise CheckFailed(
                    "the prompt stayed up after the PIN was entered twice; "
                    "the last dumps show its error text"
                )
            say("the prompt is still up after the PIN; clearing the field and typing it once more")
            dev.shell("input keyevent KEYCODE_MOVE_END " + " ".join(["KEYCODE_DEL"] * 8))


def wait_lock_view(ctx: Context, label: str, content: tuple[str, ...]) -> list[lib.Node]:
    dev = ctx.dev
    seen: list[list[lib.Node]] = []

    def probe() -> tuple[bool, str]:
        nodes = dev.ui(label, attempts=1)
        if nodes is None:
            return False, "the dump failed"
        mine = lib.app_nodes(nodes, PACKAGE)
        if mine:
            assert_hidden(mine, content, "on the lock view")
        if lib.lock_shown(mine, PACKAGE):
            seen.append(nodes)
            return True, "lock_title and lock_unlock in the dump"
        return False, f"no lock view; packages in the dump: {sorted({n.package for n in nodes})}"

    wait_for(dev, "Smylte's lock view shows", probe, timeout=GONE_TIMEOUT_S, label=label)
    nodes = seen[-1]
    title = view(nodes, "lock_title")
    if title.text.casefold() != ctx.strings["lock_title"].casefold():
        raise CheckFailed(f"the lock view's title is {title.text!r}, not {ctx.strings['lock_title']!r}")
    unlock = view(nodes, "lock_unlock")
    if unlock.text.casefold() != ctx.strings["lock_unlock"].casefold():
        raise CheckFailed(f"the lock view's button is {unlock.text!r}, not {ctx.strings['lock_unlock']!r}")
    return nodes


def wait_secure(ctx: Context, want: bool, activity: str, why: str, label: str) -> None:
    dev = ctx.dev

    def probe() -> tuple[bool, str]:
        window = dev.app_window()
        if window is None:
            return False, "no visible Smylte window in dumpsys window visible-apps"
        if not window.title.endswith("." + activity):
            return False, f"the visible Smylte window is {window.title}"
        if window.secure is None:
            return False, f"{window.title} has no fl= line"
        return window.secure == want, f"{window.title} fl={window.flags}"

    state = "has" if want else "does not have"
    wait_for(dev, f"{activity}'s window {state} FLAG_SECURE ({why})", probe, timeout=10, label=label)


def wait_setup(ctx: Context, label: str) -> list[lib.Node]:
    """Server settings, unlocked: its content is in the dump and no lock view."""
    dev = ctx.dev
    seen: list[list[lib.Node]] = []

    def probe() -> tuple[bool, str]:
        nodes = dev.ui(label, attempts=1)
        if nodes is None:
            return False, "the dump failed"
        mine = lib.app_nodes(nodes, PACKAGE)
        if shows(mine, "setup_content") and not lib.lock_shown(mine, PACKAGE):
            seen.append(nodes)
            return True, "setup_content in the dump, no lock view"
        what = "the lock view" if lib.lock_shown(mine, PACKAGE) else "no setup_content"
        return False, f"{what}; packages in the dump: {sorted({n.package for n in nodes})}"

    wait_for(dev, "Server settings shows, unlocked", probe, timeout=UI_TIMEOUT_S, label=label)
    return seen[-1]


def scroll_to_bottom(ctx: Context, nodes: list[lib.Node], label: str) -> tuple[list[lib.Node], set[str]]:
    """Swipes Server settings up until its last line (version) is on screen;
    returns that dump and every view id seen on the way."""
    dev = ctx.dev
    seen: set[str] = set()
    for swipe in range(9):
        seen |= {n.rid for n in lib.app_nodes(nodes, PACKAGE) if n.rid}
        if shows(nodes, "version"):
            return nodes, seen
        if swipe == 8:
            break
        scroller = view(nodes, "setup_content")
        if scroller is None or scroller.bounds is None:
            raise CheckFailed("Server settings is not showing (no setup_content in the dump) while scrolling")
        x1, y1, x2, y2 = scroller.bounds
        x, height = (x1 + x2) // 2, y2 - y1
        dev.shell(f"input swipe {x} {y1 + height * 3 // 4} {x} {y1 + height // 4} 400")
        nodes = dev.ui(f"{label}-scroll{swipe + 1}")
    raise CheckFailed("Server settings scrolled 8 times without reaching its last line (version)")


def note_for(ctx: Context) -> str:
    # SetupActivity: the _secure note where FLAG_SECURE is the Recents guard (below 13).
    return ctx.strings["lock_setting_note_secure" if ctx.api < 33 else "lock_setting_note"]


def keyguard_gone(dev: Device) -> tuple[bool, str]:
    showing = lib.keyguard_showing(dev.activities())
    if showing is None:
        raise ValueError("no mKeyguardShowing in dumpsys activity activities")
    return not showing, f"mKeyguardShowing={str(showing).lower()}"


def ensure_no_keyguard(dev: Device, label: str, pin: str | None) -> None:
    """The screen on and no keyguard over the app. svc's stay-on keeps the
    screen from turning off, so the keyguard should never come back; if it did,
    it goes, with the PIN on the bouncer when there is one."""
    dev.key("KEYCODE_WAKEUP")
    try:
        ok, detail = keyguard_gone(dev)
    except ValueError as e:
        # The format moved: say so, and let the next wait show what is on screen.
        say(f"warning: {e}; cannot tell whether the keyguard is showing")
        return
    if ok:
        return
    say(f"the keyguard is showing ({detail}); dismissing it")
    dev.screenshot(f"{label}-keyguard")
    dev.shell("wm dismiss-keyguard")
    try:
        wait_for(dev, "the keyguard goes", lambda: keyguard_gone(dev), timeout=10, label=f"{label}-keyguard")
        return
    except CheckFailed:
        if pin is None:
            # An insecure keyguard: the menu key dismisses it on the emulator.
            dev.key("KEYCODE_MENU")
            wait_for(dev, "the keyguard goes after the menu key", lambda: keyguard_gone(dev), timeout=10,
                     label=f"{label}-keyguard-menu")
            return
    say("typing the PIN on the keyguard's bouncer")
    dev.shell(f"input text {pin}")
    dev.key("KEYCODE_ENTER")
    wait_for(dev, "the keyguard goes after the PIN", lambda: keyguard_gone(dev), timeout=15,
             label=f"{label}-keyguard-pin")


def dismiss_error_dialog(dev: Device) -> None:
    """A system app's "isn't responding" dialog left from the boot would take
    focus from everything. hide_error_dialogs stops new ones; this closes one
    that is already up (BaseErrorDialog closes on CLOSE_SYSTEM_DIALOGS)."""
    try:
        title = dev.focus()
    except ValueError:
        return
    if title and title.startswith(("Application Not Responding", "Application Error")):
        say(f"closing a system error dialog: {title}")
        dev.shell("am broadcast -a android.intent.action.CLOSE_SYSTEM_DIALOGS", check=False)


def away(ctx: Context, seconds: float, label: str) -> float:
    """Leaves Smylte with Home and waits until `seconds` have passed on the
    device's clock that counts sleep (/proc/uptime, as elapsedRealtime), from
    the moment Smylte was seen gone. Returns the seconds measured."""
    dev = ctx.dev
    go_home(dev, f"{label}-home")
    left = dev.uptime()
    host_deadline = time.monotonic() + seconds + 300
    last_report = time.monotonic()
    while True:
        elapsed = dev.uptime() - left
        if elapsed >= seconds:
            say(f"away {elapsed:.0f}s on the device's clock")
            return elapsed
        if time.monotonic() > host_deadline:
            raise CheckFailed(f"the device's clock showed only {elapsed:.0f}s of {seconds:.0f}s away after "
                              f"{seconds + 300:.0f}s on the runner's")
        if time.monotonic() - last_report >= 60:
            say(f"away {elapsed:.0f}s of {seconds:.0f}s")
            last_report = time.monotonic()
        time.sleep(min(2.0, max(0.2, seconds - elapsed)))   # the check is about elapsed time


def crash_scan(ctx: Context, label: str, *, full: bool) -> list[str]:
    """The app's crashes and ANRs, from the crash buffer, the main, system and
    events buffers, exit-info and, with `full`, the whole run's logcat capture."""
    dev = ctx.dev
    crash = dev.shell("logcat -b crash -d -v threadtime", timeout=60, check=False)
    logs = dev.shell("logcat -b main -b system -b events -d -v threadtime", timeout=120, check=False)
    exits = dev.shell(f"dumpsys activity exit-info {PACKAGE}", timeout=30, check=False)
    dev.save(f"{label}-logcat-crash", "txt", crash)
    dev.save(f"{label}-exit-info", "txt", exits)
    if full:
        dev.save(f"{label}-logcat-main-system-events", "txt", logs)
    problems = (
        lib.find_crashes(crash, PACKAGE) + lib.find_crashes(logs, PACKAGE)
        + lib.find_anrs(logs, PACKAGE) + lib.exit_info_failures(exits)
    )
    capture = dev.diag / "logcat-all.txt"
    if full and capture.is_file():
        text = capture.read_text(encoding="utf-8", errors="replace")
        problems += lib.find_crashes(text, PACKAGE) + lib.find_anrs(text, PACKAGE)
    return lib.unique(problems)


def assert_no_crash(ctx: Context, label: str) -> None:
    problems = crash_scan(ctx, label, full=False)
    if problems:
        raise CheckFailed("Smylte crashed or stopped responding: " + " | ".join(problems[:6]))
    say("no crash or ANR of the app so far")


# ── the checks ──────────────────────────────────────────────────────────────


def prepare(ctx: Context) -> None:
    """The emulator made predictable: no animations, the screen kept on, no
    soft keyboard, no error dialogs, no keyguard, and the home screen."""
    dev = ctx.dev
    sdk = int(dev.shell("getprop ro.build.version.sdk").strip())
    if sdk != ctx.api:
        raise CheckFailed(f"the emulator runs API {sdk}, not {ctx.api}")
    for setting in ("window_animation_scale", "transition_animation_scale", "animator_duration_scale"):
        dev.shell(f"settings put global {setting} 0")
    dev.shell("settings put global hide_error_dialogs 1", check=False)
    dev.shell("settings put secure show_ime_with_hard_keyboard 0")
    dev.shell("settings put system screen_off_timeout 1800000")
    battery = dev.shell("dumpsys battery", timeout=30)
    dev.save("prepare-battery", "txt", battery)
    if not lib.powered(battery):
        say("the emulator reports no charger; setting AC power")
        dev.shell("dumpsys battery set ac 1")
    # 7 = AC | USB | wireless: what `svc power stayon true` writes.
    dev.shell("settings put global stay_on_while_plugged_in 7")
    stay = dev.shell("settings get global stay_on_while_plugged_in").strip()
    if stay != "7":
        raise CheckFailed(f"stay_on_while_plugged_in is {stay!r} after setting it to 7")
    # No keyguard at all while there is no PIN: Swipe becomes None.
    say("locksettings set-disabled: " + dev.shell("locksettings set-disabled true", check=False).strip())
    ensure_no_keyguard(dev, "prepare", pin=None)
    dismiss_error_dialog(dev)
    dev.key("KEYCODE_HOME")
    dev.screenshot("prepare-home")


def check_install_and_launch(ctx: Context) -> None:
    """1. Installs, launches with the launcher's intent, and lands on Server
    settings (no server is configured) with every setup field in the dumps."""
    dev = ctx.dev
    for attempt in (1, 2, 3):
        proc = dev.run(["install", "-r", str(ctx.apk)], timeout=180, check=False)
        out = decode(proc.stdout) + decode(proc.stderr)
        if proc.returncode == 0 and "Success" in out:
            break
        say(f"adb install: {out.strip()} (try {attempt} of 3)")
        if attempt == 3:
            raise CheckFailed(f"adb install failed 3 times: {out.strip()}")
        time.sleep(5.0)   # back off before installing again
    path = dev.shell(f"pm path {PACKAGE}").strip()
    if not path.startswith("package:"):
        raise CheckFailed(f"pm path {PACKAGE} after the install: {path!r}")
    dev.shell("logcat -b all -c", check=False)   # from here on, any crash is this run's
    launch(dev)
    nodes = wait_setup(ctx, "c1-launch")
    title = lib.find(lib.app_nodes(nodes, PACKAGE), text=ctx.strings["setup_title"])
    if not title:
        raise CheckFailed(f"Server settings shows no {ctx.strings['setup_title']!r} title")
    server = view(nodes, "server")
    if server is None or server.cls != "android.widget.EditText":
        raise CheckFailed("Server settings shows no server field (an EditText) at the top")
    nodes, seen = scroll_to_bottom(ctx, nodes, "c1-fields")
    missing = [name for name in ("server", "username", "password", "token", "save", "version")
               if lib.view_id(PACKAGE, name) not in seen]
    if missing:
        raise CheckFailed(f"scrolling Server settings never showed {', '.join(missing)}")
    ctx.bottom = nodes
    dev.screenshot("c1-setup-bottom")
    assert_no_crash(ctx, "c1")


def check_no_screen_lock(ctx: Context) -> None:
    """2. With no screen lock, Server settings offers no switch, only the note
    that a screen lock is needed."""
    nodes = ctx.bottom
    heading = lib.find(lib.app_nodes(nodes, PACKAGE), text=ctx.strings["lock_setting_heading"])
    if not heading:
        raise CheckFailed(f"the {ctx.strings['lock_setting_heading']!r} heading is not on screen at the bottom")
    note = view(nodes, "lock_unavailable")
    if note is None:
        raise CheckFailed("no lock_unavailable note on a phone with no screen lock")
    if note.text.casefold() != ctx.strings["lock_setting_unavailable"].casefold():
        raise CheckFailed(f"lock_unavailable says {note.text!r}")
    for name in ("lock_switch", "lock_note"):
        if shows(nodes, name):
            raise CheckFailed(f"{name} shows on a phone with no screen lock")
    assert_no_crash(ctx, "c2")


def check_switch_with_pin(ctx: Context) -> None:
    """3. With a PIN set, the switch shows, off; turning it on locks nothing at
    once; on Android 11 and 12 the window turns secure at once (Recents)."""
    dev = ctx.dev
    out = dev.shell(f"locksettings set-pin {PIN}").strip()
    say(out)
    if f"Pin set to '{PIN}'" not in out:
        raise CheckFailed(f"locksettings set-pin did not set the PIN: {out!r}")
    ensure_no_keyguard(dev, "c3", pin=PIN)
    go_home(dev, "c3-home")
    launch(dev)   # back to Server settings, whose onResume reads the screen lock again
    nodes = wait_setup(ctx, "c3-return")
    nodes, _ = scroll_to_bottom(ctx, nodes, "c3-bottom")
    switch = view(nodes, "lock_switch")
    if switch is None:
        raise CheckFailed("no lock switch in Server settings after a PIN was set")
    if switch.flag("checked"):
        raise CheckFailed("the lock switch is already on before it was turned on")
    if shows(nodes, "lock_unavailable"):
        raise CheckFailed("the screen-lock-needed note still shows with a PIN set")
    note = view(nodes, "lock_note")
    if note is None or note.text.casefold() != note_for(ctx).casefold():
        raise CheckFailed(f"the lock note is {note.text if note else None!r}, not {note_for(ctx)!r}")
    dev.tap(switch, "the lock switch")

    def switched() -> tuple[bool, str]:
        now = dev.ui("c3-switched", attempts=1)
        if now is None:
            return False, "the dump failed"
        s = view(now, "lock_switch")
        return bool(s and s.flag("checked")), f"lock_switch checked={s.attrs.get('checked') if s else 'absent'}"

    wait_for(dev, "the lock switch is on", switched, timeout=10, label="c3-switch")

    def saved() -> tuple[bool, str]:
        text = dev.shell(f"run-as {PACKAGE} cat shared_prefs/smylte.xml", check=False)
        dev.latest["prefs"] = text
        try:
            prefs = lib.parse_prefs(text)
        except (ValueError, SyntaxError) as e:   # not written yet, or run-as refused (ParseError is a SyntaxError)
            return False, f"no readable prefs file: {text.strip()[:200]!r} ({e})"
        return prefs.get("app_lock") is True, f"app_lock={prefs.get('app_lock')}"

    wait_for(dev, "app_lock is saved on", saved, timeout=10, label="c3-prefs")
    stays(dev, "turning the lock on locks nothing at once",
          lambda: "the prompt opened" if dev.focus() == PROMPT_WINDOW else None,
          seconds=5, label="c3-quiet")
    nodes = dev.ui("c3-after")
    if lib.lock_shown(nodes, PACKAGE) or not shows(nodes, "lock_switch"):
        raise CheckFailed("Server settings locked when the switch was turned on")
    wait_secure(ctx, ctx.api < 33, "SetupActivity",
                "Android 11 and 12 guard Recents with FLAG_SECURE while the lock is on; 13 and later do not need it",
                "c3-secure")
    dev.screenshot("c3-switch-on")
    assert_no_crash(ctx, "c3")


def check_cold_start_locks(ctx: Context) -> None:
    """4. A cold start locks: the prompt opens by itself, Server settings' window
    is secure, and its fields are never in the accessibility tree."""
    dev = ctx.dev
    force_stop(dev, "c4-stop")
    launch(dev)
    wait_prompt(ctx, "the prompt opens by itself on a cold start", "c4-prompt", SETUP_CONTENT)
    wait_secure(ctx, True, "SetupActivity", "locked", "c4-secure")
    nodes = dev.ui("c4-all", attempts=1, all_windows=True)
    mine = lib.app_nodes(nodes or [], PACKAGE)
    if mine:
        assert_hidden(mine, SETUP_CONTENT, "under the prompt (all windows)")
        if not lib.lock_shown(mine, PACKAGE):
            raise CheckFailed("under the prompt, Smylte's window shows no lock view (all-windows dump)")
        say("under the prompt: Smylte's window shows the lock view and none of the settings")
    else:
        ctx.notes.append("check 4: the all-windows dump had no Smylte nodes; the lock view was checked after the cancel")
        say("the all-windows dump has none of Smylte's nodes; the lock view is checked after Back (check 5)")
    dev.screenshot("c4-prompt")
    assert_no_crash(ctx, "c4")


def check_back_while_locked(ctx: Context) -> None:
    """5. Back cancels the prompt and leaves the lock view, and no prompt comes
    back by itself; Back again moves Smylte to the background unfinished."""
    dev = ctx.dev
    cancel_prompt(dev, "c5-cancel")
    wait_lock_view(ctx, "c5-lock", SETUP_CONTENT)
    stays(dev, "no prompt opens by itself after a cancel",
          lambda: "the prompt opened again by itself" if dev.focus() == PROMPT_WINDOW else None,
          seconds=QUIET_S, label="c5-quiet")
    nodes = dev.ui("c5-still-locked")
    assert_hidden(lib.app_nodes(nodes, PACKAGE), SETUP_CONTENT, "after the cancel")
    if not lib.lock_shown(nodes, PACKAGE):
        raise CheckFailed("the lock view went after the cancel")
    dev.key("KEYCODE_BACK")
    wait_for(dev, "Back on the lock view moves Smylte to the background", lambda: not_in_front(dev),
             timeout=GONE_TIMEOUT_S, label="c5-back")
    records = [r for r in lib.history_records(dev.activities()) if r.component.startswith(PACKAGE + "/")]
    dev.keep("c5-task")
    if not any(r.component == f"{PACKAGE}/.SetupActivity" and not r.finishing for r in records):
        raise CheckFailed(f"Back finished Server settings instead of moving it to the back: {records}")
    if not dev.pid():
        raise CheckFailed("Smylte's process is gone after Back on the lock view")
    dev.screenshot("c5-background")
    assert_no_crash(ctx, "c5")


def check_unlock_with_pin(ctx: Context) -> None:
    """6. Back in Smylte it is still locked; Unlock opens the prompt and the PIN
    unlocks: the fields are back, and FLAG_SECURE goes on Android 13 and later."""
    dev = ctx.dev
    launch(dev)
    wait_prompt(ctx, "the prompt opens by itself on the return", "c6-prompt", SETUP_CONTENT)
    cancel_prompt(dev, "c6-cancel")
    nodes = wait_lock_view(ctx, "c6-lock", SETUP_CONTENT)
    dev.tap(view(nodes, "lock_unlock"), "Unlock")
    wait_for(dev, "Unlock opens the prompt", lambda: prompt_up(dev, "c6-unlock", dump=True),
             timeout=GONE_TIMEOUT_S, label="c6-unlock")
    enter_pin(dev, "c6-pin")
    nodes = wait_setup(ctx, "c6-unlocked")
    if not shows(nodes, "server"):
        raise CheckFailed("unlocked, but the server field is not in the dump")
    wait_secure(ctx, ctx.api < 33, "SetupActivity",
                "unlocked: FLAG_SECURE stays only where it guards Recents, Android 11 and 12",
                "c6-secure")
    dev.screenshot("c6-unlocked")
    assert_no_crash(ctx, "c6")


def check_away(ctx: Context) -> None:
    """7. Under AWAY_MS away the app comes back unlocked; AWAY_MS or more and it
    comes back locked, with the prompt open by itself."""
    dev = ctx.dev
    limit_s = ctx.away_ms / 1000
    measured = away(ctx, SHORT_AWAY_S, "c7-short")
    if measured >= limit_s - 60:
        raise CheckFailed(f"the short trip took {measured:.0f}s, too close to {limit_s:.0f}s to show anything")
    ensure_no_keyguard(dev, "c7-short", pin=PIN)
    launch(dev)
    wait_setup(ctx, "c7-short-return")
    stays(dev, f"no prompt after {SHORT_AWAY_S}s away",
          lambda: "the prompt opened" if dev.focus() == PROMPT_WINDOW else None,
          seconds=QUIET_S, label="c7-short-quiet")
    nodes = dev.ui("c7-short-after")
    if lib.lock_shown(nodes, PACKAGE) or not shows(nodes, "setup_content"):
        raise CheckFailed(f"Smylte locked after {measured:.0f}s away (under {limit_s:.0f}s)")
    assert_no_crash(ctx, "c7-short")

    measured = away(ctx, limit_s + AWAY_MARGIN_S, "c7-long")
    ensure_no_keyguard(dev, "c7-long", pin=PIN)
    launch(dev)
    wait_prompt(ctx, f"the prompt opens by itself after {measured:.0f}s away", "c7-long-prompt", SETUP_CONTENT)
    wait_secure(ctx, True, "SetupActivity", "locked again", "c7-long-secure")
    dev.screenshot("c7-long-prompt")
    enter_pin(dev, "c7-long-pin")
    wait_setup(ctx, "c7-long-unlocked")
    assert_no_crash(ctx, "c7-long")


def check_locked_start_failure_screen(ctx: Context) -> None:
    """8. With a server configured and GitHub cut off, the main window starts
    locked (secure, prompt by itself, nothing of the window in the tree), and
    the unlock shows start-up's failure screen with Try again and Settings: the
    no-GitHub message, or, on a WebView older than MIN_WEBVIEW_MAJOR (Android
    11's image has 83), the outdated WebView message, which start-up checks
    before it reaches for the network."""
    dev = ctx.dev
    force_stop(dev, "c8-stop")
    prefs = lib.prefs_xml({"origin": ORIGIN}, {"app_lock": True})
    local = dev.save("c8-prefs-written", "xml", prefs)
    dev.run(["push", str(local), REMOTE_PREFS], timeout=30)
    dev.shell(f"chmod 644 {REMOTE_PREFS}")   # the app's uid reads it, through run-as
    # One argument to adb shell, so the redirections and the cd are run-as's,
    # in the app's own data directory and as the app.
    dev.shell(
        f"run-as {PACKAGE} sh -c 'mkdir -p shared_prefs && rm -f shared_prefs/smylte.xml.bak "
        f"&& cp {REMOTE_PREFS} shared_prefs/smylte.xml'"
    )
    back = dev.shell(f"run-as {PACKAGE} cat shared_prefs/smylte.xml")
    dev.save("c8-prefs-read-back", "xml", back)
    try:
        read = lib.parse_prefs(back)
    except (ValueError, SyntaxError) as e:
        raise CheckFailed(f"the prefs file written with run-as does not read back: {back!r} ({e})")
    if read != {"origin": ORIGIN, "app_lock": True}:
        raise CheckFailed(f"the prefs file reads back as {read}, not origin {ORIGIN} with app_lock on")

    # Which failure the screen must show: the app reads its engine's version
    # from the user agent, this from the WebView package, whose versionName is
    # the Chromium version for the AOSP and Google WebViews an emulator has.
    webview_dump = dev.shell("dumpsys webviewupdate", timeout=30, check=False)
    dev.save("c8-webviewupdate", "txt", webview_dump)
    webview = lib.current_webview(webview_dump)
    if webview is None:
        raise CheckFailed("dumpsys webviewupdate names no WebView in use")
    webview_major = lib.version_major(webview[1])
    outdated = webview_major is not None and webview_major < ctx.min_webview
    say(f"WebView {webview[0]} {webview[1]}: "
        f"{'older than' if outdated else 'at least'} MIN_WEBVIEW_MAJOR {ctx.min_webview}")

    # Start-up then fetches the release from GitHub before anything else. Cut
    # off, it fails at once and the failure screen is certain; reachable, it
    # would download the web build and open the page instead.
    dev.shell("cmd connectivity airplane-mode enable")
    dev.shell("settings put global http_proxy 127.0.0.1:9")

    def offline() -> tuple[bool, str]:
        mode = dev.shell("cmd connectivity airplane-mode", check=False).strip()
        text = dev.shell("dumpsys connectivity", timeout=30, check=False)
        dev.latest["connectivity"] = text
        none = lib.default_network_none(text)
        return mode == "enabled" and none is True, f"airplane-mode {mode}; no default network: {none}"

    wait_for(dev, "the emulator is offline", offline, timeout=30, label="c8-offline")
    launch(dev)
    wait_prompt(ctx, "the prompt opens by itself on a locked start of the main window", "c8-prompt", MAIN_CONTENT)
    wait_secure(ctx, True, "MainActivity", "locked", "c8-secure")
    cancel_prompt(dev, "c8-cancel")
    nodes = wait_lock_view(ctx, "c8-lock", MAIN_CONTENT)
    dev.tap(view(nodes, "lock_unlock"), "Unlock")
    wait_for(dev, "Unlock opens the prompt", lambda: prompt_up(dev, "c8-unlock", dump=True),
             timeout=GONE_TIMEOUT_S, label="c8-unlock")
    enter_pin(dev, "c8-pin")
    seen: list[list[lib.Node]] = []

    def failure_screen() -> tuple[bool, str]:
        now = dev.ui("c8-failure", attempts=1)
        if now is None:
            return False, "the dump failed"
        if all(shows(now, n) for n in ("splash_text", "retry", "open_settings")) and not lib.lock_shown(now, PACKAGE):
            seen.append(now)
            return True, "splash_text, retry and open_settings in the dump"
        text = view(now, "splash_text")
        return False, f"splash_text: {text.text if text else None!r}; web: {shows(now, 'web')}"

    wait_for(dev, "the start-up failure screen shows", failure_screen,
             timeout=FAILURE_SCREEN_TIMEOUT_S, interval=2.0, label="c8-failure")
    nodes = seen[-1]
    for name, key in (("retry", "try_again"), ("open_settings", "settings")):
        button = view(nodes, name)
        if button.text.casefold() != ctx.strings[key].casefold():
            raise CheckFailed(f"the {name} button says {button.text!r}, not {ctx.strings[key]!r}")
    message = view(nodes, "splash_text").text
    if outdated:
        expected = lib.format_regex(ctx.strings["webview_outdated"],
                                    {2: rf"{webview_major}(?:\.\d+)*", 3: str(ctx.min_webview)})
        if not expected.fullmatch(message):
            raise CheckFailed(f"start-up failed with {message!r}, not the outdated WebView message "
                              f"for Chromium {webview_major} ({ctx.strings['webview_outdated']!r})")
    elif not message.startswith(NO_GITHUB):
        raise CheckFailed(f"start-up failed with {message!r}, not the no-GitHub message ({NO_GITHUB!r}...)")
    say(f"failure screen: {message}")
    dev.screenshot("c8-failure")
    assert_no_crash(ctx, "c8")


CHECKS: list[tuple[str, Callable[[Context], None]]] = [
    ("prepare the emulator", prepare),
    ("1 install and launch", check_install_and_launch),
    ("2 no screen lock: no switch", check_no_screen_lock),
    ("3 PIN set: the switch, on", check_switch_with_pin),
    ("4 cold start locks", check_cold_start_locks),
    ("5 Back while locked", check_back_while_locked),
    ("6 unlock with the PIN", check_unlock_with_pin),
    ("7 away under and over AWAY_MS", check_away),
    ("8 locked start, failure screen", check_locked_start_failure_screen),
]


# ── running them ────────────────────────────────────────────────────────────


def find_adb(given: str | None) -> str:
    candidates = [given, os.environ.get("ADB")]
    for home in (os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT")):
        if home:
            candidates.append(str(Path(home) / "platform-tools" / "adb"))
    candidates.append(shutil.which("adb"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise SystemExit("smoke.py: no adb (give --adb, or set ADB or ANDROID_HOME)")


def final_diagnostics(ctx: Context) -> None:
    """What the screen and the system looked like when a check failed."""
    dev = ctx.dev
    steps: list[tuple[str, Callable[[], None]]] = [
        ("screenshot", lambda: dev.screenshot("failure-screen")),
        ("ui", lambda: dev.ui("failure", attempts=1)),
        ("ui --windows", lambda: dev.ui("failure", attempts=1, all_windows=True)),
    ]
    for command in ("dumpsys window windows", "dumpsys window displays", "dumpsys activity activities",
                    f"dumpsys activity exit-info {PACKAGE}", "dumpsys input_method", "dumpsys connectivity",
                    f"run-as {PACKAGE} cat shared_prefs/smylte.xml", "getprop"):
        steps.append((command, lambda c=command: dev.save(f"failure-{c}", "txt",
                                                          dev.shell(c, timeout=60, check=False))))
    for name, step in steps:
        try:
            step()
        except Exception as e:   # diagnostics never hide the failure itself
            say(f"diagnostics: {name} failed: {e}")


def write_summary(ctx: Context, results: list[tuple[str, str, float]]) -> None:
    lines = [f"### Android emulator smoke, API {ctx.api}", "", "| Check | Result | Seconds |", "|---|---|---|"]
    lines += [f"| {name} | {result} | {seconds:.0f} |" for name, result, seconds in results]
    lines += [f"- {note}" for note in ctx.notes]
    text = "\n".join(lines) + "\n"
    (ctx.dev.diag / "summary.md").write_text(text, encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(text + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apk", required=True, type=Path, help="the debug APK to install")
    parser.add_argument("--diag", required=True, type=Path, help="where every dump, screenshot and log goes")
    parser.add_argument("--api", required=True, type=int, help="the API level the emulator must run")
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument("--adb", default=None)
    args = parser.parse_args(argv)

    if not args.apk.is_file():
        print(f"::error title=Emulator smoke (API {args.api})::no APK at {args.apk}", flush=True)
        return 2
    args.diag.mkdir(parents=True, exist_ok=True)
    away_ms = lib.parse_away_ms(APP_LOCK_KT.read_text(encoding="utf-8"))
    min_webview = lib.parse_min_webview(HOST_PROTOCOL_KT.read_text(encoding="utf-8"))
    strings = lib.load_strings(STRINGS_XML.read_text(encoding="utf-8"))
    dev = Device(find_adb(args.adb), args.serial, args.diag)
    ctx = Context(dev=dev, api=args.api, strings=strings, away_ms=away_ms, apk=args.apk,
                  min_webview=min_webview)
    say(f"API {args.api}, AppLock.AWAY_MS {away_ms} ms, MIN_WEBVIEW_MAJOR {min_webview}, APK {args.apk}")

    results: list[tuple[str, str, float]] = []
    failure: str | None = None
    try:
        for name, check in CHECKS:
            if failure:
                results.append((name, "not run", 0.0))
                continue
            print(f"::group::{name}", flush=True)
            started = time.monotonic()
            try:
                check(ctx)
                results.append((name, "passed", time.monotonic() - started))
            except CheckFailed as e:
                failure = f"{name}: {e}"
                results.append((name, "FAILED", time.monotonic() - started))
            except Exception as e:   # a bug in this script, or adb gone: still a failure, still diagnosed
                failure = f"{name}: {type(e).__name__}: {e}"
                results.append((name, "ERROR", time.monotonic() - started))
            finally:
                print("::endgroup::", flush=True)
            if failure:
                say(failure)
                final_diagnostics(ctx)
    finally:
        print("::group::crashes and ANRs over the whole run", flush=True)
        try:
            problems = crash_scan(ctx, "final", full=True)
        except Exception as e:
            problems = [f"the final crash scan failed: {type(e).__name__}: {e}"]
        print("::endgroup::", flush=True)
        if problems:
            new = [p for p in problems if p not in (failure or "")]
            if new:
                message = "Smylte crashed or stopped responding: " + " | ".join(new[:6])
                failure = f"{failure}; {message}" if failure else message
            results.append(("crashes and ANRs", "FAILED", 0.0))
        else:
            results.append(("crashes and ANRs", "none", 0.0))
        write_summary(ctx, results)
    if failure:
        print(f"::error title=Emulator smoke (API {args.api})::{annotate(failure)}", flush=True)
        return 1
    say("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
