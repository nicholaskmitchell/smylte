"""Unit tests for smoke_lib.py, the emulator smoke checks' parsers.

No emulator needed:

    python3 -m unittest discover -s .github/emulator -p 'test_*.py' -v

The fixtures in fixtures/ are built from the AOSP code that prints each format
(android11-release and android15-release of platform/frameworks/base), not
captured from a device; each test names the source. Two tests read the app's
own sources (AppLock.kt, strings.xml), so the smoke checks follow the app.
"""
from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import smoke_lib as lib  # noqa: E402

FIXTURES = HERE / "fixtures"
REPO = HERE.parents[1]
APP = "com.nicholaskmitchell.smylte"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class UiDumpTest(unittest.TestCase):
    """AccessibilityNodeInfoDumper.dumpNodeRec / dumpWindowRec, DumpCommand."""

    def test_setup_fields_are_found_by_id(self):
        nodes = lib.parse_ui_dump(fixture("ui-setup-top-api30.xml"))
        for name in ("setup_content", "server", "username", "password", "token", "save", "lock_switch"):
            self.assertTrue(lib.has_id(nodes, APP, name), name)
        self.assertFalse(lib.lock_shown(nodes, APP))
        server = lib.node(nodes, APP, "server")
        self.assertEqual("android.widget.EditText", server.cls)
        self.assertTrue(server.flag("focused"))
        self.assertEqual("true", server.attrs["NAF"])
        self.assertEqual((63, 610, 1017, 734), server.bounds)

    def test_text_is_compared_case_blind(self):
        nodes = lib.parse_ui_dump(fixture("ui-setup-top-api30.xml"))
        self.assertEqual(1, len(lib.find(nodes, text="Check and save")))
        self.assertEqual(1, len(lib.find(nodes, rid=lib.view_id(APP, "save"), text="check and save")))

    def test_switch_state(self):
        nodes = lib.parse_ui_dump(fixture("ui-setup-bottom-pin-api30.xml"))
        switch = lib.node(nodes, APP, "lock_switch")
        self.assertIsNotNone(switch)
        self.assertTrue(switch.flag("checkable"))
        self.assertFalse(switch.flag("checked"))
        self.assertIn("screenshots of Smylte are blocked", lib.node(nodes, APP, "lock_note").text)
        self.assertTrue(lib.has_id(nodes, APP, "version"))
        self.assertFalse(lib.has_id(nodes, APP, "lock_unavailable"))

    def test_no_screen_lock(self):
        nodes = lib.parse_ui_dump(fixture("ui-setup-bottom-nolock-api35.xml"))
        self.assertFalse(lib.has_id(nodes, APP, "lock_switch"))
        self.assertTrue(lib.has_id(nodes, APP, "lock_unavailable"))
        self.assertEqual(1, len(lib.find(nodes, text="App lock")))

    def test_locked_window_has_no_setup_content(self):
        nodes = lib.parse_ui_dump(fixture("ui-locked-setup-api35.xml"))
        self.assertTrue(lib.lock_shown(nodes, APP))
        for name in ("setup_content", "server", "username", "password", "token"):
            self.assertFalse(lib.has_id(nodes, APP, name), name)
        self.assertEqual("Smylte is locked", lib.node(nodes, APP, "lock_title").text)

    def test_prompt_and_its_pin_field(self):
        nodes = lib.parse_ui_dump(fixture("ui-prompt-api30.xml"))
        self.assertTrue(lib.prompt_shown(nodes))
        field = lib.pin_field(nodes)
        self.assertTrue(field.flag("focused"))
        self.assertTrue(field.flag("password"))
        self.assertEqual([], lib.app_nodes(nodes, APP))
        self.assertFalse(lib.prompt_shown(lib.parse_ui_dump(fixture("ui-locked-setup-api35.xml"))))

    def test_all_windows_dump_keeps_each_windows_nodes(self):
        nodes = lib.parse_ui_dump(fixture("ui-windows-api35.xml"))
        self.assertTrue(lib.prompt_shown(nodes))
        app = lib.app_nodes(nodes, APP)
        self.assertTrue(app)
        self.assertEqual({"Smylte"}, {n.window for n in app})
        self.assertTrue(lib.lock_shown(app, APP))
        self.assertFalse(lib.has_id(app, APP, "setup_content"))

    def test_failure_screen(self):
        nodes = lib.parse_ui_dump(fixture("ui-failure-main-api35.xml"))
        for name in ("main_content", "splash_text", "retry", "open_settings"):
            self.assertTrue(lib.has_id(nodes, APP, name), name)
        self.assertTrue(lib.node(nodes, APP, "splash_text").text.startswith("Could not reach GitHub"))

    def test_text_after_the_closing_tag_is_ignored(self):
        # `uiautomator dump /dev/tty` writes the XML in one write() and then
        # prints its message on the same line.
        glued = fixture("ui-prompt-api30.xml") + "UI hierchary dumped to: /dev/tty\n"
        self.assertTrue(lib.prompt_shown(lib.parse_ui_dump(glued)))

    def test_dump_ok(self):
        xml = fixture("ui-prompt-api30.xml")
        self.assertTrue(lib.dump_ok("UI hierchary dumped to: /data/local/tmp/smylte-ui.xml\n", xml)[0])
        self.assertFalse(lib.dump_ok("ERROR: could not get idle state.\n", "")[0])
        self.assertFalse(lib.dump_ok("ERROR: null root node returned by UiTestAutomationBridge.\n", "")[0])
        self.assertFalse(lib.dump_ok("UI hierchary dumped to: /data/local/tmp/smylte-ui.xml\n", "")[0])
        self.assertFalse(lib.dump_ok("UI hierchary dumped to: x\n", "<hierarchy rotation=\"0\">")[0])
        self.assertFalse(lib.dump_ok("", xml)[0])

    def test_bounds(self):
        self.assertEqual((10, 20, 110, 220), lib.parse_bounds("[10,20][110,220]"))
        self.assertEqual((60, 120), lib.centre((10, 20, 110, 220)))
        self.assertIsNone(lib.parse_bounds(""))
        self.assertIsNone(lib.parse_bounds("[1,2]"))


