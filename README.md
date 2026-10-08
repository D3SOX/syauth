# syauth

Authenticate `sudo`, `login`, `gdm`, `swaylock`, or KDE screen unlock with
your Android phone's fingerprint sensor. syauth works over Bluetooth without a
cloud service. When the phone is unavailable, PAM continues to your configured
password or FIDO2 authentication.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Rust](https://img.shields.io/badge/rust-2024-orange)](Cargo.toml)
[![Platform](https://img.shields.io/badge/platform-Linux%20%2B%20Android-lightgrey)](#)
[![Status](https://img.shields.io/badge/status-v0.1%20RC-yellow)](specs/syauth/ROADMAP.md)

---

## Why

Bluetooth proximity alone can be relayed. syauth requires fresh biometric
authentication on the bonded phone for each request.

- The phone signs a random challenge nonce with Ed25519. The desktop verifies
  the response against the public key pinned during pairing.
- Android Keystore holds the signing key with
  `setUserAuthenticationRequired(true)`. An unlocked phone still requires a
  fresh biometric before signing.
- The PAM module uses `sufficient`, so an unavailable phone leaves the remaining
  authentication stack available. The default installer can add FIDO2; the
  Arch/KDE guide preserves existing password and fingerprint authentication.

The fingerprint prompt opens automatically when the phone receives a request.
Dismissing it returns to the
Authorize/Disallow screen. Authorize retries biometrics; Disallow declines.

---

## How it works

```
┌─────────────────┐                 BLE/LESC                 ┌──────────────────┐
│  Linux desktop  │                                          │  Android phone   │
│                 │                                          │                  │
│  pam_syauth.so  │ ── challenge (nonce, MAC) ─────────────► │  approve screen  │
│       │         │                                          │        │         │
│       ▼         │                                          │        ▼         │
│ syauth-presenced│ ◄──── response (Ed25519 signature) ───── │  BiometricPrompt │
│   (user daemon) │                                          │ + Keystore sign  │
└─────────────────┘                                          └──────────────────┘
        │                                                              ▲
        │            verify(VerifyingKey, body, signature)             │
        └──────────────────────────────────────────────────────────────┘
                       (32-byte Ed25519 public key,
                        pinned at pair time via LESC
                        + 4-word app-level OOB confirm)
```

- The desktop advertises a rotating session UUID derived from
  `BLAKE3(bond_key || current_minute)`. The phone observes presence
  via `CompanionDeviceManager` and opens a GATT client with
  `autoConnect=true`.
- Pairing requires BLE LE Secure Connections numeric comparison of the six-digit
  code and a separate four-word app confirmation. The app confirmation also
  checks the bond if an attacker bypasses system pairing.
- The phone creates its Ed25519 private key in Keystore during pairing.
  `BiometricPrompt` authorizes each `sign()` operation.

---

## Quick start

For the tested Arch Linux / KDE Plasma / Pixel setup, follow:

1. [Build, install, and pair](docs/getting-started.md), including the native
   Android AAR, systemd runtime permissions, and phone-only Bluetooth recovery.
2. [Enable sudo and KDE screen unlock](docs/pam.md), including backups, tests,
   password fallback, and rollback.

Pair with `syauth pair --timeout-secs 300` while the presence daemon is stopped.
Compare both the six-digit system Bluetooth code and the four-word app phrase.
Tapping Done on the phone updates Home and starts its connection service without
restarting the app. Then enable the desktop daemon.

KDE can request the phone when you press Enter with an empty password field,
using the optional `on_empty_password` PAM argument. Typing a password uses
normal password authentication. For automatic requests with simultaneous
password unlock, use the parallel `kde-fingerprint` service instead. Both
configurations are in the [PAM guide](docs/pam.md).

The generic `install-pam` / `uninstall-pam` commands remain available for other
PAM services. Review their output and the target distro's module paths before
applying it; the per-user socket and KDE stack need the explicit setup
above. The tested Arch module path is `/usr/lib/security/pam_syauth.so`.

## Bluetooth recovery

On restart the daemon can disconnect and reconnect one explicitly configured
phone to recover a stale GATT subscription. Set `SYAUTH_RECONNECT_DEVICE` to that
phone's bonded BlueZ identity address; when unset it disconnects no devices.
Headphones and other Bluetooth devices remain connected. The phone refreshes its
GATT cache on connection before discovering services. See
[Bluetooth configuration](docs/bluetooth.md).

---

## What's where

```
syauth/
├── crates/
│   ├── syauth-core/           # Wire format, BLAKE3 MAC, OOB derivation, fuzz harness
│   ├── syauth-transport/      # bluer GATT peripheral + advertisement rotation
│   ├── syauth-pam/            # pam_syauth.so — auth-stack entry point
│   ├── syauth-cli/            # syauth(1): pair / list / revoke / status / install-pam / doctor
│   ├── syauth-presenced/      # Long-running user daemon (systemd --user unit)
│   └── syauth-mobile/         # UniFFI bindings consumed by the Android app
├── syauth-android/            # Kotlin app (Compose UI, Keystore signing, CDM presence)
├── specs/
│   ├── syauth/SPEC.md         # Protocol, wire format, install layout
│   ├── syauth/ROADMAP.md      # Items S-001..S-019 + JOURNEY closures
│   └── threat/                # Formal threat model (T-001..T-016)
├── docs/                      # Setup guides, security overview, known gaps
└── scripts/                   # e2e-unlock.sh latency benchmark, build helpers
```

---

## Configuration cheatsheet

```sh
# Daemon
systemctl --user status syauth-presenced
journalctl --user -u syauth-presenced -f
syauth status                     # adapter + bonded peers + last unlock
syauth status --json              # same data, machine-readable

# Bonds
syauth list                       # TSV: id, name, status, created_at
syauth revoke --id <peer_id>      # idempotent; audit trail preserved
syauth pair --force               # overwrite an existing bond record

# Health
syauth doctor                     # one OK/WARN/FAIL line per probe
syauth doctor --json              # typed JSON for tooling
```

Environment overrides for the daemon are in the systemd unit
(`~/.config/systemd/user/syauth-presenced.service`); see
`docs/known-gaps.md` for an audit-trail of every spec deviation.

---

## Security model

A formal threat model lives in
[`specs/threat/THREAT-2026-05-15.md`](specs/threat/THREAT-2026-05-15.md);
the short version:

- T-001..T-006 (link-layer attacks): covered by LESC + per-unlock
  signing.
- T-007 (compromised phone): bound by the Keystore's
  `setUserAuthenticationRequired(true)`, a stolen unlocked phone
  cannot sign without a fresh biometric.
- T-014 (biometric coercion / phishing prompt): hostname is
  sanitized + truncated on the Approve screen so a malicious peer
  can't render a multi-line phishing prompt.
- T-016 (compromised desktop): in scope for v0.2; v0.1 trusts
  the desktop's `bond_key`.

If the phone is unavailable, `pam_syauth` returns `PAM_AUTHINFO_UNAVAIL`
and PAM continues to the configured FIDO2 or password modules. A failed
phone response does not grant authentication.

---

## Roadmap

- v0.1.0 (RC, current), five auth surfaces (sudo, login, su,
  gdm-password, swaylock), real-device LESC, Keystore-resident
  Ed25519, FIDO2 fallback installed in one CLI command.
- v0.2, F-Droid + Play Store delivery, multi-host bonds,
  bond-revocation push from desktop, daemon presence on the system
  bus.
- v0.3, pre-boot unlock (LUKS/cryptsetup), CompanionDeviceService
  in-process re-discovery so the daemon kick is no longer needed.

Tracking is in
[`specs/syauth/ROADMAP.md`](specs/syauth/ROADMAP.md). Sibling
roadmap for the `sy` desktop integration is at
[`~/sources/sy/specs/roadmaps/syauth-integration/ROADMAP.md`](https://github.com/dmytrogajewski/sy/blob/master/specs/roadmaps/syauth-integration/ROADMAP.md).

---

## Contributing

PRs welcome. Run the checks below and document user-visible behavior:

- `cargo clippy --all-targets -- -D warnings` must pass.
- Every new module ships with tests before behaviour.
- No `TODO` / `FIXME` / `unimplemented!()` in committed code, the
  pre-commit hook blocks it.
- Open SPEC deviations live in
  [`docs/known-gaps.md`](docs/known-gaps.md) with a numbered
  `DEV-NNN` audit row.

---

## License

[MIT](LICENSE). Copyright © 2026 syauth contributors.
