using System.Security.Cryptography;
using System.Text;

namespace Smylte.Desktop;

/// Encrypting the one sensitive field in settings.json, on whichever OS is
/// running.
///
/// **What DPAPI actually promises, and what this has to match.** `CurrentUser`
/// scope does not make the password unreadable by the user's own processes —
/// anything running as them can call Unprotect. What it gives is narrower and is
/// the whole of what desktop/README.md claims: *a copied settings.json is inert
/// on another account or machine*. That is the bar, and the Linux path clears
/// it by the same three facts, not by imitating the mechanism:
///
///   another machine   the key is derived from a random 32-byte file this
///                     client writes beside settings.json, and from
///                     /etc/machine-id when there is one. Copy the JSON and the
///                     blob is undecryptable; copy the whole directory to
///                     another machine and machine-id no longer matches.
///   another account   the key file is 0600 and the derivation is salted with
///                     the user name, so the same file under another account
///                     yields a different key even if it could be read.
///   a corrupt blob    every failure is an empty string, never a throw.
///
/// The last one is the load-bearing contract and the reason nothing here
/// reports errors: `Settings.GetPassword` returning "" makes the app show its
/// own login screen, which is a working client. Throwing would make a roamed
/// profile a dead one.
///
/// **What this deliberately is NOT.** It is not the login keyring. libsecret
/// would put the key behind the user's login credential, which is strictly
/// better against someone imaging the disk — and it is the natural next tier
/// here, behind this same two-method surface. It is not in yet because the
/// keyring path cannot be exercised by any test that runs in CI (there is no
/// session bus on a runner), and putting the untestable path on the primary
/// credential route is the wrong way round: this one is unit-tested, has no
/// daemon dependency, and works over SSH, on KDE, and on a minimal install.
internal static class PasswordProtector
{
    /// Marks a blob written by the derived-key path, so a reader can tell it
    /// from a DPAPI blob without guessing. Windows blobs stay bare base64
    /// exactly as they were written before this file existed — an installed
    /// client must keep reading its own settings.json across this change.
    private const string DerivedPrefix = "mk1:";

    private const string KeyFileName = "secret.key";

    /// Where the key file lives. A seam, so the tests do not write into the
    /// real ~/.config while they run.
    internal static Func<string> Directory = () => Settings.Dir;

    public static string Protect(string password)
    {
        if (string.IsNullOrEmpty(password)) return "";

        if (OperatingSystem.IsWindows())
            return Convert.ToBase64String(System.Security.Cryptography.ProtectedData.Protect(
                Encoding.UTF8.GetBytes(password), null, DataProtectionScope.CurrentUser));

        try
        {
            var key = DeriveKey(create: true);
            if (key is null) return "";

            // AES-256-GCM: 12-byte nonce, 16-byte tag, both by the book. Laid
            // out nonce ‖ tag ‖ ciphertext so the reader can slice it with two
            // constants rather than a length prefix it would have to trust.
            var nonce = RandomNumberGenerator.GetBytes(12);
            var plain = Encoding.UTF8.GetBytes(password);
            var cipher = new byte[plain.Length];
            var tag = new byte[16];
            using (var aes = new AesGcm(key, tag.Length))
                aes.Encrypt(nonce, plain, cipher, tag);

            var blob = new byte[nonce.Length + tag.Length + cipher.Length];
            nonce.CopyTo(blob, 0);
            tag.CopyTo(blob, nonce.Length);
            cipher.CopyTo(blob, nonce.Length + tag.Length);
            return DerivedPrefix + Convert.ToBase64String(blob);
        }
        catch (Exception)
        {
            // A read-only home, a full disk. Storing nothing is the honest
            // outcome: the app asks for the password at its own login screen.
            return "";
        }
    }

