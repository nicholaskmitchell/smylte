"""Pure helpers for the emulator smoke checks (smoke.py, android-emulator.yml).

Everything here parses text that adb hands back (a uiautomator dump, dumpsys,
logcat, the app's SharedPreferences) or the app's own sources. Nothing here
touches a device, so test_smoke_lib.py covers it without an emulator:

    python3 -m unittest discover -s .github/emulator -p 'test_*.py'

Each parser names the AOSP source its format comes from. They were written
against the android11-release and android15-release branches of
platform/frameworks/base; where the two differ, both forms are accepted.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from xml.sax.saxutils import escape

SYSTEMUI = "com.android.systemui"


# ── uiautomator dumps ───────────────────────────────────────────────────────
#
# cmds/uiautomator/.../AccessibilityNodeInfoDumper.java: one <hierarchy
# rotation="0"> holding nested <node> elements, each with index, text,
# resource-id, class, package, content-desc, checkable, checked, clickable,
# enabled, focusable, focused, scrollable, long-clickable, password, selected
# and bounds="[x1,y1][x2,y2]". Only children that are visible to the user are
# written. `dump --windows` wraps one <hierarchy> per window in
# <displays><display id><window title ...>.


@dataclass
class Node:
    attrs: dict
    # The title of the <window> the node came from in a --windows dump, else "".
    window: str = ""

    @property
    def rid(self) -> str:
        return self.attrs.get("resource-id", "")

    @property
    def text(self) -> str:
        return self.attrs.get("text", "")

    @property
    def cls(self) -> str:
        return self.attrs.get("class", "")

    @property
    def package(self) -> str:
        return self.attrs.get("package", "")

    def flag(self, name: str) -> bool:
        return self.attrs.get(name) == "true"

    @property
    def bounds(self) -> tuple[int, int, int, int] | None:
        return parse_bounds(self.attrs.get("bounds", ""))


_DUMP_END = re.compile(r"</(?:hierarchy|displays)>")


def parse_ui_dump(text: str) -> list[Node]:
    """Every <node> in a dump, in document order, at any depth.

    Anything after the closing tag is dropped: `uiautomator dump /dev/tty`
    glues its "UI hierchary dumped to:" line straight after it."""
    start = text.find("<")
    ends = list(_DUMP_END.finditer(text))
    if start < 0 or not ends:
        raise ValueError("no <hierarchy> or <displays> element in the dump")
    root = ET.fromstring(text[start:ends[-1].end()].encode("utf-8"))
    nodes: list[Node] = []

    def walk(element: ET.Element, window: str) -> None:
        if element.tag == "window":
            window = element.get("title", "")
        if element.tag == "node":
            nodes.append(Node(dict(element.attrib), window))
        for child in element:
            walk(child, window)

    walk(root, "")
    return nodes


def dump_ok(output: str, xml_text: str) -> tuple[bool, str]:
    """Whether one `uiautomator dump FILE` run worked, and why not.

    DumpCommand.java prints "ERROR: could not get idle state." or "ERROR: null
    root node returned by UiTestAutomationBridge." and returns without writing;
    "UI hierchary dumped to: FILE" (sic) only after a write, which can still
    have failed (dumpWindowToFile only logs an IOException), so the file is
    checked too."""
    if "ERROR" in output:
        return False, output.strip()
    if "dumped to" not in output:
        return False, f"uiautomator printed no 'dumped to' line: {output.strip()!r}"
    if not xml_text.strip():
        return False, "the dump file is empty"
    try:
        nodes = parse_ui_dump(xml_text)
    except (ET.ParseError, ValueError) as e:
        return False, f"the dump is not a uiautomator hierarchy: {e}"
    if not nodes:
        return False, "the dump has no nodes"
    return True, f"{len(nodes)} nodes"


_BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def parse_bounds(text: str) -> tuple[int, int, int, int] | None:
    m = _BOUNDS.fullmatch(text.strip())
    if not m:
        return None
    x1, y1, x2, y2 = (int(g) for g in m.groups())
    return x1, y1, x2, y2


def centre(bounds: tuple[int, int, int, int]) -> tuple[int, int]:
    x1, y1, x2, y2 = bounds
    return (x1 + x2) // 2, (y1 + y2) // 2


def view_id(package: str, name: str) -> str:
    """The resource-id a dump gives the app's view `R.id.<name>`."""
    return f"{package}:id/{name}"


