# Android companion setup

Use the [tested Arch/KDE installation guide](getting-started.md) for toolchain,
APK installation, pairing, and desktop service setup. The Gradle app consumes a
native AAR and generated Kotlin bindings; build these before `assembleDebug`.
The guide includes the UniFFI CLI wrapper needed with version 0.29.5.

## Permissions and device requirements

Open the app and allow Bluetooth/Nearby devices and notifications. Pairing uses
Android's CompanionDeviceManager picker for discovery; the app then uses
`BLUETOOTH_CONNECT` for bonding and its GATT connection. Enroll a strong biometric
before attempting authentication.

The Gradle minimum SDK is 26, but the production Keystore Ed25519 generator
requires Android 13/API 33 or newer and device support for that algorithm. Do not
interpret the APK's minimum SDK as proof that older phones can complete pairing.
The tested device was a Pixel 8 Pro on Android 16.

## Key storage and approval

The current pairing flow creates an Ed25519 signing key in AndroidKeyStore.
It first requests StrongBox, then retries without StrongBox when the hardware
reports it unavailable or rejects that curve. The bond file holds the Keystore
alias and public key, plus the shared bond MAC key; it does not hold the private
Ed25519 seed.

`KeystoreKeyGenerator.kt` sets signing-only purpose, the Ed25519 curve,
`DIGEST_NONE`, `setUserAuthenticationRequired(true)`, and
`setUserAuthenticationParameters(0, AUTH_BIOMETRIC_STRONG)`. Approval uses a
`Signature("Ed25519")` bound to `BiometricPrompt.CryptoObject`. Each signing
operation requires fresh strong biometric authentication. Each incoming request
opens the fingerprint prompt automatically, without an extra Approve button tap.
Dismissing that prompt returns to the Authorize/Disallow screen while the request
is pending. Authorize reopens biometrics; Disallow rejects the request.
The pending approval appears in Android Recents. Its card is removed when the
request is approved, disallowed, cancelled by the desktop, or closed after an
error. Dismissing only biometrics keeps the pending approval available for retry,
including after switching to another app. The desktop deadline still applies;
its cancellation closes the pending approval even while it is in the background.
The phone prompt has no PIN/password fallback; the laptop's normal PAM password
is independent.

These are the current implementation's parameters. The former description of a
P-256 gate followed by a separate UniFFI seed signature no longer describes the
production approval path.

## Pairing and the persistent connection

Stop the desktop presence daemon and run `syauth pair --timeout-secs 300`.
Select the advertising computer in the phone's system picker, compare and approve
the six-digit system Bluetooth code, then compare and confirm the four-word app
phrase on both sides. The picker may display syauth rather than the hostname.

After the pair flow reaches success, tap Done. The Activity reloads the saved
bond, updates Home, installs the companion providers and GATT factory, starts
observing matching CDM associations, starts the foreground service, and schedules
the watchdog. No app restart is needed. Start the desktop daemon afterward.

The desktop is the GATT peripheral; the phone uses a persistent GATT client.
`SyauthCompanionService` is a foreground service holding this connection, rather
than a short-lived phone GATT server. Boot recovery and a periodic watchdog
provide recovery paths. Force-stopping the app prevents Android background
restart until the user opens it again; it is not an ordinary service crash.

The service closes stale GATT connections when Bluetooth turns off and reopens
them when Bluetooth turns on. After a connection drops, the client retries
connection and notification setup every 15 seconds until subscribed again.
Retries continue even if Android returns no GATT handle or rejects an open.
The retry interval does not guarantee a radio connection within 15 seconds.

If a connection remains stale, inspect daemon logs and the app status. Configure
only the phone's address for [desktop Bluetooth recovery](bluetooth.md). Opening
the app can reinitialize its connection; that is distinct from the fixed pairing
completion bug. No Bluetooth adapter reset is part of the normal procedure.

## Where the two `y` answers belong

The system code and the app phrase are separate keystrokes, on purpose:

* The **OS numeric comparison** is answered on the machine running
  `syauth pair`. The CLI prints the code BlueZ gave it and waits up to
  `OS_CONFIRM_DECISION_TIMEOUT` (25 s) for `y` + Enter **at the desktop
  keyboard**; the phone's dialog needs its own tap. Typing `y` early —
  the moment the code matches on either screen — is fine: keystrokes are
  queued and delivered to whichever prompt asks first.
* The **app-level OOB** `[y/N]` is answered in the same terminal, after the
  numeric comparison, against the 4-word code the phone prints.

If nobody answers the numeric comparison, the CLI answers BlueZ "reject"
once the window closes and says so, instead of leaving the phone waiting:
a pairing attempt that nobody confirmed must fail, and it must look like
that and not like a broken radio.

## Troubleshooting the pair flow

| Symptom | Check | Fix / note |
|---------|-------|-----------|
| `unrecognized subcommand 'pair'` | `syauth --help` lists `pair` | The installed binary predates the build in `target/`; install the current one (`make install`). |
| Phone's pairing dialog appears, tap does nothing | Desktop terminal shows `BT pairing code: NNNNNN` and the "Type y + Enter HERE" line | Answer at the desktop. `--waybar` hands the same decision to the bar applet; `--yes` auto-accepts (tests / scripted rigs only). |
| Codes differ between desktop and phone | — | **Stop and cancel on the phone.** Differing codes mean the numeric comparison is being relayed; SPEC §3.2 D5 exists for this case. |
| `error: no advertising peers found` after ~5 min | `systemctl --user status syauth-presenced`, `bluetoothctl show` | The CLI advertised for its accept window and no phone connected. Check the app is on the pairing screen, then retry. |
| Repeated attempts leave the picker empty | `adb shell dumpsys companiondevice` and count `com.sy.syauth.android` rows | Each `CompanionDeviceManager.associate` adds an association and they accumulate; clear the stale ones with `adb shell cmd companiondevice disassociate <user> <pkg> <desktop-address>`. |

## Cancellation and KDE

The phone verifies the complete challenge/cancellation frame before interpreting
its payload. Host cancellation matches the bonded peer and challenge nonce,
closes the matching activity, cancels biometrics, and suppresses late callbacks.
Submitting a sudo password in `terminal_prompt` mode dismisses both the approval
screen and an open biometric dialog. See [approval cancellation](cancellation.md).

For KDE, follow [the parallel fingerprint PAM setup](pam.md). Its separate password
stack remains available while phone approval is pending. Password unlock dismisses
the phone prompt when the cancellation notification reaches it; BLE delivery is
best effort.

## Verification and known build limitation

`./gradlew :app:testDebugUnitTest` runs JVM/Robolectric tests, including pairing
completion without Activity recreation and cancellation races. Real Bluetooth
pairing and hardware biometric approval still require a physical supported phone.
The tested setup's acceptance checks are recorded in the installation guide.

On Android 16, the current native dependencies may trigger the system's 16 KB
page-size compatibility warning. The tested Pixel completed pairing and biometric
approval in compatibility mode. This is a debug build, not a claim of native
16 KB compliance or a signed store release.

The October 2026 checks include native cancellation tests on Android 8/API 26
and physical Pixel approval/cancellation over Bluetooth on Android 16. API 26
coverage tests the approval lifecycle with a test gate; it does not establish
Keystore Ed25519 pairing support on that Android version. Android lint still
reports permission and API-level errors in existing pairing/connection code.

When updating an installed build, use the fork's current source and preserve its
signing identity. An older worktree can replace already installed behavior even
when the APK version name has not changed. Update the companion before the daemon
when deploying cancellation support, then check automatic biometrics, dismissal
and retry, password cancellation, and pending/completed Recents behavior.
