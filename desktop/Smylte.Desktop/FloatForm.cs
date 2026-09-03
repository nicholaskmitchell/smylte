using System.Runtime.InteropServices;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace Smylte.Desktop;

/// The floating focus window: a second WebView2 on the same local origin,
/// frameless, above other windows, moved by its own page and resized from a
/// six-pixel ring of the form around it.
///
/// It is not a second app. The page it shows is `/focus?float=1` — the same
/// focus surface the main window can show, told by the query string that it is
/// the small one — served by the same LocalServer, in the same WebView2
/// profile, with the same session cookie. The session it paints is the
/// server's, so this window and the main one agree to the second, and either
/// may be closed without the other losing anything.
///
/// Three Win32 facts shape it, and each is the reason for a block below:
///
///   * A window with no frame has no caption to drag and no border to resize.
///     The drag is the page's: WebView2 ≥ 123 honours `app-region: drag` when
///     `IsNonClientRegionSupportEnabled` is on, answering WM_NCHITTEST with
///     HTCAPTION itself so Windows moves the window natively; for a runtime
///     that cannot, the page asks the bridge and `BeginDrag` posts the same
///     message. The resize is the form's: the ring of `Padding` around the
///     docked WebView2 is form client area, and WndProc answers WM_NCHITTEST
///     over it with the eight edge codes, which DefWindowProc turns into the
///     ordinary size loop.
///   * It has no Owner, on purpose. An owned window hides with its owner, and
///     the main window minimises the moment this one opens.
///   * WinForms keeps a `ShowInTaskbar = false` top-level form out of the
///     taskbar by parenting it to a hidden tool window rather than by making
///     it one, which is why it stays reachable through Alt-Tab.
public sealed class FloatForm : Form
{
    /// Opening size and floor, in logical pixels; scaled by the DPI of the
    /// monitor the window is created on. The floor is where the compact face
    /// stops fitting with a one-line title (frontend/src/styles/app.css, the
    /// `.focus[data-float]` block, has the arithmetic).
    private const int DefaultWidth = 420;
    private const int DefaultHeight = 280;
    private const int MinWidth = 320;
    private const int MinHeight = 200;
    private const int Ring = 6;

    private const int WmNcHitTest = 0x0084;
    private const int WmNcLButtonDown = 0x00A1;
    private const int WmEnterSizeMove = 0x0231;
    private const int WmExitSizeMove = 0x0232;
    private const int HtClient = 1;
    private const int HtCaption = 2;
    private const int HtLeft = 10;
    private const int HtRight = 11;
    private const int HtTop = 12;
    private const int HtTopLeft = 13;
    private const int HtTopRight = 14;
    private const int HtBottom = 15;
    private const int HtBottomLeft = 16;
    private const int HtBottomRight = 17;
    private const int CsDropShadow = 0x00020000;

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool ReleaseCapture();

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool PostMessage(IntPtr hWnd, int msg, IntPtr wParam, IntPtr lParam);

    private readonly Settings _settings;
    private readonly CoreWebView2Environment _environment;
    private readonly string _url;
    private readonly Action<bool> _nativeDragReady;
    private readonly WebView2 _web = new() { Dock = DockStyle.Fill };
    private bool _inSizeMove;

    /// `environment` is the main window's own, shared rather than re-created:
    /// two views on one environment share the browser process, the profile and
    /// so the seeded session cookie — and a second CreateAsync on the same user
    /// data folder with different options is refused anyway. `nativeDragReady`
    /// reports whether the runtime took `IsNonClientRegionSupportEnabled`, so
    /// State() can tell the page which way to drag.
    public FloatForm(
        Settings settings, CoreWebView2Environment environment, string url,
        Action<bool> nativeDragReady)
    {
        _settings = settings;
        _environment = environment;
        _url = url;
        _nativeDragReady = nativeDragReady;

        Text = "Smylte — Focus";
        FormBorderStyle = FormBorderStyle.None;
        ShowInTaskbar = false;
        // No WS_MAXIMIZEBOX: a double-click on a caption region maximises a
        // window that has one, and a floating clock the size of the screen is
        // not a state anyone asked for.
        MaximizeBox = false;
        MinimizeBox = false;
        StartPosition = FormStartPosition.Manual;
        TopMost = settings.FloatPinned;
        AutoScaleMode = AutoScaleMode.Font;
        try { Icon = IconLibrary.Load(IconLibrary.Parse(settings.IconChoice)) ?? Icon; }
        catch (Exception) { /* cosmetic */ }

        Controls.Add(_web);
        Load += async (_, _) => await InitialiseAsync().ConfigureAwait(true);
    }

