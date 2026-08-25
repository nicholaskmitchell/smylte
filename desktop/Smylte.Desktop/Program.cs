namespace Smylte.Desktop;

internal static class Program
{
    /// Named per-user, not global: two people signed into the same machine each
    /// get their own client, with their own DPAPI-scoped credentials.
    private const string InstanceMutex = @"Local\SmylteDesktopSingleInstance";

    [STAThread]
    private static void Main(string[] args)
    {
        // `Smylte.exe --setup` reopens configuration without having to lose the
        // installed build — the way to change server or credentials later, and
        // what desktop/README.md tells the user to run.
        //
        // Read BEFORE the single-instance check, which is where it used to sit.
        // Nine lines below a `return`, it could never be true for the launch
        // that carried the flag: with the app open, `--setup` exited silently —
        // no window, no message, nothing the user could tell apart from the
        // program not existing — and the running window has no menu or settings
        // affordance either, so there was no way to reach the dialog at all.
        var wantsSetup = args.Any(a =>
            a.Equals("--setup", StringComparison.OrdinalIgnoreCase) ||
            a.Equals("/setup", StringComparison.OrdinalIgnoreCase));

        // Ahead of the mutex check now, because the "already running" branch can
        // show a dialog: SetCompatibleTextRenderingDefault has to run before the
        // process creates its first window, and a MessageBox is a window.
        ApplicationConfiguration.Initialize();

        using var mutex = new Mutex(initiallyOwned: true, InstanceMutex, out var isFirst);
        if (!isFirst)
        {
            // Already running; the existing window is the app. Silence is fine
            // for a plain second launch, but a user who typed `--setup` asked
            // for something and has to be told why it did not happen.
            if (wantsSetup)
            {
                MessageBox.Show(
                    "Smylte is already running.\n\n" +
                    "Close it first, then run Smylte.exe --setup again.",
                    "Smylte", MessageBoxButtons.OK, MessageBoxIcon.Information);
            }
            return;
        }

        var settings = Settings.Load();

        if (wantsSetup || !settings.IsConfigured)
        {
            using var setup = new SetupForm(settings);
            if (setup.ShowDialog() != DialogResult.OK) return;
            settings = setup.Result;
        }

        Application.Run(new MainForm(settings));
    }
}
