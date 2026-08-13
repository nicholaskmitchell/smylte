namespace Smylte.Desktop;

internal static class Program
{
    /// Named per-user, not global: two people signed into the same machine each
    /// get their own client, with their own DPAPI-scoped credentials.
    private const string InstanceMutex = @"Local\SmylteDesktopSingleInstance";

    [STAThread]
    private static void Main(string[] args)
    {
        using var mutex = new Mutex(initiallyOwned: true, InstanceMutex, out var isFirst);
        if (!isFirst) return;   // already running; the existing window is the app

        ApplicationConfiguration.Initialize();

        var settings = Settings.Load();

        // `Smylte.exe --setup` reopens configuration without having to lose the
        // installed build — the way to change server or credentials later.
        var wantsSetup = args.Any(a =>
            a.Equals("--setup", StringComparison.OrdinalIgnoreCase) ||
            a.Equals("/setup", StringComparison.OrdinalIgnoreCase));

        if (wantsSetup || !settings.IsConfigured)
        {
            using var setup = new SetupForm(settings);
            if (setup.ShowDialog() != DialogResult.OK) return;
            settings = setup.Result;
        }

        Application.Run(new MainForm(settings));
    }
}