class WindowDumpTest(unittest.TestCase):
    """DisplayContent.dump (mCurrentFocus), WindowManagerService.dumpWindows
    (visible-apps), RootWindowContainer.dumpWindowsNoHeader, WindowState.dump
    and LayoutParams.toString(prefix) with ViewDebug.flagsToString."""

    def test_focus_on_the_prompt(self):
        self.assertEqual("BiometricPrompt", lib.parse_current_focus(fixture("window-visible-apps-api30.txt")))

    def test_focus_on_an_app_window(self):
        self.assertEqual(f"{APP}/{APP}.MainActivity", lib.parse_current_focus(fixture("window-visible-apps-api35.txt")))

    def test_null_focus(self):
        self.assertIsNone(lib.parse_current_focus(fixture("window-displays-no-focus-api30.txt")))

    def test_missing_focus_line_is_an_error(self):
        with self.assertRaises(ValueError):
            lib.parse_current_focus("Can't find service: window\n")

    def test_secure_app_window_under_the_prompt(self):
        blocks = lib.parse_window_blocks(fixture("window-visible-apps-api30.txt"))
        self.assertEqual(1, len(blocks))
        window = lib.app_window(blocks, APP)
        self.assertEqual(f"{APP}/{APP}.SetupActivity", window.title)
        self.assertEqual(APP, window.package)
        self.assertTrue(window.secure)

    def test_splash_and_exiting_windows_are_skipped(self):
        blocks = lib.parse_window_blocks(fixture("window-visible-apps-api35.txt"))
        self.assertEqual(4, len(blocks))
        self.assertEqual("Splash Screen com.nicholaskmitchell.smylte", blocks[0].title)
        self.assertTrue(blocks[1].exiting)
        window = lib.app_window(blocks, APP)
        self.assertEqual(2, window.index)
        self.assertEqual(f"{APP}/{APP}.MainActivity", window.title)
        self.assertFalse(window.secure)
        self.assertFalse(blocks[3].secure)

    def test_no_app_window(self):
        blocks = lib.parse_window_blocks(fixture("window-visible-apps-api35.txt"))
        self.assertIsNone(lib.app_window(blocks, "com.example.absent"))

    def test_secure_flag(self):
        self.assertTrue(lib.is_secure("LAYOUT_IN_SCREEN SECURE HARDWARE_ACCELERATED"))
        self.assertFalse(lib.is_secure("LAYOUT_IN_SCREEN NOT_SECURE_EXAMPLE HARDWARE_ACCELERATED"))
        self.assertFalse(lib.is_secure(""))
        self.assertTrue(lib.is_secure("81812100"))
        self.assertFalse(lib.is_secure("81810100"))


