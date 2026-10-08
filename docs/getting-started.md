# Install on Arch Linux with KDE Plasma and an Android phone

This procedure was tested on Arch Linux, Plasma/kscreenlocker 6.7.91, and a
Pixel 8 Pro running Android 16. It enables sudo and KDE screen unlock for one
local user. Choose empty-field Enter for manual phone requests or the parallel
fingerprint stack for automatic requests in the [PAM guide](pam.md).
The parallel setup permits password unlock while phone approval waits and
cancels its pending dialog. Login/SDDM and global PAM stacks are outside this
procedure.

## Desktop binaries and storage

Install Rust, a C linker, the BlueZ development files, and enable Bluetooth.
For building Android, also install OpenJDK, Android SDK platform 34, platform-tools,
and an Android NDK. The tested Java version was OpenJDK 21 and NDK 28.2.13676358.
On Arch, `base-devel`, `bluez`, `bluez-utils`, `dbus`, `polkit`, and `jdk21-openjdk`
provide the desktop dependencies; use your SDK installation for the Android tools.

```sh
git clone https://github.com/D3SOX/syauth.git
cd syauth
cargo build --release --locked -p syauth-cli -p syauth-pam -p syauth-presenced
```

Run the following from a terminal in your local KDE session. `sudo` requests
administrator authentication in that terminal. Substitute your login name for
`LOCAL_USER`; do not run the daemon as root.

```sh
sudo install -Dm644 target/release/libpam_syauth.so /usr/lib/security/pam_syauth.so
sudo install -Dm755 target/release/syauth /usr/local/bin/syauth
sudo install -Dm755 target/release/syauth-presenced /usr/local/libexec/syauth-presenced
sudo install -d -m700 -o LOCAL_USER -g LOCAL_USER /var/lib/syauth /var/lib/syauth/keys /var/log/syauth
install -Dm644 crates/syauth-presenced/dist/syauth-presenced.service \
  ~/.config/systemd/user/syauth-presenced.service
mkdir -p ~/.config/systemd/user/syauth-presenced.service.d
cat > ~/.config/systemd/user/syauth-presenced.service.d/runtime.conf <<'UNIT'
[Service]
RuntimeDirectory=syauth
RuntimeDirectoryMode=0700
ReadWritePaths=%t/syauth
UNIT
systemctl --user daemon-reload
```

The runtime drop-in is needed with the shipped unit's `ProtectSystem=strict`:
the daemon must create its socket and pidfile under `/run/user/UID/syauth`.
`/usr/lib/security` is the PAM module directory on Arch; `/usr/lib64/security`
from the earlier README instructions was incorrect for this installation.

### Update the daemon without administrator access

The daemon runs as your user. You can install updates in your home directory and
override the unit's executable path. This was also used on the tested laptop:

```sh
cargo build --release --locked -p syauth-presenced
install -Dm755 target/release/syauth-presenced ~/.local/libexec/syauth-presenced
mkdir -p ~/.config/systemd/user/syauth-presenced.service.d
cat > ~/.config/systemd/user/syauth-presenced.service.d/binary.conf <<'UNIT'
[Service]
ExecStart=
ExecStart=%h/.local/libexec/syauth-presenced
UNIT
systemctl --user daemon-reload
systemctl --user restart syauth-presenced
systemctl --user status syauth-presenced
```

Keep the runtime and phone drop-ins. Later daemon updates only need the build,
install, and restart commands. Updating the daemon does not change PAM rules,
pairing keys, or the pacman checker's baseline. To return to the executable in
the original unit, remove `binary.conf`, reload the user manager, and restart
the service.

## Build and install Android

Gradle needs the native AAR and generated Kotlin bindings first. A plain
`assembleDebug` on a fresh checkout does not create these inputs.

```sh
export ANDROID_HOME="$HOME/Android/Sdk"
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk
export NDK_HOME="$ANDROID_HOME/ndk/28.2.13676358"
cargo install cargo-ndk --locked
rustup target add aarch64-linux-android armv7-linux-androideabi \
  x86_64-linux-android i686-linux-android
```

UniFFI 0.29.5's crate does not ship an installable standalone executable. Create
this small CLI wrapper outside the repository, matching the workspace's version:

