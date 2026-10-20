Approve Linux authentication on Android with a fresh strong biometric.

- Native desktop DEB, RPM, and Arch packages and Linux archives for x86_64 and ARM64.
- Signed Android companion with four native ABIs and a published signing certificate.
- Illustrated documentation: https://dmytrogajewski.github.io/syauth/
- Installer: `curl -fsSL https://dmytrogajewski.github.io/syauth/install.sh | sh`

Packages install the CLI, PAM module, presence daemon, and user service. They do not enable PAM or start the service automatically. Follow the installation guide to prepare storage, pair the phone, select a PAM policy, and test your recovery method.

Linux requires glibc 2.36+; supported package paths include Debian 12+, Ubuntu 24.04+, and current Fedora/openSUSE/Arch systems. Android signing requires Android 13+ and a supported Ed25519 Keystore implementation, despite the APK's lower installation minimum.

Verify downloads against `SHA256SUMS`. `release.json` records the source commit and artifact digests. The Android release certificate SHA-256 fingerprint is `25:58:5E:64:1E:DB:3D:A8:7B:98:90:56:B3:D1:65:CA:C2:AF:AF:2A:AE:DD:35:87:56:66:B5:21:EC:C0:22:1C`.

Read the documented security boundaries before enabling PAM: https://dmytrogajewski.github.io/syauth/explanation/security/
