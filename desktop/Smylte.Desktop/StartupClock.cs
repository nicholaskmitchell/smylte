using System.Diagnostics;
using System.Globalization;
using System.Text;

namespace Smylte.Desktop;

/// How long each step of a start took, said once the page is handed over.
///
/// A slow start is invisible from inside: the window shows "Starting…" or
/// nothing at all, and whether the time went to GitHub, the web engine or the
/// sign-in cannot be read off it. So every start prints its steps to stderr,
/// and one slow enough to notice also leaves a line in errors.log, which is
/// where the README sends anyone reporting a problem.
public sealed class StartupClock
{
    /// Past this a start is worth a line in the log.
    internal static readonly TimeSpan Slow = TimeSpan.FromSeconds(5);

    private readonly Stopwatch _watch = Stopwatch.StartNew();
    private readonly List<(string Step, TimeSpan Took)> _steps = new();
    private TimeSpan _last;

    public void Mark(string step)
    {
        var now = _watch.Elapsed;
        _steps.Add((step, now - _last));
        _last = now;
    }

    public TimeSpan Total => _last;

    /// "Smylte: started in 4.2 s (update check 3.0 s, web engine 0.4 s, …)".
    public string Describe() => Describe(_steps, _last);

    internal static string Describe(IReadOnlyList<(string Step, TimeSpan Took)> steps, TimeSpan total)
    {
        var text = new StringBuilder("Smylte: started in ").Append(Seconds(total));
        if (steps.Count > 0)
            text.Append(" (")
                .Append(string.Join(", ", steps.Select(s => $"{s.Step} {Seconds(s.Took)}")))
                .Append(')');
        return text.ToString();
    }

    private static string Seconds(TimeSpan t) =>
        t.TotalSeconds.ToString("0.0", CultureInfo.InvariantCulture) + " s";

    public void Report(Settings settings)
    {
        var line = Describe();
        Console.Error.WriteLine(line);
        if (Total < Slow) return;
        try
        {
            var dir = string.IsNullOrEmpty(settings.DataFolder) ? Path.GetTempPath() : settings.DataFolder;
            Directory.CreateDirectory(dir);
            File.AppendAllText(Path.Combine(dir, "errors.log"),
                $"{DateTime.UtcNow:O}  slow start: {line}{Environment.NewLine}");
        }
        catch (Exception) { /* a breadcrumb, not a reason to fail */ }
    }
}