```sh
bindgen_dir="$(mktemp -d)"
mkdir -p "$bindgen_dir/src"
cat > "$bindgen_dir/Cargo.toml" <<'TOML'
[package]
name = "syauth-uniffi-tool"
version = "0.1.0"
edition = "2024"

[dependencies]
uniffi = { version = "=0.29.5", features = ["cli"] }

[[bin]]
name = "uniffi-bindgen"
path = "src/main.rs"
TOML
cat > "$bindgen_dir/src/main.rs" <<'RUST'
fn main() { uniffi::uniffi_bindgen_main(); }
RUST
cargo build --release --manifest-path "$bindgen_dir/Cargo.toml"
export PATH="$bindgen_dir/target/release:$PATH"
make android-aar
cd syauth-android
./gradlew :app:assembleDebug :app:testDebugUnitTest
adb devices -l
adb -s PHONE_SERIAL shell am get-current-user
adb -s PHONE_SERIAL install --user 0 -r app/build/outputs/apk/debug/app-debug.apk
cd ..
```

Use the actual serial reported by ADB, and install into the intended Android user
(the tested phone used user 0). The checked-in Gradle configuration already
consumes the AAR and bindings from `crates/syauth-mobile`; no copying into `app/libs`
is required. The tested Pixel installation used an arm64-only AAR assembled from
the same native library and bindings; `make android-aar` packages all four ABIs.

Open syauth on the phone, allow Nearby devices/Bluetooth access and notifications,
and keep Bluetooth enabled. Production pairing requires Android 13/API 33+
with Keystore Ed25519 support; the APK minimum SDK alone is insufficient. See
[Android requirements](android-setup.md). This is a debug APK signed by your local debug key;
update it using the same key to preserve app data. Android 16 may show a native
16 KB page-size compatibility warning with the current native dependencies. The
tested Pixel successfully paired and approved authentication in compatibility
mode; this does not establish native 16 KB compliance.

## Pair while the daemon is stopped

The pairing CLI advertises its own service. Stop the presence daemon first so
both processes do not register competing services on the adapter.

```sh
systemctl --user stop syauth-presenced
syauth pair --timeout-secs 300
```

1. On the phone, select Pair / Pair with computer and choose syauth
   in Android's device picker (it may use this advertisement name rather than
   your laptop hostname).
2. Compare the six-digit Bluetooth code on both devices and approve only a match.
   Contact/call-history sharing is unnecessary. Media audio and Phone calls can
   stay disabled; authentication uses BLE. See the
   [Bluetooth transport test](bluetooth.md#test-the-pixel-without-audio-profiles).
3. Compare the four-word app confirmation on both devices and confirm the match
   in the phone app and desktop terminal. These are a separate confirmation from
   the system Bluetooth dialog.
4. Tap Done. Home now shows the new bond and starts the companion service
   immediately. Restarting the Android app is no longer required.
5. Run `syauth list` to confirm the desktop record exists.

If pairing fails, inspect Bluetooth settings on both devices for stale bonds
before retrying. Only remove the intended phone/computer pairing. Do not reset
Bluetooth or remove unrelated devices.

Optionally configure the daemon to reconnect only the phone on restart. Use
the phone identity address shown by `bluetoothctl devices Paired`, not an unrelated
headset address or the desktop peer ID from `syauth list`:

```sh
cat > ~/.config/systemd/user/syauth-presenced.service.d/phone.conf <<'UNIT'
[Service]
Environment=SYAUTH_RECONNECT_DEVICE=AA:BB:CC:DD:EE:FF
UNIT
systemctl --user daemon-reload
systemctl --user enable --now syauth-presenced
systemctl --user status syauth-presenced
syauth status
```

Replace the address before starting. With this variable unset, the daemon does
not disconnect Bluetooth devices on startup. See [Bluetooth recovery](bluetooth.md).
The connection can take several seconds; inspect `journalctl --user -u
syauth-presenced` and the phone's connection status before enabling PAM.

## Enable and test PAM

Follow [sudo and KDE PAM setup](pam.md). First test the module without changing
system stacks, then sudo, then KDE phone unlock and password fallback. Keep a
working desktop session and the documented rollback available during setup.

The completed acceptance checks on the tested laptop were:

- `sudo -k; sudo true` approved by a Pixel fingerprint.
- Meta+L, then Pixel fingerprint unlocked KDE with the password field available.
- Meta+L, then laptop password unlocked KDE and dismissed the pending phone dialog.
- Headphones stayed connected across daemon restarts after limiting reconnect to
  the phone address.
