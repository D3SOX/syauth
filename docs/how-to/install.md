# Install the desktop and companion app

This guide sets up the desktop daemon and Android companion, then explains how to enable one PAM service. It targets a single desktop account using the default `/var/lib/syauth` store.

## Prerequisites

Use Linux with PAM, systemd user services, BlueZ, and a BLE adapter capable of advertising. You need a Rust toolchain compatible with `Cargo.lock`, a C toolchain, `pkg-config`, and the development packages for D-Bus, PAM, and Bluetooth. On Debian-based systems those packages are `libdbus-1-dev`, `libpam0g-dev`, and `libbluetooth-dev`.

For the phone, use Android 13 / API 33 or later, a supported Ed25519 Keystore implementation, and an enrolled strong biometric. Hardware support varies; StrongBox is requested with a non-StrongBox Keystore fallback. A PIN alone cannot satisfy the unlock signing prompt.

Before enabling PAM, read [security boundaries](../explanation/security.md). Keep an authenticated administrator session open and retain your distribution's existing recovery method while testing.

## Build the desktop

From a checkout of syauth:

```sh
cargo build --locked --release \
  -p syauth-cli -p syauth-pam -p syauth-presenced
```

The build produces `target/release/syauth`, `target/release/syauth-presenced`, and `target/release/libpam_syauth.so`.

Install the binaries:

```sh
sudo install -D -m 755 target/release/syauth /usr/local/bin/syauth
sudo install -D -m 755 target/release/syauth-presenced \
  /usr/local/libexec/syauth-presenced
```

Install the PAM library in your distribution's PAM module directory, with the name `pam_syauth.so`. Find that directory from existing modules; common locations are `/usr/lib/security`, `/usr/lib64/security`, and `/usr/lib/x86_64-linux-gnu/security`. For example, on a host using `/usr/lib64/security`:

```sh
sudo install -m 644 target/release/libpam_syauth.so \
  /usr/lib64/security/pam_syauth.so
```

## Prepare storage and the user service

For a new installation, create the default directories owned by the account that runs the daemon and pairing command:

```sh
sudo install -d -m 700 -o "$(id -un)" -g "$(id -gn)" \
  /var/lib/syauth /var/lib/syauth/keys /var/log/syauth
```

Do not give multiple accounts ownership of the same store. Existing installations should retain their intended ownership; inspect the paths with `syauth doctor` before changing permissions.

Write the user unit using the already installed binary, then activate it as your desktop user:

```sh
syauth install-presenced --dry-run \
  --from /usr/local/libexec/syauth-presenced
systemctl --user daemon-reload
systemctl --user enable --now syauth-presenced.service
```

The `--dry-run` command **writes the unit file** but skips the binary copy and `systemctl` calls. This sequence performs the privileged binary installation separately and places the unit in your own user session. There is no `--live` flag. See [configuration](../reference/configuration.md#service-installation) for the installer's other behavior.

## Install the Android app

Use an APK from a [release](https://github.com/dmytrogajewski/syauth/releases) if a suitable artifact is available. To build from source, provide Android SDK platform 34, a JDK compatible with the checked-in Gradle wrapper, the Android NDK, `cargo-ndk`, the four Rust Android targets required by `scripts/build_aar.sh`, and UniFFI bindgen 0.29 matching the Rust dependency.

Set `NDK_HOME` to your installed NDK, then run:

```sh
make android-aar
cd syauth-android
./gradlew :app:assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Confirm the AAR exists at `crates/syauth-mobile/target/syauth_mobile.aar` before running Gradle. The Make target can skip on an incomplete toolchain; a skipped build is not an APK build.

Open the app and grant the requested Bluetooth and notification permissions. Complete the companion-device and battery-optimization prompts presented by setup. Manufacturer background restrictions can affect delivery even after these grants.

## Pair, then enable one PAM service

Follow [pairing](pair-and-revoke.md) and confirm an active bond before changing a PAM service.

The installer defaults to `auth sufficient`, whereas SPEC §3.2 D7 specifies `auth required`. These policies behave differently. Read [the PAM policy reference](../reference/configuration.md#pam-policy) and have your administrator select the intended stack before running the installer.

If you have selected the installer's `sufficient` policy for `sudo`, install only its PAM line; the user daemon is already configured:

```sh
sudo syauth install-pam --service sudo --with-presenced=false \
  --control sufficient
```

Inspect `/etc/pam.d/sudo` and its `.bak` backup. Do not add U2F fallback unless `pam_u2f` is installed and enrolled. Do not copy a service chain from another distribution.

## Verify and undo

Run `syauth doctor`, then complete [your first unlock](../tutorials/first-unlock.md). Test the existing authentication method with the phone unavailable before closing the administrator session.

To undo this service's installation, restore its backup:

```sh
sudo syauth uninstall-pam --service sudo
```

The uninstall command restores the saved file, so preserve any edits made after installation before using it. Other enabled PAM services remain separate.

<!-- Structure: Diátaxis goal-oriented how-to; commands checked against CLI help and installer source. -->
