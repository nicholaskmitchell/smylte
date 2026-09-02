using System.IO.Compression;
using System.Reflection;
using Xunit;

namespace Smylte.Desktop.Tests;

/// The floors `app.ico` has to keep, asserted on the bytes the exe actually gets.
///
/// The icon is a committed binary with a hand-run generator
/// (`backend/dev/build_app_icon.py`) that CI deliberately never executes, so
/// nothing else in the build has an opinion about whether it is correct. Left
/// alone that is how the shipped file came to be four PNG frames with no alpha
/// channel at all, cut from an *iOS* asset, carrying a monogram that had been
/// realigned in the SVG a month earlier.
///
/// What makes it worth a test rather than a code review is that the failure is
/// silent from both ends. `System.Drawing.Icon` throws on a malformed directory
/// — but MainForm.cs and SetupForm.cs both wrap the load in a bare `catch`
/// because the icon is cosmetic, so a botched regeneration does not crash: the
/// window quietly falls back to the default WinForms icon while Explorer still
/// shows the stamped one. A split-brain icon is not something anyone notices in
/// a diff of a .ico.
///
/// This reads the bytes rather than the image. `System.Drawing.Common` throws
/// PlatformNotSupportedException off Windows on .NET 6+, and this project is
/// plain net8.0 on purpose so the suite runs anywhere — see the csproj comment.
/// An ICO directory is 6 bytes plus 16 per entry, and .NET has shipped
/// ZLibStream since 6.0, so the pixels are reachable without a decoder package
/// whose build targets would run on the runner.
public sealed class AppIconTests
{
    /// Microsoft's three request bands (title bar/tray, taskbar/Start list, Start
    /// pins) across 100-400% scaling, plus 128.
    ///
    /// 24 is the one to keep an eye on: it is the Windows 11 taskbar size at 100%
    /// scaling — the most visible surface there is — it is on Microsoft's stated
    /// bare-minimum list, and it was the one size missing from the old file.
    ///
    /// 128 is on no Microsoft list. `ICONDIRENTRY.bWidth` is a byte and 256 is
    /// encoded as 0, and `Icon.Initialize` scores candidates on that raw byte
    /// (|0 - requested|), so the 256 entry can never win at any requested size.
    /// Without a 128, ICON_BIG — Alt-Tab, Task Manager — caps at 96.
    private static readonly int[] Expected =
        [16, 20, 24, 30, 32, 36, 40, 48, 60, 64, 72, 80, 96, 128, 256];

    private static readonly byte[] Accent = [0xC7, 0x5A, 0x26];

    /// Every icon the exe carries, by resource name. `app.ico` is the one
    /// <ApplicationIcon> stamps into the PE and the only one Explorer, a pinned
    /// entry or a desktop shortcut can ever show; the other three are the
    /// alternates IconLibrary switches between at runtime. All four have to hold
    /// the same floors, because any of them can end up on the taskbar.
    public static TheoryData<string> Icons() =>
        new() { "app.ico", "icon-paper.ico", "icon-ink.ico", "icon-mark.ico" };

    private static byte[] Bytes(string name)
    {
        using var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream(name)
            ?? throw new InvalidOperationException($"{name} is not embedded in the test assembly");
        using var buffer = new MemoryStream();
        stream.CopyTo(buffer);
        return buffer.ToArray();
    }

    private readonly record struct Entry(int Size, int Planes, int BitCount, int Offset, int Length,
                                         byte ColorCount, byte Reserved, int RawHeight);

    private static List<Entry> Directory(byte[] ico)
    {
        Assert.Equal(0, BitConverter.ToUInt16(ico, 0));  // idReserved
        Assert.Equal(1, BitConverter.ToUInt16(ico, 2));  // idType: 1 = icon
        int count = BitConverter.ToUInt16(ico, 4);

        var entries = new List<Entry>();
        for (int i = 0; i < count; i++)
        {
            int at = 6 + 16 * i;
            entries.Add(new Entry(
                Size: ico[at] == 0 ? 256 : ico[at],
                Planes: BitConverter.ToUInt16(ico, at + 4),
                BitCount: BitConverter.ToUInt16(ico, at + 6),
                Offset: (int)BitConverter.ToUInt32(ico, at + 12),   // dwImageOffset, absolute
                Length: (int)BitConverter.ToUInt32(ico, at + 8),    // dwBytesInRes
                ColorCount: ico[at + 2],
                Reserved: ico[at + 3],
                RawHeight: ico[at + 1]));
        }
        return entries;
    }

    // ── the directory ──────────────────────────────────────────────────────