    public static string Unprotect(string blob)
    {
        if (string.IsNullOrEmpty(blob)) return "";
        try
        {
            if (!blob.StartsWith(DerivedPrefix, StringComparison.Ordinal))
            {
                // Bare base64: a DPAPI blob. Only Windows can read one, and a
                // settings.json carried to Linux legitimately lands here.
                if (!OperatingSystem.IsWindows()) return "";
                return Encoding.UTF8.GetString(System.Security.Cryptography.ProtectedData.Unprotect(
                    Convert.FromBase64String(blob), null, DataProtectionScope.CurrentUser));
            }

            // The key file is not created on the read path. Its absence is how a
            // settings.json copied without it stays inert, which is the property
            // this whole file exists to hold.
            var key = DeriveKey(create: false);
            if (key is null) return "";

            var bytes = Convert.FromBase64String(blob[DerivedPrefix.Length..]);
            if (bytes.Length < 12 + 16) return "";

            var nonce = bytes.AsSpan(0, 12);
            var tag = bytes.AsSpan(12, 16);
            var cipher = bytes.AsSpan(28);
            var plain = new byte[cipher.Length];
            using (var aes = new AesGcm(key, tag.Length))
                aes.Decrypt(nonce, cipher, tag, plain);
            return Encoding.UTF8.GetString(plain);
        }
        catch (Exception)
        {
            // Wrong machine, wrong account, a tampered blob, a truncated file.
            // All the same answer, and it is not an error: show the login screen.
            return "";
        }
    }

    /// The 32-byte AES key, or null when there is no key file and we are not
    /// allowed to make one.
    ///
    /// HKDF rather than a bare hash, because three inputs are being combined and
    /// two of them (machine-id, user name) are low-entropy and public. The
    /// random file is the actual secret; the other two only bind the key to a
    /// machine and an account.
    private static byte[]? DeriveKey(bool create)
    {
        var seed = ReadOrCreateSeed(create);
        if (seed is null) return null;

        var salt = Encoding.UTF8.GetBytes(MachineId());
        var info = Encoding.UTF8.GetBytes("smylte:password:v1:user=" + Environment.UserName);
        return HKDF.DeriveKey(HashAlgorithmName.SHA256, seed, 32, salt, info);
    }

    private static byte[]? ReadOrCreateSeed(bool create)
    {
        var path = Path.Combine(Directory(), KeyFileName);
        if (File.Exists(path))
        {
            var existing = File.ReadAllBytes(path);
            if (existing.Length == 32) return existing;
            if (!create) return null;         // truncated; only rewritten while saving
        }
        if (!create) return null;

        System.IO.Directory.CreateDirectory(Directory());
        var seed = RandomNumberGenerator.GetBytes(32);

        // Written 0600 BEFORE the bytes go in, not after: a key file that is
        // world-readable for even the width of one write is a key file that was
        // world-readable, and a `chmod` afterwards cannot close a window that
        // has already been open. Setting the mode on the handle is the only
        // ordering that never exposes it.
        //
        // The branch is not a tidiness choice — `FileStreamOptions.UnixCreateMode`
        // is annotated unsupported on Windows, so writing it unconditionally is
        // a platform warning in the Windows build even when the value is null.
        // Windows never reaches this code anyway (Protect took the DPAPI path
        // above), so the arm exists to compile cleanly rather than to run.
        if (OperatingSystem.IsWindows())
        {
            File.WriteAllBytes(path, seed);
        }
        else
        {
            using var stream = new FileStream(path, new FileStreamOptions
            {
                Mode = FileMode.Create,
                Access = FileAccess.Write,
                Share = FileShare.None,
                UnixCreateMode = UnixFileMode.UserRead | UnixFileMode.UserWrite,
            });
            stream.Write(seed);
        }
        return seed;
    }

    /// Binds the key to this machine, so a whole config directory carried to
    /// another one does not decrypt. Empty when the file is missing — a
    /// container, a BSD, a stripped image — which costs that one property and
    /// leaves the other two standing, rather than refusing to store anything.
    private static string MachineId()
    {
        foreach (var path in new[] { "/etc/machine-id", "/var/lib/dbus/machine-id" })
        {
            try
            {
                if (File.Exists(path)) return File.ReadAllText(path).Trim();
            }
            catch (Exception) { /* unreadable is the same as absent */ }
        }
        return "";
    }
}