class ActivityDumpTest(unittest.TestCase):
    """ActivityTaskManagerService.dumpActivitiesLocked, ActivityRecord.toString,
    the Hist lines of dumpHistoryList/dumpActivity and KeyguardController.dump."""

    def test_launcher_resumed_and_the_app_still_in_its_task(self):
        text = fixture("activities-api30.txt")
        self.assertEqual("com.google.android.apps.nexuslauncher/.NexusLauncherActivity",
                         lib.parse_resumed_activity(text))
        mine = [r for r in lib.history_records(text) if r.component.startswith(APP + "/")]
        self.assertEqual(2, len(mine))
        self.assertTrue(all(r.component == f"{APP}/.SetupActivity" and not r.finishing for r in mine))
        self.assertEqual({14}, {r.task for r in mine})
        self.assertIs(False, lib.keyguard_showing(text))

    def test_android15_format(self):
        text = fixture("activities-api35.txt")
        self.assertEqual(f"{APP}/.SetupActivity", lib.parse_resumed_activity(text))
        records = lib.history_records(text)
        self.assertEqual(3, len(records))
        main = [r for r in records if r.component == f"{APP}/.MainActivity"]
        self.assertEqual(1, len(main))
        self.assertTrue(main[0].finishing)
        self.assertIs(True, lib.keyguard_showing(text))

    def test_nothing_resumed(self):
        self.assertIsNone(lib.parse_resumed_activity("ACTIVITY MANAGER ACTIVITIES (dumpsys activity activities)\n"))
        self.assertIsNone(lib.keyguard_showing(""))

    def test_record_without_task(self):
        # The first toString() of a record caches its name before the task is
        # known, so the " t<id>" part (and the closing brace) can be missing.
        ref = lib.parse_record(f"ActivityRecord{{abc123 u0 {APP}/.SetupActivity")
        self.assertEqual(f"{APP}/.SetupActivity", ref.component)
        self.assertIsNone(ref.task)


class SmallDumpTest(unittest.TestCase):
    def test_uptime(self):
        self.assertEqual(1234.56, lib.parse_uptime("1234.56 4567.89\n"))
        with self.assertRaises(ValueError):
            lib.parse_uptime("")

    def test_default_network(self):
        # ConnectivityService.dump
        self.assertIs(True, lib.default_network_none(fixture("connectivity-airplane.txt")))
        self.assertIs(False, lib.default_network_none(fixture("connectivity-online.txt")))
        self.assertIsNone(lib.default_network_none("nothing"))

    def test_powered(self):
        # BatteryService.dumpInternal
        self.assertTrue(lib.powered(fixture("battery.txt")))
        self.assertFalse(lib.powered(fixture("battery.txt").replace("AC powered: true", "AC powered: false")))


