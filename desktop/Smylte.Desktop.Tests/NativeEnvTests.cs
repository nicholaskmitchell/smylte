using Smylte.Desktop;
using Xunit;

namespace Smylte.Desktop.Tests;

/// Setting an environment variable so that NATIVE code can read it.
///
/// **The bug this pins was invisible from managed code.** On Linux
/// `Environment.SetEnvironmentVariable` writes a dictionary inside the runtime
/// and never calls `setenv(3)` — `libSystem.Native` exports no entry point for
/// one — while `Environment.GetEnvironmentVariable` reads that same dictionary
/// straight back. Every managed check therefore agreed that the value was set.
///
/// The client's whole X11 default rested on it: GDK reads `GDK_BACKEND` with
/// `g_getenv()`, saw nothing, and opened whatever backend it would have chosen
/// anyway — which on a stock Fedora Workstation session is Wayland, the one the
/// floating window exists to avoid. The NVIDIA blank-page workaround
/// (`WEBKIT_DISABLE_DMABUF_RENDERER`) was inert for the same reason, and so was
/// the setting documented as its escape hatch.
///
/// So the assertion here is deliberately the one that broke: what a NATIVE
/// reader sees. Asserting the managed read-back would have passed before the
/// fix, which is precisely the trap.
public sealed class NativeEnvTests
{
    /// Unique per run, so a leaked value from an earlier run cannot pass this —
    /// and unique per TEST, which is what keeps this class out of the "xdg"
    /// collection the two Settings classes share: xunit runs classes in
    /// parallel and the environment is process-wide, so a fixed name here
    /// would be a race with itself.
    private static string Name() => "SMYLTE_TEST_" + Guid.NewGuid().ToString("N");

    [Fact]
    public void A_value_set_through_NativeEnv_is_visible_to_getenv()
    {
        var name = Name();
        Assert.Null(NativeEnv.GetNative(name));

        Assert.True(NativeEnv.Set(name, "x11"));

        // The half that was missing. Before the fix this was null while the
        // line below returned "x11".
        Assert.Equal("x11", NativeEnv.GetNative(name));
        Assert.Equal("x11", Environment.GetEnvironmentVariable(name));
    }

    [Fact]
    public void The_managed_copy_is_written_too_so_a_child_process_inherits_it()
    {
        // Not redundant with the native write: .NET builds a child's
        // environment from the managed dictionary, so a helper this client
        // spawns would not see a value written only with setenv.
        var name = Name();
        NativeEnv.Set(name, "wayland");
        Assert.Equal("wayland", Environment.GetEnvironmentVariable(name));
    }

    [Fact]
    public void Setting_a_name_twice_overwrites_it()
    {
        // `setenv(name, value, overwrite)` with overwrite = 0 keeps the first
        // value and reports success, which would make the second of the two
        // calls Program.Main makes a silent no-op if the variable was already
        // in the environment — the common case for GDK_BACKEND.
        var name = Name();
        NativeEnv.Set(name, "first");
        NativeEnv.Set(name, "second");
        Assert.Equal("second", NativeEnv.GetNative(name));
    }

    [Fact]
    public void Reading_a_name_nobody_set_is_null_rather_than_empty()
    {
        Assert.Null(NativeEnv.GetNative(Name()));
    }
}