    [Theory, MemberData(nameof(Icons))]
    public void Every_size_Windows_asks_for_is_present_exactly_once(string icon)
    {
        var sizes = Directory(Bytes(icon)).Select(e => e.Size).ToList();
        Assert.Equal(Expected.Length, sizes.Count);
        Assert.Equal(Expected.Order(), sizes.Order());
    }

    [Theory, MemberData(nameof(Icons))]
    public void Entries_declare_themselves_as_square_32bpp_truecolour(string icon)
    {
        foreach (var e in Directory(Bytes(icon)))
        {
            // Roslyn only overrides wPlanes/wBitCount when the payload opens with
            // a 40-byte BITMAPINFOHEADER. A PNG payload does not, so whatever is
            // written here is copied verbatim into the exe's RT_GROUP_ICON. The
            // old file declared 24bpp on frames that had no alpha channel.
            Assert.Equal(1, e.Planes);
            Assert.Equal(32, e.BitCount);
            Assert.Equal(0, e.ColorCount);   // 0 = "not a palette"
            Assert.Equal(0, e.Reserved);
            Assert.Equal(e.Size == 256 ? 0 : e.Size, e.RawHeight);
        }
    }

    [Theory, MemberData(nameof(Icons))]
    public void Payloads_lie_inside_the_file_and_do_not_overlap(string icon)
    {
        var ico = Bytes(icon);
        int header = 6 + 16 * Directory(ico).Count;
        var spans = Directory(ico).OrderBy(e => e.Offset).ToList();

        foreach (var e in spans)
        {
            Assert.True(e.Offset >= header, $"{icon} {e.Size}px payload overlaps the directory");
            Assert.True(e.Offset + e.Length <= ico.Length, $"{icon} {e.Size}px payload runs off the end");
        }
        for (int i = 1; i < spans.Count; i++)
        {
            Assert.True(spans[i].Offset >= spans[i - 1].Offset + spans[i - 1].Length,
                $"{icon} {spans[i].Size}px payload overlaps {spans[i - 1].Size}px");
        }
    }

    // ── the payloads ───────────────────────────────────────────────────────

    [Theory, MemberData(nameof(Icons))]
    public void Every_frame_is_a_non_interlaced_8_bit_RGBA_PNG_of_the_declared_size(string icon)
    {
        var ico = Bytes(icon);
        foreach (var e in Directory(ico))
        {
            var png = ico.AsSpan(e.Offset, e.Length);
            Assert.True(png[..8].SequenceEqual<byte>([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]),
                $"{icon} {e.Size}px payload is not a PNG");

            // Roslyn trusts the directory and never cross-checks the payload, so
            // a mismatch here would ship an exe whose icon group lies about its
            // own contents.
            Assert.Equal(e.Size, ReadBigEndian(png, 16));
            Assert.Equal(e.Size, ReadBigEndian(png, 20));

            Assert.Equal(8, png[24]);   // bit depth
            Assert.Equal(6, png[25]);   // colour type 6 = RGBA. The whole point:
                                        // the old file was type 2, no alpha at all.
            Assert.Equal(0, png[28]);   // interlace
        }
    }

    // ── the pixels ─────────────────────────────────────────────────────────

    [Theory, MemberData(nameof(Icons))]
    public void The_mark_is_cut_out_rather_than_being_a_full_bleed_tile(string icon)
    {
        // Windows applies no mask, inset or rounding to a Win32 exe icon — what
        // the file holds is composited literally — so a fully opaque rectangle at
        // every size is the shape no other icon in the taskbar has, and is what
        // the icon this replaced was.
        //
        // Where the floor sits differs by design, and honestly so. The bare mark
        // is a silhouette, so every frame has a transparent ground. The plated
        // ones are tiles whose only transparency is the corner radius, and 12% of
        // 24px is under three pixels: below 32 the corner is smaller than the
        // antialiasing around it and no pixel comes out fully clear. Asserting
        // otherwise at 16px would be asserting something the geometry cannot do.
        var plated = icon != "icon-mark.ico";
        var ico = Bytes(icon);
        foreach (var e in Directory(ico))
        {
            if (plated && e.Size < 32) continue;
            var px = Decode(ico.AsSpan(e.Offset, e.Length).ToArray(), e.Size);
            var clear = 0;
            for (var i = 3; i < px.Length; i += 4)
            {
                if (px[i] == 0) clear++;
            }
            Assert.True(clear > 0, $"{icon} {e.Size}px frame is fully opaque");
        }
    }

