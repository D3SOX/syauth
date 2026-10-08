# syauth-android

Android companion app for the syauth phone-as-key unlock protocol.

## Setup and behavior

Follow [the tested Arch/KDE installation guide](../docs/getting-started.md) to
build, install, and pair the app, then enable [sudo and KDE unlock](../docs/pam.md).
The app includes Bluetooth pairing, persistent GATT connections, foreground
service recovery, and per-request Keystore biometric signing.

Tapping Done after pairing updates Home and starts the connection service without
an app restart. Authentication opens the fingerprint prompt automatically.
Dismissing it returns to Authorize/Disallow; Authorize retries and Disallow
rejects. Host cancellation or timeout closes the pending approval.

Although the APK's minimum SDK is 26, production pairing needs Android 13/API 33+
and Keystore Ed25519 support. See [Android requirements](../docs/android-setup.md).
The physical acceptance tests used a Pixel 8 Pro on Android 16.

## Build

The installation guide builds a debug APK. Update with the same debug signing
key to preserve app data. The release build does not enable R8 minification.

Prerequisites on the build host:

- OpenJDK 21 for the tested build. Set `JAVA_HOME` to that installation.
- Android SDK with `cmdline-tools;latest` and `platforms;android-34`.
- The `syauth_mobile.aar` produced by `make android-aar` from the workspace
  root. On hosts without the Android NDK, `make android-aar-dry-run` verifies
  the pipeline but does not produce the artifact.

From this directory:

```bash
./gradlew :app:assembleDebug
```

The APK is written to `app/build/outputs/apk/debug/app-debug.apk`.
Build the AAR and generated Kotlin bindings before running Gradle; the
[installation guide](../docs/getting-started.md) includes the UniFFI CLI setup.

## Test

Run the JVM/Robolectric tests from this directory with
`./gradlew :app:testDebugUnitTest`. These cover pairing completion, approval
callbacks, manual retry, and host cancellation.

The instrumented `HelloWorldTest` launches `MainActivity` on a connected
device or emulator and checks the OOB display:

```bash
# From the workspace root:
make android-test
```

`make android-test` skips cleanly with an actionable message when either:

- `crates/syauth-mobile/target/syauth_mobile.aar` does not exist
  (run `make android-aar` on an NDK-equipped host first), or
- no emulator / device is connected over `adb`.

## Pinned versions

| Component                    | Version           | Source line in prrr-android        |
|------------------------------|-------------------|------------------------------------|
| AGP                          | 8.2.2             | `build.gradle.kts` plugins block.  |
| Kotlin                       | 1.9.22            | `build.gradle.kts` plugins block.  |
| compileSdk                   | 34                | `app/build.gradle.kts` line 22.    |
| minSdk                       | 26                | `app/build.gradle.kts` line 30.    |
| targetSdk                    | 34                | `app/build.gradle.kts` line 31.    |
| JVM target                   | 17                | `app/build.gradle.kts` lines 70-75 |
| Compose compiler ext         | 1.5.8             | `app/build.gradle.kts` line 83.    |
| Compose BOM                  | 2024.02.00        | `app/build.gradle.kts` line 111.   |
| JNA                          | 5.14.0            | `app/build.gradle.kts` line 96.    |
| Gradle wrapper               | 9.5.0-milestone-3 | `gradle/wrapper/...properties`.    |

The Gradle wrapper (`gradle/wrapper/gradle-wrapper.jar`, `gradlew`,
`gradlew.bat`) is copied verbatim from prrr-android.
