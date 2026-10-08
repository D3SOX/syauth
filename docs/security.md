# syauth security model

syauth lets a bonded Android phone approve Linux PAM authentication over
Bluetooth. The desktop sends a fresh challenge; the phone signs it only after
strong biometric authentication. The desktop verifies the response before PAM
accepts it. No cloud service is involved.

For the tested Arch/KDE configuration, see [installation](getting-started.md)
and [PAM setup](pam.md). The detailed threat audit is in
[`specs/threat/THREAT-2026-05-15.md`](../specs/threat/THREAT-2026-05-15.md).
Some audit entries describe earlier implementations; the current setup and
approval behavior are documented below.

## What phone approval provides

You do not type a laptop password during a successful phone approval, so that
attempt exposes no typed password to shoulder surfing or keyboard capture.
Someone using your unlocked terminal still needs approval on your bonded phone.

The phone's Ed25519 signing key stays in Android Keystore. Each signing operation
uses `BiometricPrompt.CryptoObject` with `AUTH_BIOMETRIC_STRONG` and a zero-second
authentication window. Unlocking the phone or knowing its PIN does not satisfy
this per-operation biometric requirement. There is no phone PIN/password fallback.

The fingerprint prompt opens automatically for a verified request. Opening it
or dismissing it does not authenticate. Dismissal returns to Authorize/Disallow;
Authorize retries the biometric operation, and Disallow rejects the request.

Fresh nonces, bond-key MAC verification, response signature verification, and
replay checks prevent a captured response from approving a different request.
Pairing requires both the six-digit system Bluetooth comparison and the separate
four-word app confirmation.

## Limits

syauth does not measure distance. A Bluetooth relay can forward a request to the
real bonded phone. The biometric requirement prevents approval without user
interaction, but it cannot distinguish a coerced or mistakenly approved request.
Check the displayed desktop name before scanning your fingerprint.

Root access on the desktop can change PAM or bypass authentication. A compromised
phone OS, compromised Keystore implementation, or biometric spoofing can also
undermine the approval requirement. syauth does not protect against Bluetooth
jamming or guarantee service availability.

The app first requests StrongBox for the Ed25519 key and falls back to the
regular Keystore when StrongBox is unavailable or rejects the curve. Do not assume
that a StrongBox-capable phone stores this particular key in StrongBox. Production
pairing requires Android 13/API 33 or newer with Keystore Ed25519 support.

The phone bond file stores the Keystore alias, public key, and shared bond MAC
key. It does not store the private signing key. The tested desktop setup uses
user-owned storage under `/var/lib/syauth`, with restricted file and directory
permissions. These locations and the shared MAC key should not be confused with
the non-exportable phone signing key.

## Password fallback and cancellation

The tested sudo configuration uses `auth sufficient pam_syauth.so` before the
existing auth stack. Phone absence or denial leaves that stack available. KDE
runs phone approval through its parallel `kde-fingerprint` service while its
normal `kde` password service remains available. Preserve the existing mandatory
checks and verify password fallback before relying on either setup.

When the PAM caller disconnects or the daemon deadline expires, the daemon sends
a bond-key-authenticated cancellation for the matching peer and nonce. Android
closes that approval and ignores late biometric callbacks. Cancellation cannot
grant authentication. BLE delivery is best effort, so a lost notification can
leave a stale phone dialog after the desktop request has ended. See
[approval cancellation](cancellation.md) and its
[threat model](../specs/threat/THREAT-2026-10-08-cancellation.md).

## Operating the setup

Keep Android and the desktop updated. Review bonds with `syauth list` and revoke
unrecognized or retired peers with `syauth revoke`. Compare both pairing
confirmations in a setting where you can identify the intended devices.

Keep the documented PAM backups and rollback procedure available. Test with the
phone unavailable and with a declined request. Disable USB debugging when you no
longer need it for development.

The relevant implementation is in `crates/syauth-core` for framing, MACs,
signatures, and replay checks; `crates/syauth-presenced` for challenge handling;
`crates/syauth-pam` for PAM results; and `syauth-android/app/src/main/kotlin` for
Keystore signing and approval lifecycle.
