using System.Runtime.InteropServices;

namespace Smylte.Desktop;

/// Setting an environment variable so that NATIVE code can read it.
///
/// **`Environment.SetEnvironmentVariable` does not do this on Linux.** It
/// mutates a dictionary inside the runtime and nothing else: there is no
/// `setenv` call behind it, and `libSystem.Native` exports no entry point for
/// one. A managed `GetEnvironmentVariable` reads the value straight back, which
/// is exactly why this is so easy to get wrong — the value looks set from every
/// angle except the only one that matters.
///
/// GLib reads the environment with `g_getenv()`, which is `getenv(3)`. So GDK
/// never saw `GDK_BACKEND` and WebKitGTK never saw
/// `WEBKIT_DISABLE_DMABUF_RENDERER`: the client asked for X11 and got whatever
/// GDK would have picked anyway, which on a stock Fedora Workstation session is
/// Wayland — the backend the whole floating-window design exists to avoid. The
/// NVIDIA blank-page workaround was inert for the same reason.
///
/// Proven rather than reasoned about, because "the runtime surely does this"
/// was the assumption that produced the bug:
///
///     Environment.SetEnvironmentVariable("GDK_BACKEND", "x11");
///     managed = x11      native (libc getenv) = null
///     after setenv():    native = x11
///
/// Both are written. The managed copy is not redundant — child processes are
/// started from it, so a helper this client spawns should see the same value.
internal static class NativeEnv
{
    [DllImport("libc", EntryPoint = "setenv", SetLastError = true)]
    private static extern int SetEnvNative(string name, string value, int overwrite);

    [DllImport("libc", EntryPoint = "getenv")]
    private static extern IntPtr GetEnvNative(string name);

    /// Set `name` for this process, in both environments. Returns false when the
    /// native half could not be written — which is not fatal on its own, but a
    /// caller relying on a native reader should know.
    public static bool Set(string name, string value)
    {
        Environment.SetEnvironmentVariable(name, value);
        if (OperatingSystem.IsWindows()) return true;   // one environment there
        try
        {
            return SetEnvNative(name, value, 1) == 0;
        }
        catch (Exception)
        {
            // No libc, or a platform without it. The managed copy still stands.
            return false;
        }
    }

    /// What a NATIVE reader would see. Exists so the regression test can assert
    /// the thing that actually broke rather than the thing that looked fine.
    public static string? GetNative(string name)
    {
        if (OperatingSystem.IsWindows()) return Environment.GetEnvironmentVariable(name);
        try
        {
            var pointer = GetEnvNative(name);
            return pointer == IntPtr.Zero ? null : Marshal.PtrToStringUTF8(pointer);
        }
        catch (Exception)
        {
            return null;
        }
    }
}
