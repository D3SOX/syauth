# Install the desktop and companion app

This guide sets up the desktop daemon and Android companion, then explains how to enable one PAM service. It targets a single desktop account using the default `/var/lib/syauth` store.

## Prerequisites

Use Linux with glibc 2.36+, PAM, systemd user services, BlueZ, and a BLE adapter capable of advertising. Release packages target Debian 12+, Ubuntu 24.04+, and current Fedora, openSUSE, and Arch systems. Both x86_64 and ARM64 artifacts are available; the tested distribution/CPU matrix is listed in [release development](../contributing/releases.md#artifact-contract).

For the phone, use Android 13 / API 33 or later, a supported Ed25519 Keystore implementation, and an enrolled strong biometric. Hardware support varies; StrongBox is requested with a non-StrongBox Keystore fallback. A PIN alone cannot satisfy the unlock signing prompt.

Before enabling PAM, read [security boundaries](../explanation/security.md). Keep an authenticated administrator session open and retain your distribution's existing recovery method while testing.

## Install a release package

Install the latest release with your native package manager:

```sh
curl -fsSL https://d3sox.me/syauth/install.sh | sh
```

The POSIX shell installer reads your distribution and architecture, resolves one GitHub release tag, downloads that tag's package, checks it against the SHA-256 digest GitHub's release API reports for that exact asset, then invokes `apt`, `dnf`, `zypper`, or `pacman`. It requests `sudo` when necessary. An unsupported system or checksum mismatch stops installation. It does not change PAM stacks, enable services, or change existing bond ownership.

To inspect the script, select a version, or preview package selection:

```sh
curl -fsSLo install-syauth.sh https://d3sox.me/syauth/install.sh
less install-syauth.sh
sh install-syauth.sh --version 0.1.1 --dry-run
sh install-syauth.sh --version 0.1.1
```

### Direct downloads

The [v0.1.1 release](https://github.com/D3SOX/syauth/releases/tag/v0.1.1) has the native packages, manual archives, source, and signed APK. GitHub shows each asset's SHA-256 digest on the release page and in its API; there is no separate checksum file. For example, on Debian/Ubuntu x86_64:

```sh
release=https://github.com/D3SOX/syauth/releases/download/v0.1.1
curl -fSLO "$release/syauth_0.1.1_amd64.deb"
curl -fsSL https://api.github.com/repos/D3SOX/syauth/releases/tags/v0.1.1 \
  | jq -r '.assets[] | "\(.digest | ltrimstr("sha256:"))  \(.name)"' > digests
sha256sum --check --ignore-missing digests
sudo apt install ./syauth_0.1.1_amd64.deb
```

Choose the corresponding artifact for other native managers, verify it against the same digest list, then install it:

| System | x86_64 artifact | Install command |
| --- | --- | --- |
| Fedora | `syauth-0.1.1-4.x86_64.rpm` | `sudo dnf install ./syauth-0.1.1-4.x86_64.rpm` |
| openSUSE | `syauth-0.1.1-4.x86_64.rpm` | `sudo zypper install --allow-unsigned-rpm ./syauth-0.1.1-4.x86_64.rpm` |
| Arch | `syauth-0.1.1-1-x86_64.pkg.tar.zst` | `sudo pacman -U ./syauth-0.1.1-1-x86_64.pkg.tar.zst` |

For ARM64, use the DEB ending in `_arm64.deb`, or the RPM/Arch filename with `aarch64` replacing `x86_64`. The RPM is digest-verified rather than RPM-signed; the openSUSE command permits that local unsigned RPM without disabling repository checks. These are downloadable native packages, not registered APT/DNF repositories or an AUR listing. Repeat the shell installer to fetch and install a newer release.

Packages install `/usr/bin/syauth`, `/usr/libexec/syauth-presenced`, the distribution's `pam_syauth.so`, and `/usr/lib/systemd/user/syauth-presenced.service`. Continue with storage preparation below.

## Build the desktop from source

Source builds additionally require a Rust toolchain compatible with `Cargo.lock`, a C toolchain, `pkg-config`, Python 3, and development packages for D-Bus, PAM, and Bluetooth (`libdbus-1-dev`, `libpam0g-dev`, and `libbluetooth-dev` on Debian).

From a checkout of syauth, the installer builds the binaries, packages them with the same packager as the releases, and installs that package with your package manager:

```sh
sh scripts/install.sh --source --dry-run
sh scripts/install.sh --source
```

The result has the same layout as a release package, so upgrades and removal go through the package manager. `--source DIR` builds a checkout elsewhere.

## Arch Linux and KDE Plasma setup

On Arch Linux with Plasma 6.8 or newer, add `--desktop` to either mode. The installer then also configures sudo and KDE screen unlock, live lockscreen status, the storage directories, and the user daemon, with backups and a `rollback` command. `--android SERIAL` installs the phone app over ADB: the signed release APK, or with `--source` a debug build. See [install on Arch Linux](../getting-started.md#install-with-the-script).

## Prepare storage and the user service

For a new installation, create the default directories owned by the account that runs the daemon and pairing command:

```sh
sudo install -d -m 700 -o "$(id -un)" -g "$(id -gn)" \
  /var/lib/syauth /var/lib/syauth/keys /var/log/syauth
```

Do not give multiple accounts ownership of the same store. Existing installations should retain their intended ownership; inspect the paths with `syauth doctor` before changing permissions.

For a package installation, the user unit is already installed. Reload and activate it as your desktop user:

```sh
systemctl --user daemon-reload
systemctl --user enable --now syauth-presenced.service
```

## Install the Android app

Download the [signed Android APK](https://github.com/D3SOX/syauth/releases/download/v0.1.1/syauth-0.1.1-android.apk). Verify the downloaded file against its GitHub digest before opening it on your phone, or install it with ADB:

```sh
curl -fsSL https://api.github.com/repos/D3SOX/syauth/releases/tags/v0.1.1 \
  | jq -r '.assets[] | "\(.digest | ltrimstr("sha256:"))  \(.name)"' > digests
sha256sum --check --ignore-missing digests
adb install -r syauth-0.1.1-android.apk
```

With Android SDK Build Tools installed, verify the signature using `apksigner verify --verbose --print-certs syauth-0.1.1-android.apk`. Compare its SHA-256 certificate digest with the [published release signing identity](../contributing/releases.md#android-builds-and-signing). The private signing key is retained across releases. A debug APK or an APK from the upstream repository uses a different identity and must be uninstalled before installing this release; uninstalling removes its local app data and requires pairing again.

To build from source, provide Android SDK platform 34, JDK 21, NDK 28.0.13004108, cargo-ndk 4.1.2, and the four Rust Android targets required by `scripts/build_aar.sh`. Its checked-in helper generates the matching UniFFI 0.29.5 bindings.

Set `NDK_HOME` to your installed NDK, then run:

```sh
scripts/build_aar.sh
cd syauth-android
./gradlew :app:assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Confirm the AAR exists at `crates/syauth-mobile/target/syauth_mobile.aar` before running Gradle. See [release builds](../contributing/releases.md) for the signing workflow.

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
