using System.Text;
using Smylte.Desktop;
using Xunit;

namespace Smylte.Desktop.Tests;

/// The password at rest.
///
/// What is asserted here is the derived-key path, which is what runs on Linux.
/// The DPAPI path is asserted only where it can be: this suite runs on both
/// runners, so the Windows leg takes the DPAPI branch and the Linux leg takes
/// the other, and the two branches share only the contract — which is the thing
/// worth pinning either way.
///
/// **That contract is "never throw".** `Settings.GetPassword` returning an empty
/// string is not an error path; it is how a settings.json carried to another
/// machine ends up at the app's own login screen instead of at a crash. Half the
/// cases below are failures, and all of them assert "" rather than an exception.
public sealed class PasswordProtectorTests : IDisposable
{
    private readonly string _dir = Directory.CreateTempSubdirectory("smylte-key").FullName;
    private readonly Func<string> _restore;

    public PasswordProtectorTests()
    {
        // The seam exists so the suite never writes a key file into the real
        // ~/.config while it runs — and so a second "machine" can be simulated
        // below by pointing at a different directory.
        _restore = PasswordProtector.Directory;
        PasswordProtector.Directory = () => _dir;
    }

    public void Dispose()
    {
        PasswordProtector.Directory = _restore;
        try { Directory.Delete(_dir, recursive: true); } catch (IOException) { }
    }

    [Fact]
    public void A_password_survives_a_round_trip()
    {
        const string secret = "correct horse battery staple";
        Assert.Equal(secret, PasswordProtector.Unprotect(PasswordProtector.Protect(secret)));
    }

    [Fact]
    public void A_password_with_non_ascii_survives_a_round_trip()
    {
        // UTF-8 both ways, and the field goes through JSON on the way to disk.
        const string secret = "Ünicøde — 🔑 — paßwort";
        Assert.Equal(secret, PasswordProtector.Unprotect(PasswordProtector.Protect(secret)));
    }

    [Fact]
    public void An_empty_password_stores_nothing()
    {
        Assert.Equal("", PasswordProtector.Protect(""));
        Assert.Equal("", PasswordProtector.Unprotect(""));
    }

    [Fact]
    public void The_stored_blob_does_not_contain_the_password()
    {
        // The point of the whole file, and the one assertion that would catch
        // the worst possible regression here — a "simplification" to base64.
        const string secret = "hunter2-and-a-bit-more";
        var blob = PasswordProtector.Protect(secret);
        Assert.DoesNotContain(secret, blob, StringComparison.Ordinal);
        Assert.DoesNotContain(Convert.ToBase64String(Encoding.UTF8.GetBytes(secret)), blob,
            StringComparison.Ordinal);
    }

    [Fact]
    public void A_blob_copied_without_the_key_file_does_not_decrypt()
    {
        if (OperatingSystem.IsWindows()) return;   // DPAPI's own scoping covers this

        var blob = PasswordProtector.Protect("something worth taking");

        // Exactly the "roamed settings.json" case: the JSON travelled, the 0600
        // key file beside it did not. This is the property desktop/README.md
        // promises, so it is asserted rather than described.
        var elsewhere = Directory.CreateTempSubdirectory("smylte-other").FullName;
        try
        {
            PasswordProtector.Directory = () => elsewhere;
            Assert.Equal("", PasswordProtector.Unprotect(blob));
        }
        finally
        {
            PasswordProtector.Directory = () => _dir;
            try { Directory.Delete(elsewhere, recursive: true); } catch (IOException) { }
        }
    }

    [Fact]
    public void A_blob_from_a_different_key_file_does_not_decrypt()
    {
        if (OperatingSystem.IsWindows()) return;

        var blob = PasswordProtector.Protect("something worth taking");

        // The other half: a key file exists, but it is not the one that wrote
        // the blob. GCM's tag makes this a clean failure rather than garbage.
        File.WriteAllBytes(Path.Combine(_dir, "secret.key"),
            System.Security.Cryptography.RandomNumberGenerator.GetBytes(32));
        Assert.Equal("", PasswordProtector.Unprotect(blob));
    }

    [Fact]
    public void A_tampered_blob_does_not_decrypt()
    {
        if (OperatingSystem.IsWindows()) return;

        var blob = PasswordProtector.Protect("something worth taking");
        var prefix = blob[..4];
        var bytes = Convert.FromBase64String(blob[4..]);
        bytes[^1] ^= 0xFF;                        // flip a ciphertext bit
        Assert.Equal("", PasswordProtector.Unprotect(prefix + Convert.ToBase64String(bytes)));
    }

    [Theory]
    [InlineData("mk1:not base64 at all")]
    [InlineData("mk1:")]
    [InlineData("mk1:AAAA")]                      // valid base64, far too short
    [InlineData("garbage")]
    [InlineData("!!!")]
    public void An_unreadable_blob_is_an_empty_password_not_an_exception(string blob)
    {
        Assert.Equal("", PasswordProtector.Unprotect(blob));
    }

    [Fact]
    public void A_windows_blob_read_on_linux_is_an_empty_password()
    {
        if (OperatingSystem.IsWindows()) return;

        // A bare base64 blob is DPAPI's shape. Carrying settings.json from a
        // Windows machine to a Linux one is a thing people do, and it must land
        // on the login screen rather than on a PlatformNotSupportedException.
        Assert.Equal("", PasswordProtector.Unprotect(
            Convert.ToBase64String(new byte[] { 1, 0, 0, 0, 0xD0, 0x8C, 0x9D, 0xDF })));
    }

    [Fact]
    public void The_key_file_is_not_readable_by_anyone_else()
    {
        if (OperatingSystem.IsWindows()) return;

        PasswordProtector.Protect("anything");
        var mode = File.GetUnixFileMode(Path.Combine(_dir, "secret.key"));

        // 0600. The group and other bits are the assertion — the key file is
        // the whole secret, and a umask that left it 0644 would quietly undo
        // the "another account on this machine" half of the guarantee.
        Assert.Equal(UnixFileMode.UserRead | UnixFileMode.UserWrite, mode);
    }

    [Fact]
    public void Two_passwords_encrypted_in_a_row_produce_different_blobs()
    {
        // A fresh nonce every time. Identical blobs would leak that the password
        // had not changed between two saves, and would mean the nonce was fixed
        // — which for GCM is not a leak but a break.
        const string secret = "the same password twice";
        Assert.NotEqual(PasswordProtector.Protect(secret), PasswordProtector.Protect(secret));
    }
}
