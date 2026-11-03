# Fixtures for test_smoke_lib.py

Built from the AOSP code that prints each format, not captured from a device:
no emulator could run where they were written. The paths are in
platform/frameworks/base, branches android11-release and android15-release,
unless another repository is named. When a real run's artifacts show a format
that differs, add that output here as a fixture of its own.

| Fixture | Format | Printed by |
|---|---|---|
| `ui-*.xml` | `uiautomator dump` | `cmds/uiautomator/library/core-src/com/android/uiautomator/core/AccessibilityNodeInfoDumper.java` (`dumpNodeRec`; `dumpWindowRec` for `--windows`), through KXmlSerializer |
| `ui-prompt-api30.xml`, `ui-windows-api35.xml` | the system's PIN prompt | `packages/SystemUI/res/layout/auth_container_view.xml`, `auth_credential_password_view.xml` (android11), `auth_credential_password_pin_content_view.xml` (android15) |
| `window-*.txt` | `dumpsys window displays`, `dumpsys window visible-apps` | `services/core/java/com/android/server/wm/`: `DisplayContent.dump`, `WindowManagerService.dumpWindows`, `RootWindowContainer.dumpWindowsNoHeader`, `WindowState.dump` and `toString`; `core/java/android/view/WindowManager.java` `LayoutParams.toString(String)`; `ViewDebug.flagsToString` |
| `activities-*.txt` | `dumpsys activity activities` | `ActivityTaskManagerService.dumpActivitiesLocked`, `ActivityRecord.toString`, `ActivityStackSupervisor`/`ActivityTaskSupervisor.dumpHistoryList` and `dump`, `KeyguardController.dump` |
| `exit-info-*.txt` | `dumpsys activity exit-info <package>` | `core/java/android/app/ApplicationExitInfo.java` `dump` |
| `logcat-crash.txt` | `logcat -v threadtime`, crash buffer | `core/java/com/android/internal/os/RuntimeInit.java`; bionic's fatal signal message and debuggerd's `>>> name <<<` line |
| `logcat-anr.txt` | `logcat -v threadtime`, main and events | `ProcessRecord` (android11) / `ProcessErrorStateRecord` (android15) "ANR in", the `am_anr` event |
| `connectivity-*.txt` | `dumpsys connectivity` | `ConnectivityService.dump` (packages/modules/Connectivity on android15) |
| `battery.txt` | `dumpsys battery` | `services/core/java/com/android/server/BatteryService.java` |
| `webviewupdate-*.txt` | `dumpsys webviewupdate` | `services/core/java/com/android/server/webkit/WebViewUpdateServiceImpl.java` and `WebViewUpdater.java` `dumpState` (android11), `WebViewUpdateServiceImpl2.java` `dumpState` (android15); the versions are examples |
