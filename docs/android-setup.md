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

If a connection remains stale, inspect daemon logs and the app status. Configure
only the phone's address for [desktop Bluetooth recovery](bluetooth.md). Opening
the app can reinitialize its connection; that is distinct from the fixed pairing
completion bug. No Bluetooth adapter reset is part of the normal procedure.

## Cancellation and KDE

The phone verifies the complete challenge/cancellation frame before interpreting
its payload. Host cancellation matches the bonded peer and challenge nonce,
closes the matching activity, cancels biometrics, and suppresses late callbacks.
See [approval cancellation](cancellation.md).

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