def find(nodes: list[Node], *, rid: str | None = None, text: str | None = None,
         package: str | None = None) -> list[Node]:
    """The nodes matching every criterion given. Text is compared case-blind:
    the app's DeviceDefault theme sets buttons in capitals on some versions,
    and a dump reports the text as drawn."""
    out = []
    for n in nodes:
        if rid is not None and n.rid != rid:
            continue
        if text is not None and n.text.casefold() != text.casefold():
            continue
        if package is not None and n.package != package:
            continue
        out.append(n)
    return out


def app_nodes(nodes: list[Node], package: str) -> list[Node]:
    return [n for n in nodes if n.package == package]


def has_id(nodes: list[Node], package: str, name: str) -> bool:
    return bool(find(nodes, rid=view_id(package, name)))


def node(nodes: list[Node], package: str, name: str) -> Node | None:
    found = find(nodes, rid=view_id(package, name))
    return found[0] if found else None


def lock_shown(nodes: list[Node], package: str) -> bool:
    """The app's lock view (layout/lock.xml) is on screen."""
    return has_id(nodes, package, "lock_title") and has_id(nodes, package, "lock_unlock")


def pin_field(nodes: list[Node]) -> Node | None:
    """The system prompt's credential field. SystemUI's auth_credential_pin_view
    and auth_credential_password_view (android11 to android16) both call it
    lockPassword."""
    for n in nodes:
        if n.package == SYSTEMUI and n.rid.endswith(":id/lockPassword"):
            return n
    return None


def prompt_shown(nodes: list[Node]) -> bool:
    return pin_field(nodes) is not None


# ── dumpsys window ──────────────────────────────────────────────────────────
#
# `dumpsys window displays` (and the first part of `dumpsys window
# visible-apps`): DisplayContent.dump prints "  mCurrentFocus=" + the focused
# WindowState, whose toString() is "Window{<hash> u<user> <title>}", with
# " EXITING" before the brace while it animates away.
#
# `dumpsys window visible-apps` then lists only the visible windows that belong
# to an activity, top to bottom (WindowManagerService.dumpWindows), each as
# RootWindowContainer.dumpWindowsNoHeader prints it: "  Window #<n> <window>:"
# and then WindowState.dump with a 4-space prefix. Its third line is
# "mAttrs=" + LayoutParams.toString(prefix), which puts the flags on a line of
# their own, "      fl=NAME NAME ...", from ViewDebug.flagsToString: names
# joined by single spaces, FLAG_SECURE named SECURE, and plain hex only for a
# class without a flag mapping.

_FOCUS = re.compile(r"^\s*mCurrentFocus=(.*?)\s*$", re.M)
_WINDOW = re.compile(r"Window\{([0-9a-f]+) u(\d+) (.*)\}")
_WINDOW_HEADER = re.compile(r"^  Window #(\d+) Window\{([0-9a-f]+) u(\d+) (.*)\}:\s*$")
_FLAGS = re.compile(r"^\s+fl=(.*?)\s*$")
_OWNER = re.compile(r"^\s+mOwnerUid=\d+ .*\bpackage=(\S+)")
_HEX = re.compile(r"(?:0x)?([0-9a-fA-F]+)")
FLAG_SECURE = 0x2000


def _title(raw: str) -> tuple[str, bool]:
    if raw.endswith(" EXITING"):
        return raw[: -len(" EXITING")], True
    return raw, False


def parse_current_focus(text: str) -> str | None:
    """The focused window's title, or None for mCurrentFocus=null.

    Raises ValueError when the dump has no mCurrentFocus line at all, so that
    a dumpsys that failed is never read as "nothing has focus"."""
    m = _FOCUS.search(text)
    if not m:
        raise ValueError("no mCurrentFocus line in dumpsys window")
    value = m.group(1)
    if value == "null":
        return None
    w = _WINDOW.fullmatch(value)
    if not w:
        raise ValueError(f"unrecognised mCurrentFocus: {value!r}")
    return _title(w.group(3))[0]


def is_secure(flags: str) -> bool:
    """Whether an "fl=" value carries FLAG_SECURE."""
    tokens = flags.split()
    if "SECURE" in tokens:
        return True
    if len(tokens) == 1:
        m = _HEX.fullmatch(tokens[0])
        if m and not tokens[0].isalpha():
            return bool(int(m.group(1), 16) & FLAG_SECURE)
    return False


