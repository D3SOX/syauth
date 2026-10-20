Approve Linux authentication on Android with a fresh strong biometric.

- Native desktop DEB, RPM, and Arch packages and Linux archives for x86_64 and ARM64.
- Signed Android companion with four native ABIs and a published signing certificate.
- Illustrated documentation: https://d3sox.me/syauth/
- Installer: `curl -fsSL https://d3sox.me/syauth/install.sh | sh`

Packages install the CLI, PAM module, presence daemon, and user service. They do not enable PAM or start the service automatically. Follow the installation guide to prepare storage, pair the phone, select a PAM policy, and test your recovery method.

Linux requires glibc 2.36+; supported package paths include Debian 12+, Ubuntu 24.04+, and current Fedora/openSUSE/Arch systems. Android signing requires Android 13+ and a supported Ed25519 Keystore implementation, despite the APK's lower installation minimum.

This release comes from the [D3SOX/syauth](https://github.com/D3SOX/syauth) fork. See [fork changes](https://d3sox.me/syauth/fork/). Verify downloads against the SHA-256 digest GitHub shows for each asset. `release.json` records the source commit and artifact sizes. The Android release certificate SHA-256 fingerprint is `F8:9A:79:07:DF:39:0C:A3:E2:A8:1B:82:48:BC:AA:C4:5A:A6:38:AE:5B:01:31:CE:13:BE:2E:8F:93:55:51:3E`. It differs from the upstream release key, so replacing an upstream or debug APK requires uninstalling it and pairing again.

Read the documented security boundaries before enabling PAM: https://d3sox.me/syauth/explanation/security/
