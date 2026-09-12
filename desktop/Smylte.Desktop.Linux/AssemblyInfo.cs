using System.Runtime.Versioning;

// This assembly only ever runs on Linux, and saying so is what makes the
// platform analyser useful here rather than noisy.
//
// GirCore annotates its WebKitGTK and libsoup bindings as unsupported on
// Windows and macOS — correctly, since neither has WebKitGTK — so without this
// every one of the thirty-odd calls in WebHost, Notifications and FloatWindow
// is a CA1416 warning about a platform this project has no intention of
// running on. Blanket-suppressing CA1416 would also hide the one warning here
// that IS worth having: PasswordProtector's DPAPI arm is Windows-only, and the
// analyser still checks that it stays behind its `OperatingSystem.IsWindows()`
// guard.
[assembly: SupportedOSPlatform("linux")]