class CrashTest(unittest.TestCase):
    """RuntimeInit's FATAL EXCEPTION, debuggerd's tombstone line,
    ActivityManager's ANR line, the am_anr event and ApplicationExitInfo.dump."""

    def test_crashes_of_this_app_only(self):
        hits = lib.find_crashes(fixture("logcat-crash.txt"), APP)
        self.assertEqual(2, len(hits), hits)
        self.assertIn("FATAL EXCEPTION: main", hits[0])
        self.assertIn(">>> com.nicholaskmitchell.smylte <<<", hits[1])

    def test_anrs_of_this_app_only(self):
        hits = lib.find_anrs(fixture("logcat-anr.txt"), APP)
        self.assertEqual(2, len(hits), hits)
        self.assertIn("am_anr", hits[0])
        self.assertIn("ANR in com.nicholaskmitchell.smylte (", hits[1])

    def test_clean_logs(self):
        self.assertEqual([], lib.find_crashes(fixture("logcat-anr.txt"), APP))
        self.assertEqual([], lib.find_anrs(fixture("logcat-crash.txt"), APP))

    def test_exit_info(self):
        old = lib.exit_info_failures(fixture("exit-info-api30.txt"))
        self.assertEqual(["reason=4 (APP CRASH(EXCEPTION))"], old)
        new = lib.exit_info_failures(fixture("exit-info-api35.txt"))
        self.assertEqual(2, len(new))
        self.assertIn("(ANR)", new[0])
        self.assertIn("(APP CRASH(NATIVE))", new[1])
        self.assertEqual([], lib.exit_info_failures(fixture("exit-info-clean-api35.txt")))

    def test_unique(self):
        self.assertEqual(["a", "b"], lib.unique(["a", "b", "a"]))


class AppSourceTest(unittest.TestCase):
    """The smoke checks read these from the app at run time."""

    def test_away_ms_from_app_lock(self):
        source = (REPO / "android/src/main/kotlin/com/nicholaskmitchell/smylte/AppLock.kt").read_text(encoding="utf-8")
        self.assertEqual(5 * 60 * 1000, lib.parse_away_ms(source))

    def test_away_ms_forms(self):
        self.assertEqual(300000, lib.parse_away_ms("const val AWAY_MS = 5 * 60 * 1000L\n"))
        self.assertEqual(90000, lib.parse_away_ms("        const val AWAY_MS = 90_000L // note\n"))
        with self.assertRaises(ValueError):
            lib.parse_away_ms("const val AWAY_MS = minutes(5)\n")
        with self.assertRaises(ValueError):
            lib.parse_away_ms("val other = 1\n")

    def test_strings_from_the_app(self):
        strings = lib.load_strings((REPO / "android/src/main/res/values/strings.xml").read_text(encoding="utf-8"))
        self.assertEqual("Smylte is locked", strings["lock_title"])
        self.assertEqual("Unlock", strings["lock_unlock"])
        self.assertEqual("App lock", strings["lock_setting_heading"])
        self.assertEqual("Try again", strings["try_again"])
        self.assertEqual("Settings", strings["settings"])
        self.assertTrue(strings["lock_setting_unavailable"].endswith("in the phone's settings first."))
        for name in ("lock_setting_note", "lock_setting_note_secure", "setup_title", "lock_setting"):
            self.assertIn(name, strings)

    def test_min_webview_from_host_protocol(self):
        source = (REPO / "android/src/main/kotlin/com/nicholaskmitchell/smylte/HostProtocol.kt").read_text(encoding="utf-8")
        self.assertEqual(111, lib.parse_min_webview(source))
        self.assertEqual(120, lib.parse_min_webview("    const val MIN_WEBVIEW_MAJOR = 120\n"))
        with self.assertRaises(ValueError):
            lib.parse_min_webview("const val MIN_WEBVIEW_MAJOR = MINIMUM\n")

    def test_the_outdated_webview_message(self):
        strings = lib.load_strings((REPO / "android/src/main/res/values/strings.xml").read_text(encoding="utf-8"))
        pattern = lib.format_regex(strings["webview_outdated"], {2: r"83(?:\.\d+)*", 3: "111"})
        name = "Android System WebView"
        shown = (f"Smylte needs a newer {name}. It runs on Chromium 111 or later, and this phone's {name} "
                 f"is Chromium 83.0.4103.106. Update {name} from the phone's app store, then tap Try again.")
        self.assertTrue(pattern.fullmatch(shown))
        self.assertIsNone(pattern.fullmatch(shown.replace("Chromium 83.", "Chromium 84.")))
        self.assertIsNone(pattern.fullmatch(shown.replace("Chromium 111", "Chromium 107")))
        # The WebView's name is the same text wherever it appears.
        self.assertIsNone(pattern.fullmatch(shown.replace(f"Update {name}", "Update Vanadium")))
        self.assertIsNone(pattern.fullmatch(shown + " More."))

    def test_format_regex(self):
        self.assertTrue(lib.format_regex("a %1$s b %2$d c %1$s", {2: "7"}).fullmatch("a x.y b 7 c x.y"))
        self.assertIsNone(lib.format_regex("a %1$s b %2$d c %1$s", {2: "7"}).fullmatch("a x b 7 c y"))
        self.assertTrue(lib.format_regex("(%1$s) * %2$s?", {}).fullmatch("(p) * q?"))
        self.assertIsNone(lib.format_regex("(%1$s)", {}).fullmatch("p"))

    def test_android_string_escapes(self):
        self.assertEqual("phone's", lib.android_string(r"phone\'s"))
        self.assertEqual('a "b"', lib.android_string(r'a \"b\"'))
        self.assertEqual("one two", lib.android_string("one\n        two"))
        self.assertEqual("  kept  ", lib.android_string('"  kept  "'))