@dataclass
class WindowBlock:
    index: int
    hash: str
    title: str
    exiting: bool
    package: str | None
    flags: str | None

    @property
    def secure(self) -> bool | None:
        return None if self.flags is None else is_secure(self.flags)


def parse_window_blocks(text: str) -> list[WindowBlock]:
    """The "  Window #n" blocks of a `dumpsys window windows` or `visible-apps`,
    in the order printed (top to bottom), each with its first fl= line."""
    blocks: list[WindowBlock] = []
    current: WindowBlock | None = None
    for line in text.splitlines():
        header = _WINDOW_HEADER.match(line)
        if header:
            title, exiting = _title(header.group(4))
            current = WindowBlock(int(header.group(1)), header.group(2), title, exiting, None, None)
            blocks.append(current)
            continue
        if current is None:
            continue
        if line.strip() and not line.startswith("    "):
            current = None   # past the block: a section printed after the windows
            continue
        if current.package is None:
            owner = _OWNER.match(line)
            if owner:
                current.package = owner.group(1)
                continue
        if current.flags is None:
            flags = _FLAGS.match(line)
            if flags:
                current.flags = flags.group(1)
    return blocks


def app_window(blocks: list[WindowBlock], package: str) -> WindowBlock | None:
    """The top-most of the app's activity windows in the list: its title is
    "<package>/<activity class>" (the platform's splash window is titled
    "Splash Screen <package>" and is skipped), and it is not animating away."""
    for b in blocks:
        if b.title.startswith(package + "/") and not b.exiting:
            return b
    return None


# ── dumpsys activity activities ─────────────────────────────────────────────
#
# ActivityTaskManagerService.dumpActivitiesLocked prints
# "  ResumedActivity: " + the top resumed ActivityRecord, then the task
# supervisor's dump, which ends with KeyguardController.dump:
# "    mKeyguardShowing=<bool>". ActivityRecord.toString() is
# "ActivityRecord{<hash> u<user> <package>/<short class> t<task>}" with " f}"
# before the last brace while finishing (" isExiting" may follow it). Each
# activity of a task is listed as "* Hist #<i>: <record>" (android11's label is
# "Hist") or "* Hist  #<i>: <record>" (android15's is "Hist ").

_RECORD = re.compile(
    r"ActivityRecord\{([0-9a-f]+) u(\d+) ([^\s/{}]+)/([^\s{}]+)(?: t(-?\d+))?( f\})?"
)
_RESUMED = re.compile(r"^\s*ResumedActivity: (ActivityRecord\{.*)$", re.M)
_HIST = re.compile(r"^\s*\*?\s*Hist\s+#\d+:\s+(ActivityRecord\{.*)$", re.M)
_KEYGUARD = re.compile(r"\bmKeyguardShowing=(true|false)\b")


@dataclass
class ActivityRef:
    hash: str
    component: str
    task: int | None
    finishing: bool


def parse_record(text: str) -> ActivityRef | None:
    m = _RECORD.search(text)
    if not m:
        return None
    task = int(m.group(5)) if m.group(5) is not None else None
    return ActivityRef(m.group(1), f"{m.group(3)}/{m.group(4)}", task, m.group(6) is not None)


def parse_resumed_activity(text: str) -> str | None:
    """The top resumed activity's component ("package/.Class"), or None when
    nothing is resumed (in the middle of a transition)."""
    m = _RESUMED.search(text)
    if not m:
        return None
    ref = parse_record(m.group(1))
    return ref.component if ref else None


def history_records(text: str) -> list[ActivityRef]:
    """Every activity listed in a task ("Hist" lines)."""
    out = []
    for m in _HIST.finditer(text):
        ref = parse_record(m.group(1))
        if ref:
            out.append(ref)
    return out


def keyguard_showing(text: str) -> bool | None:
    m = _KEYGUARD.search(text)
    return None if m is None else m.group(1) == "true"


# ── small dumps ─────────────────────────────────────────────────────────────


def parse_uptime(text: str) -> float:
    """/proc/uptime's first field: seconds since boot, sleep included (the
    clock SystemClock.elapsedRealtime reads, which AppLock counts away time on)."""
    fields = text.split()
    if not fields:
        raise ValueError("empty /proc/uptime")
    return float(fields[0])


_DEFAULT_NETWORK = re.compile(r"^Active default network: (\S+)", re.M)