    [Theory, MemberData(nameof(Icons))]
    public void The_accent_period_survives_at_every_size(string icon)
    {
        // The brand rule turned into a gate: the terminal period in --accent is
        // the signature, and a naive downscale of the 256px art smears it into a
        // grey blur long before 16px. Deliberately a distance test rather than an
        // exact match — a visually identical orange can land a channel off, and a
        // gate that fails on a good regeneration gets deleted rather than fixed.
        // True of all four for different reasons: the accent is the period on
        // the cream and ink plates, the plate itself on the accent one, and the
        // whole mark on the bare one.
        var ico = Bytes(icon);
        foreach (var e in Directory(ico))
        {
            var px = Decode(ico.AsSpan(e.Offset, e.Length).ToArray(), e.Size);
            bool found = false;
            for (int i = 0; i < px.Length && !found; i += 4)
            {
                if (px[i + 3] < 250) continue;
                int dr = px[i] - Accent[0], dg = px[i + 1] - Accent[1], db = px[i + 2] - Accent[2];
                found = dr * dr + dg * dg + db * db <= 100;   // Euclidean distance <= 10
            }
            Assert.True(found, $"{icon} {e.Size}px frame has no opaque pixel near #C75A26");
        }
    }

    [Theory, MemberData(nameof(Icons))]
    public void Nothing_is_pure_black_or_pure_white(string icon)
    {
        var ico = Bytes(icon);
        foreach (var e in Directory(ico))
        {
            var px = Decode(ico.AsSpan(e.Offset, e.Length).ToArray(), e.Size);
            for (int i = 0; i < px.Length; i += 4)
            {
                // Only pixels that are actually drawn. An antialiased edge at
                // alpha 1 is not artwork, and its RGB is whatever a 64-pixel box
                // average rounded a 14/255 channel down to — reading a brand rule
                // off those would fail on correct art for arithmetic reasons.
                if (px[i + 3] < 250) continue;
                bool black = px[i] == 0 && px[i + 1] == 0 && px[i + 2] == 0;
                bool white = px[i] == 255 && px[i + 1] == 255 && px[i + 2] == 255;
                Assert.False(black || white, $"{icon} {e.Size}px frame contains pure black or white");
            }
        }
    }

    // ── a minimal PNG reader, so the suite needs no image package ───────────

    private static int ReadBigEndian(ReadOnlySpan<byte> data, int at) =>
        (data[at] << 24) | (data[at + 1] << 16) | (data[at + 2] << 8) | data[at + 3];

    /// Inflate and un-filter one 8-bit RGBA PNG into raw pixels.
    ///
    /// Narrow on purpose: it handles what `build_app_icon.py` emits and what
    /// `Every_frame_is_a_non_interlaced_8_bit_RGBA_PNG_of_the_declared_size`
    /// has already asserted, and nothing else.
    private static byte[] Decode(byte[] png, int size)
    {
        var idat = new MemoryStream();
        int at = 8;
        while (at < png.Length)
        {
            int length = ReadBigEndian(png, at);
            string type = System.Text.Encoding.ASCII.GetString(png, at + 4, 4);
            if (type == "IDAT") idat.Write(png, at + 8, length);
            if (type == "IEND") break;
            at += 12 + length;   // length + type + data + CRC
        }

        idat.Position = 0;
        using var inflate = new ZLibStream(idat, CompressionMode.Decompress);
        using var raw = new MemoryStream();
        inflate.CopyTo(raw);
        var scanlines = raw.ToArray();

        const int Bpp = 4;
        int stride = size * Bpp;
        var outp = new byte[stride * size];
        for (int y = 0; y < size; y++)
        {
            int filter = scanlines[y * (stride + 1)];
            int src = y * (stride + 1) + 1;
            int dst = y * stride;
            for (int x = 0; x < stride; x++)
            {
                int a = x >= Bpp ? outp[dst + x - Bpp] : 0;       // left
                int b = y > 0 ? outp[dst - stride + x] : 0;       // up
                int c = x >= Bpp && y > 0 ? outp[dst - stride + x - Bpp] : 0;  // up-left
                int value = filter switch
                {
                    0 => scanlines[src + x],
                    1 => scanlines[src + x] + a,
                    2 => scanlines[src + x] + b,
                    3 => scanlines[src + x] + (a + b) / 2,
                    4 => scanlines[src + x] + Paeth(a, b, c),
                    _ => throw new InvalidOperationException($"unknown PNG filter {filter}"),
                };
                outp[dst + x] = (byte)value;
            }
        }
        return outp;
    }

    private static int Paeth(int a, int b, int c)
    {
        int p = a + b - c;
        int pa = Math.Abs(p - a), pb = Math.Abs(p - b), pc = Math.Abs(p - c);
        return pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
    }
}