    /// A drop shadow, so a frameless window reads as a window rather than as a
    /// rectangle painted on the desktop.
    protected override CreateParams CreateParams
    {
        get
        {
            var cp = base.CreateParams;
            cp.ClassStyle |= CsDropShadow;
            return cp;
        }
    }

    // ── shape ────────────────────────────────────────────────────────────────

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        // The ring is form client area the docked WebView2 does not cover — the
        // frame, drawn by OnPaint and hit-tested by WndProc. Logical units, so
        // it is six pixels on every monitor.
        Padding = new Padding(LogicalToDeviceUnits(Ring));
        MinimumSize = new Size(LogicalToDeviceUnits(MinWidth), LogicalToDeviceUnits(MinHeight));
        Place();
        ApplyChrome(_settings.TitleBarColor);
    }

    protected override void OnDpiChanged(DpiChangedEventArgs e)
    {
        base.OnDpiChanged(e);
        Padding = new Padding(LogicalToDeviceUnits(Ring));
        MinimumSize = new Size(LogicalToDeviceUnits(MinWidth), LogicalToDeviceUnits(MinHeight));
    }

    /// Where the window opens: where it was last, if that is still on a screen;
    /// otherwise the bottom-right of the primary working area.
    private void Place()
    {
        var saved = new Rectangle(
            _settings.FloatX, _settings.FloatY, _settings.FloatWidth, _settings.FloatHeight);
        if (saved.Width > 0 && saved.Height > 0)
        {
            // Recorded on a monitor at another scale: keep the size the owner
            // chose rather than the pixel count, which would be a different size.
            if (_settings.FloatDpi > 0 && _settings.FloatDpi != DeviceDpi)
            {
                var factor = DeviceDpi / (double)_settings.FloatDpi;
                saved.Width = (int)Math.Round(saved.Width * factor);
                saved.Height = (int)Math.Round(saved.Height * factor);
            }
            foreach (var screen in Screen.AllScreens)
            {
                var overlap = Rectangle.Intersect(saved, screen.WorkingArea);
                if (overlap.Width >= 40 && overlap.Height >= 40)
                {
                    Bounds = saved;
                    return;
                }
            }
        }
        var area = Screen.PrimaryScreen?.WorkingArea ?? new Rectangle(0, 0, 1280, 800);
        var inset = LogicalToDeviceUnits(24);
        var size = new Size(LogicalToDeviceUnits(DefaultWidth), LogicalToDeviceUnits(DefaultHeight));
        Bounds = new Rectangle(
            area.Right - inset - size.Width, area.Bottom - inset - size.Height,
            size.Width, size.Height);
    }

    /// Written after a move or a resize (WinForms raises ResizeEnd for both,
    /// on WM_EXITSIZEMOVE) and on close. Never per pixel.
    private void Remember()
    {
        if (!IsHandleCreated || WindowState != FormWindowState.Normal) return;
        _settings.FloatX = Bounds.X;
        _settings.FloatY = Bounds.Y;
        _settings.FloatWidth = Bounds.Width;
        _settings.FloatHeight = Bounds.Height;
        _settings.FloatDpi = DeviceDpi;
        try { _settings.Save(); } catch (Exception) { /* not worth blocking a move */ }
    }

    protected override void OnResizeEnd(EventArgs e)
    {
        base.OnResizeEnd(e);
        Remember();
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        Remember();
        base.OnFormClosing(e);
    }

    /// The ring's colour follows the app's own --bg, the same value the main
    /// window's caption is painted with; a theme change reaches here through
    /// the same bridge call.
    public void ApplyChrome(string? background)
    {
        var colour = WindowChrome.ParseHex(background);
        BackColor = colour ?? SystemColors.Window;
        try
        {
            if (colour is null) WindowChrome.Reset(Handle);
            else WindowChrome.Apply(Handle, colour.Value);
        }
        catch (Exception) { /* cosmetic */ }
        Invalidate();
    }

    /// One hairline inside the ring, a step off the background either way, so
    /// the window has an edge on a desktop the same colour as itself.
    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        var edge = BackColor.GetBrightness() < 0.5f
            ? ControlPaint.Light(BackColor, 0.35f)
            : ControlPaint.Dark(BackColor, 0.15f);
        using var pen = new Pen(edge);
        var r = ClientRectangle;
        r.Width -= 1;
        r.Height -= 1;
        e.Graphics.DrawRectangle(pen, r);
    }

    // ── moving and resizing ──────────────────────────────────────────────────

    protected override void WndProc(ref Message m)
    {
        switch (m.Msg)
        {
            case WmNcHitTest:
                base.WndProc(ref m);
                if ((int)m.Result == HtClient)
                {
                    var l = m.LParam.ToInt64();
                    var point = PointToClient(new Point(
                        unchecked((short)(l & 0xFFFF)), unchecked((short)((l >> 16) & 0xFFFF))));
                    var hit = HitRing(point);
                    if (hit != HtClient) m.Result = (IntPtr)hit;
                }
                return;
            case WmEnterSizeMove:
                _inSizeMove = true;
                break;
            case WmExitSizeMove:
                _inSizeMove = false;
                break;
        }
        base.WndProc(ref m);
    }

    /// Which edge or corner of the ring a client point is on, or HTCLIENT. The
    /// inner rectangle is `DisplayRectangle` — the client area minus the
    /// padding — so the answer is right at any DPI without a second constant.
    /// Corners take three rings' width so they can actually be grabbed.
    private int HitRing(Point p)
    {
        var inner = DisplayRectangle;
        if (!ClientRectangle.Contains(p) || inner.Contains(p)) return HtClient;
        var corner = Padding.Left * 3;
        var left = p.X < inner.Left + corner;
        var right = p.X >= inner.Right - corner;
        var top = p.Y < inner.Top + corner;
        var bottom = p.Y >= inner.Bottom - corner;
        var onLeft = p.X < inner.Left;
        var onRight = p.X >= inner.Right;
        var onTop = p.Y < inner.Top;
        var onBottom = p.Y >= inner.Bottom;
        if (onTop || onBottom)
        {
            if (left) return onTop ? HtTopLeft : HtBottomLeft;
            if (right) return onTop ? HtTopRight : HtBottomRight;
            return onTop ? HtTop : HtBottom;
        }
        if (onLeft)
        {
            if (top) return HtTopLeft;
            if (bottom) return HtBottomLeft;
            return HtLeft;
        }
        if (onRight)
        {
            if (top) return HtTopRight;
            if (bottom) return HtBottomRight;
            return HtRight;
        }
        return HtClient;
    }

    /// The fallback drag, for a runtime that cannot do `app-region: drag`. Only
    /// while the button is still down: the move loop that WM_NCLBUTTONDOWN
    /// enters exits at once otherwise, and the page's press is a few
    /// milliseconds old by the time this runs. PostMessage rather than
    /// SendMessage — the bridge call arrives from the listener thread, and a
    /// SendMessage would sit inside the modal move loop for the whole drag.
    public void BeginDrag()
    {
        if (!IsHandleCreated || _inSizeMove) return;
        if ((MouseButtons & MouseButtons.Left) == 0) return;
        ReleaseCapture();
        PostMessage(Handle, WmNcLButtonDown, (IntPtr)HtCaption, IntPtr.Zero);
    }

    // ── the page ─────────────────────────────────────────────────────────────

    private async Task InitialiseAsync()
    {
        try
        {
            await _web.EnsureCoreWebView2Async(_environment).ConfigureAwait(true);
            var core = _web.CoreWebView2;
            var settings = core.Settings;
            settings.IsStatusBarEnabled = false;
            // Ctrl+wheel would wreck a face fitted to the window.
            settings.IsZoomControlEnabled = false;
            settings.AreDefaultContextMenusEnabled = false;

            // The page marks its body `app-region: drag`, and with this on the
            // runtime answers the hit-test itself and Windows moves the window.
            // A runtime older than 123 has no such setting and the setter
            // throws; the page is told, and drags through the bridge instead.
            var native = false;
            try
            {
                settings.IsNonClientRegionSupportEnabled = _settings.FloatNativeDrag;
                native = _settings.FloatNativeDrag;
            }
            catch (Exception) { /* older runtime: BeginDrag is the way */ }
            _nativeDragReady(native);

            // Unhandled, a page's request to notify is refused. The focus surface
            // asks only from a click and only with the setting on.
            core.PermissionRequested += (_, e) =>
            {
                if (e.PermissionKind == CoreWebView2PermissionKind.Notifications)
                    e.State = CoreWebView2PermissionState.Allow;
            };
            // Alt-Tab shows the countdown: the page keeps its title current.
            core.DocumentTitleChanged += (_, _) => Text = core.DocumentTitle;

            core.Navigate(_url);
        }
        catch (Exception)
        {
            // A window that cannot show its page is not worth keeping; closing
            // hands the main window back, through the same path Dock takes.
            Close();
        }
    }
}