def default_network_none(text: str) -> bool | None:
    """Whether `dumpsys connectivity` says there is no default network
    (ConnectivityService.dump: "Active default network: none", else its netId);
    None when the line is missing."""
    m = _DEFAULT_NETWORK.search(text)
    return None if m is None else m.group(1) == "none"


_POWERED = re.compile(r"^\s*(?:AC|USB|Wireless) powered: true\s*$", re.M)


def powered(battery_dump: str) -> bool:
    """Whether `dumpsys battery` reports a charger, which `stay_on_while_plugged_in` needs."""
    return bool(_POWERED.search(battery_dump))


# ── crashes and ANRs ────────────────────────────────────────────────────────
#
# RuntimeInit's handler logs "FATAL EXCEPTION: <thread>" then
# "Process: <name>, PID: <pid>" (to the crash buffer and AndroidRuntime). A
# native crash: libc's "Fatal signal ... pid <pid> (<name>)" and debuggerd's
# ">>> <name> <<<". An ANR: ActivityManager's "ANR in <process>" and the events
# buffer's am_anr "[user,pid,<process>,flags,reason]". `dumpsys activity
# exit-info <package>` prints each ApplicationExitInfo with
# "reason=<n> (<name>)", where the names for these are ANR,
# APP CRASH(EXCEPTION) and APP CRASH(NATIVE).


def _process(package: str) -> str:
    # The app's main process or any ":name" process of it.
    return re.escape(package) + r"(?::[\w.]+)?"


def find_crashes(logcat: str, package: str) -> list[str]:
    proc = _process(package)
    process_line = re.compile(rf"Process: {proc}(?:,|\s|$)")
    tombstone = re.compile(rf">>> {proc} <<<")
    signal = re.compile(rf"\({proc}\)")
    lines = logcat.splitlines()
    hits = []
    for i, line in enumerate(lines):
        if "FATAL EXCEPTION" in line:
            if any(process_line.search(following) for following in lines[i + 1:i + 4]):
                hits.append(line.strip())
        elif tombstone.search(line) or ("Fatal signal" in line and signal.search(line)):
            hits.append(line.strip())
    return hits


def find_anrs(logcat: str, package: str) -> list[str]:
    proc = _process(package)
    # ActivityManager is the tag ProcessRecord (android11) and
    # ProcessErrorStateRecord (android15) log the ANR under.
    anr_in = re.compile(rf"\bActivityManager\b.*?\bANR in {proc}(?=[\s(:]|$)")
    am_anr = re.compile(rf"\bam_anr\b.*[\[,]\d+,{proc},")
    return [line.strip() for line in logcat.splitlines() if anr_in.search(line) or am_anr.search(line)]


_EXIT_FAILURE = re.compile(r"reason=\d+ \((?:ANR|APP CRASH\(EXCEPTION\)|APP CRASH\(NATIVE\))\)")


def exit_info_failures(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if _EXIT_FAILURE.search(line)]


def unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


# ── dumpsys webviewupdate ───────────────────────────────────────────────────
#
# WebViewUpdater.dumpState (android11, services/core/java/com/android/server/
# webkit/) and WebViewUpdateServiceImpl2.dumpState (android15) both print
#   "  Current WebView package (name, version): (<package>, <versionName>)"
# or "  Current WebView package is null". A "Preferred WebView package" line of
# the same shape follows, which is not the one in use.

_WEBVIEW_CURRENT = re.compile(
    r"^\s*Current WebView package \(name, version\): \((?P<package>[^,()]+), (?P<version>[^()]*)\)\s*$",
    re.MULTILINE,
)


def current_webview(dumpsys: str) -> tuple[str, str] | None:
    """(package, versionName) of the WebView in use, or None when none is."""
    m = _WEBVIEW_CURRENT.search(dumpsys)
    return (m.group("package").strip(), m.group("version").strip()) if m else None


def version_major(version: str) -> int | None:
    """The first number of a version name ("83.0.4103.106" is 83), as the
    app's HostProtocol.webViewMajor reads it; None when there is none."""
    head = version.strip().split(".", 1)[0]
    return int(head) if head.isdigit() and int(head) > 0 else None


# ── the app's own sources ───────────────────────────────────────────────────

_AWAY_MS = re.compile(r"const\s+val\s+AWAY_MS\s*=\s*([^\n/]+)")
_FACTOR = re.compile(r"\d[\d_]*L?")


