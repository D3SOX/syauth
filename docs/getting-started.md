# Install on Arch Linux with KDE Plasma and an Android phone

This procedure was tested on Arch Linux, Plasma/kscreenlocker 6.7.91, and a
Pixel 8 Pro running Android 16. It enables sudo and KDE screen unlock for one
local user. Choose empty-field Enter for manual phone requests or the parallel
fingerprint stack for automatic requests in the [PAM guide](pam.md).
The parallel setup permits password unlock while phone approval waits and
cancels its pending dialog. Login/SDDM and global PAM stacks are outside this
procedure.

The live lockscreen status integration was also tested with Plasma 6.8. For
sudo, the [combined password/phone prompt](pam.md#password-entry-while-phone-approval-waits)
accepts password input while phone approval is pending and supports asterisks.

## Install with the script

Use Python 3.11 or newer from your normal desktop user session on Arch Linux
with Plasma and kscreenlocker 6.8 or newer. Install the Rust toolchain and
desktop build prerequisites listed below first. The script checks prerequisites
and PAM compatibility before building. It does not install system packages.
Enable Bluetooth before starting. If `~/.local/bin` is not on your `PATH`, use
`~/.local/bin/syauth` explicitly after installation.

From the repository root:

```sh
python3 scripts/install.py --dry-run
python3 scripts/install.py
```

The dry run prints the proposed PAM changes without building, elevating, or
writing files. The installation builds release binaries as your user, installs
the CLI under `~/.local/bin` and daemon under `~/.local/libexec`, and configures
the systemd user service. It uses `sudo` in the terminal to install the PAM
module and the selected user's sudo/KDE rules. Run the installer as your normal
desktop user; it requests administrator access only for system changes.

Sudo gets `terminal_prompt pwfeedback`. KDE uses empty-field Enter for phone
requests and keeps password authentication available. The script installs the
live status label into the active Plasma shell package. It preserves account,
password, and session rules, and leaves global PAM files and SDDM unchanged.
It supports stock Arch stacks and the documented empty-submission setup.
An existing automatic phone block in `kde-fingerprint` must first be removed
using the [PAM guide](pam.md#kde-request-the-phone-with-an-empty-submission).
Unfamiliar custom stacks stop for review.

To configure reconnects for only your phone, supply its bonded BlueZ address:

```sh
python3 scripts/install.py --phone-address AA:BB:CC:DD:EE:FF
```

Use `bluetoothctl devices Paired` to find the phone's address. Omitting this
option preserves an existing `phone.conf`; on a fresh installation it leaves
forced desktop reconnects disabled. Other Bluetooth devices are untouched.

### Optional Android installation and pairing

Install OpenJDK, Android SDK platform 34, platform-tools, an Android NDK, and
`cargo-ndk` as described below. Set `JAVA_HOME` and `ANDROID_HOME`; set `NDK_HOME`
to choose an installed NDK explicitly. Otherwise the script selects the newest
installed stable NDK under the SDK's `ndk` directory.

```sh
adb devices -l
python3 scripts/install.py --android PHONE_SERIAL
python3 scripts/install.py pair
```

Replace `PHONE_SERIAL` with the intended ADB device. The Android option prepares
a UniFFI tool matching `Cargo.lock`, installs the Rust Android targets, builds
the native AAR and debug APK, runs Android JVM tests, and updates the app for
Android user 0. Production pairing needs Android 13/API 33+ with Keystore
Ed25519 support. The selected device must currently be using user 0. Existing app
data is preserved; updating requires the same debug signing key. SDK setup and
license acceptance remain prerequisites. The script does not uninstall an app
when signing keys differ.

The pairing command pauses the running desktop daemon and restores it afterward,
including when pairing fails or is cancelled. Open the phone's pairing screen
and compare and confirm both the Bluetooth and app codes on both devices.
Existing bonds are retained unless you explicitly pair or revoke them.

For already built artifacts, use `--skip-build`. The desktop artifacts default
to `target/release`; `--artifacts-dir /absolute/path/to/artifacts` overrides that
location. With `--android`, this also reuses the existing debug APK. The installer
checks the desktop ELF files, PAM exports, and module dependencies before copying.

### Backups, rollback, and update checks

Repeat installation updates the managed files without adding duplicate PAM
rules. The first originals remain in `/var/lib/syauth-installer` for system
files and `~/.local/state/syauth/installer` for your user files. The user state
location follows `XDG_STATE_HOME`. A failed file transaction restores the files
from that attempt. Rollback restores the setup from before the first installation:

```sh
python3 scripts/install.py rollback
```

An interrupted process leaves a recovery journal. Use the same rollback command
before retrying; concurrent installers are refused.

Rollback restores service state, PAM files, desktop binaries, lockscreen settings,
and any previous shell override. It preserves pairing keys and the Android app.
If managed files have been edited since installation, the script stops before
overwriting them and identifies the backup directory for review. Keep backups
until the new setup has passed phone approval, password fallback, and timeout
checks in the [PAM guide](pam.md).

After those checks, optionally install the Arch update checker and record its
baseline:

```sh
python3 scripts/install.py update-check
```

This explicit step uses the existing pacman-hook installer. It refuses an
existing checker or baseline so a repeat command cannot silently approve
changes. Follow the [update-check guide](pam.md#check-the-setup-after-pacman-updates)
to maintain or remove it. Desktop rollback leaves this separately installed
checker and its baseline in place.

The following sections document the equivalent manual setup.

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

Enable `terminal_prompt` for concurrent sudo password entry. Add its `pwfeedback`
option for asterisks; sudoers' `Defaults pwfeedback` does not control this prompt.
Phone approval finishes without Enter and discards any partial password. Enter
submits the password to the existing password module and dismisses the phone
request. Clear cached authentication with `sudo -k` before testing each path.

For empty-field phone requests on Plasma 6.8, install
[live lockscreen status](pam.md#live-phone-status-on-the-lockscreen). It uses a
Plasma shell package override and shows whether the phone's notification
subscription is ready before you press Enter. Password entry stays available.
Rerun the installer after Plasma upgrades to refresh the copied shell files.

### Check connection recovery

With the daemon running, use `syauth status --json` to inspect the peer's
`connected` field. Turn phone Bluetooth off, confirm it becomes `false`, then
turn Bluetooth on and wait for `true` before requesting approval. Repeat after
leaving the laptop's range and returning. These checks should not require
reopening the phone app or pairing again.

The client retries every 15 seconds until notification setup succeeds, including
when Android initially rejects a GATT connection. Radio discovery can take
longer than that interval. See [connection recovery and measured results](bluetooth.md#recovery-after-leaving-range-or-restarting-bluetooth).

### Verified behavior

The completed acceptance checks on the tested laptop were:

- `sudo -k; sudo true` approved by a Pixel fingerprint.
- Meta+L, then Pixel fingerprint unlocked KDE with the password field available.
- Meta+L, then laptop password unlocked KDE and dismissed the pending phone dialog.
- Headphones stayed connected across daemon restarts after limiting reconnect to
  the phone address.

Additional checks on 2026-10-15 covered masked password editing in a private
PAM/PTY test, automatic fingerprint prompts, password submission dismissing both
phone dialogs, and live status changes in an isolated Plasma 6.8 greeter. The
Pixel recovered Bluetooth off/on and a simulated unavailable desktop without
reopening the app. Physical range loss and long idle periods still need separate
acceptance checks.