class WebViewDumpTest(unittest.TestCase):
    def test_current_webview(self):
        self.assertEqual(("com.android.webview", "83.0.4103.106"),
                         lib.current_webview(fixture("webviewupdate-api30.txt")))
        self.assertEqual(("com.google.android.webview", "124.0.6367.219"),
                         lib.current_webview(fixture("webviewupdate-api35.txt")))

    def test_no_current_webview(self):
        dump = "Current WebView Update Service state\n  Current WebView package is null\n" \
               "  Preferred WebView package (name, version): (com.android.webview, 83.0.4103.106)\n"
        self.assertIsNone(lib.current_webview(dump))
        self.assertIsNone(lib.current_webview(""))

    def test_version_major(self):
        self.assertEqual(83, lib.version_major("83.0.4103.106"))
        self.assertEqual(124, lib.version_major(" 124.0.6367.219 "))
        self.assertEqual(140, lib.version_major("140"))
        self.assertIsNone(lib.version_major(""))
        self.assertIsNone(lib.version_major("0.1"))
        self.assertIsNone(lib.version_major("v83"))


class PrefsTest(unittest.TestCase):
    """SharedPreferencesImpl's file, written by XmlUtils.writeMapXml."""

    def test_round_trip(self):
        text = lib.prefs_xml({"origin": "https://smylte.invalid"}, {"app_lock": True})
        self.assertTrue(text.startswith("<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\n<map>\n"))
        self.assertIn('    <string name="origin">https://smylte.invalid</string>\n', text)
        self.assertIn('    <boolean name="app_lock" value="true" />\n', text)
        self.assertEqual({"origin": "https://smylte.invalid", "app_lock": True}, lib.parse_prefs(text))

    def test_values_are_escaped(self):
        text = lib.prefs_xml({"origin": "https://a.invalid/?x=1&y=<2>"}, {})
        self.assertEqual("https://a.invalid/?x=1&y=<2>", lib.parse_prefs(text)["origin"])

    def test_platform_file(self):
        written = (
            "<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\n<map>\n"
            '    <boolean name="app_lock" value="true" />\n'
            '    <long name="last_check" value="1793714400000" />\n'
            '    <int name="theme_colour" value="-15132391" />\n'
            '    <string name="release_etag">W/&quot;abc&quot;</string>\n</map>\n'
        )
        self.assertEqual(
            {"app_lock": True, "last_check": 1793714400000, "theme_colour": -15132391, "release_etag": 'W/"abc"'},
            lib.parse_prefs(written),
        )

    def test_not_a_map(self):
        with self.assertRaises(ValueError):
            lib.parse_prefs("<set />")


class ScriptTest(unittest.TestCase):
    def test_smoke_script_imports(self):
        # smoke.py does nothing at import; this catches a script that would not even start.
        smoke = importlib.import_module("smoke")
        self.assertEqual(9, len(smoke.CHECKS))


if __name__ == "__main__":
    unittest.main()
