# Fork changes

This site documents [D3SOX/syauth](https://github.com/D3SOX/syauth), a fork of [dmytrogajewski/syauth](https://github.com/dmytrogajewski/syauth). The fork merges upstream regularly and publishes its own releases. The changes below are not in upstream.

## Arch Linux and KDE Plasma desktop

- **One installer.** `install.sh` installs the verified release package or, with `--source`, builds and installs a local package. `--desktop` configures sudo and KDE screen unlock, live lockscreen status, and the user daemon, and keeps backups for `rollback`. `--android SERIAL` installs the phone app over ADB. See [scripted installation](getting-started.md#install-with-the-script).
- **Empty-password KDE unlock.** With the `on_empty_password` PAM option, pressing Enter in an empty lockscreen password field requests phone approval. Typing a password uses normal password authentication. See [KDE: request the phone with an empty submission](pam.md#kde-request-the-phone-with-an-empty-submission).
- **Combined sudo prompt.** With `terminal_prompt`, sudo accepts a password while phone approval waits. Approval finishes without Enter, and submitting a password dismisses the phone request. `pwfeedback` shows asterisks. See [password entry while phone approval waits](pam.md#password-entry-while-phone-approval-waits).
- **Live lockscreen status.** On Plasma 6.8, the lockscreen shows whether the phone is connected and when an approval is pending. See [live phone status](pam.md#live-phone-status-on-the-lockscreen).
- **Approval cancellation.** A password submission or host cancellation closes the pending approval on the phone. See [approval cancellation](cancellation.md).
- **Update check.** An optional pacman hook checks the PAM files, package versions, and module dependencies after updates. See [Arch package update checks](arch-update-check.md).

## Connection recovery

- The daemon retries an unlock request while the phone resubscribes to notifications, within the original authentication deadline.
- It disconnects and reconnects only the phone set in `SYAUTH_RECONNECT_DEVICE`; other Bluetooth devices stay connected.
- When the Bluetooth adapter disappears or changes, the daemon exits and systemd restarts it against the current adapter. A USB controller can return as `hci1` instead of `hci0` after suspend.
- The phone app stops its connection when Bluetooth turns off and reconnects when it turns on. It retries until the notification subscription is ready.

See [Bluetooth transport and connection recovery](bluetooth.md).

## Android companion

- The fingerprint prompt opens automatically when a request arrives. Dismissing it returns to Authorize/Disallow.
- Pending approvals stay reachable from Recents.
- Tapping Done after pairing activates the bond and starts the connection service without restarting the app.

See [Android companion setup](android-setup.md).

## Releases

The fork builds its releases from this repository and signs the APK with its own Android key. That certificate differs from upstream's, so replacing an upstream or debug APK requires uninstalling it and pairing again. Releases publish no separate checksum file. The installer checks each download against the SHA-256 digest GitHub reports for that asset. See [build and publish a release](contributing/releases.md).