def parse_away_ms(kotlin: str) -> int:
    """AppLock.AWAY_MS from AppLock.kt, a product of integer literals such as
    `5 * 60 * 1000L`, so the relock check follows the app if it changes."""
    m = _AWAY_MS.search(kotlin)
    if not m:
        raise ValueError("no `const val AWAY_MS = ...` in AppLock.kt")
    product = 1
    for factor in m.group(1).split("*"):
        factor = factor.strip()
        if not _FACTOR.fullmatch(factor):
            raise ValueError(f"AWAY_MS is not a product of integer literals: {m.group(1).strip()!r}")
        product *= int(factor.rstrip("L").replace("_", ""))
    return product


_MIN_WEBVIEW = re.compile(r"const\s+val\s+MIN_WEBVIEW_MAJOR\s*=\s*(\d+)\b")


def parse_min_webview(kotlin: str) -> int:
    """HostProtocol.MIN_WEBVIEW_MAJOR from HostProtocol.kt: the oldest
    Chromium major the app starts on, below which it shows its failure screen."""
    m = _MIN_WEBVIEW.search(kotlin)
    if not m:
        raise ValueError("no `const val MIN_WEBVIEW_MAJOR = <number>` in HostProtocol.kt")
    return int(m.group(1))


_FORMAT_ARG = re.compile(r"%(\d+)\$[sd]")


def format_regex(template: str, given: dict[int, str]) -> re.Pattern[str]:
    """A string resource with positional arguments (%1$s, %3$d) as a pattern
    for the text Android shows. The arguments in `given` match their own
    pattern; any other matches some text, the same text wherever it repeats.
    Use it with fullmatch."""
    parts: list[str] = []
    seen: set[int] = set()
    last = 0
    for m in _FORMAT_ARG.finditer(template):
        parts.append(re.escape(template[last:m.start()]))
        n = int(m.group(1))
        if n in given:
            parts.append(f"(?:{given[n]})")
        elif n in seen:
            parts.append(f"(?P=arg{n})")
        else:
            parts.append(f"(?P<arg{n}>.+?)")
            seen.add(n)
        last = m.end()
    parts.append(re.escape(template[last:]))
    return re.compile("".join(parts), re.DOTALL)


_ESCAPES = {"n": "\n", "t": "\t"}


def android_string(raw: str) -> str:
    """A <string> resource's text as Android shows it: whitespace collapsed
    unless the whole value is double-quoted, and backslash escapes resolved."""
    value = raw.strip()
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
    else:
        value = re.sub(r"\s+", " ", value)
    return re.sub(r"\\(.)", lambda m: _ESCAPES.get(m.group(1), m.group(1)), value)


def load_strings(xml_text: str) -> dict[str, str]:
    """name -> text for every <string> in a values/strings.xml."""
    root = ET.fromstring(xml_text.encode("utf-8"))
    return {
        el.get("name"): android_string("".join(el.itertext()))
        for el in root.iter("string")
        if el.get("name")
    }


# ── SharedPreferences ───────────────────────────────────────────────────────
#
# SharedPreferencesImpl writes XmlUtils.writeMapXml through FastXmlSerializer:
#   <?xml version='1.0' encoding='utf-8' standalone='yes' ?>
#   <map>
#       <string name="origin">https://example.org</string>
#       <boolean name="app_lock" value="true" />
#   </map>


def prefs_xml(strings: dict[str, str], booleans: dict[str, bool]) -> str:
    lines = ["<?xml version='1.0' encoding='utf-8' standalone='yes' ?>", "<map>"]
    for name, value in strings.items():
        lines.append(f'    <string name="{escape(name, {chr(34): "&quot;"})}">{escape(value)}</string>')
    for name, value in booleans.items():
        lines.append(f'    <boolean name="{escape(name, {chr(34): "&quot;"})}" value="{"true" if value else "false"}" />')
    lines.append("</map>")
    return "\n".join(lines) + "\n"


def parse_prefs(xml_text: str) -> dict[str, object]:
    root = ET.fromstring(xml_text.strip().encode("utf-8"))
    if root.tag != "map":
        raise ValueError(f"a SharedPreferences file's root is <map>, not <{root.tag}>")
    out: dict[str, object] = {}
    for el in root:
        name = el.get("name")
        if name is None:
            continue
        if el.tag == "string":
            out[name] = el.text or ""
        elif el.tag == "boolean":
            out[name] = el.get("value") == "true"
        elif el.tag in ("int", "long"):
            out[name] = int(el.get("value", "0"))
        elif el.tag == "float":
            out[name] = float(el.get("value", "0"))
    return out
