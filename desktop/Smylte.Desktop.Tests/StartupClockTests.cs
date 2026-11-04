using Smylte.Desktop;
using Xunit;

namespace Smylte.Desktop.Tests;

public sealed class StartupClockTests
{
    [Fact]
    public void Each_step_is_named_with_how_long_it_took()
    {
        var text = StartupClock.Describe(new[]
        {
            ("update check", TimeSpan.FromSeconds(3)),
            ("sign-in", TimeSpan.FromMilliseconds(420)),
        }, TimeSpan.FromSeconds(3.42));

        Assert.Equal("Smylte: started in 3.4 s (update check 3.0 s, sign-in 0.4 s)", text);
    }

    [Fact]
    public void Marks_measure_from_the_one_before()
    {
        var clock = new StartupClock();
        clock.Mark("first");
        Thread.Sleep(20);
        clock.Mark("second");

        Assert.True(clock.Total >= TimeSpan.FromMilliseconds(20));
        Assert.Contains("second", clock.Describe(), StringComparison.Ordinal);
    }
}
