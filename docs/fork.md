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
- `syauth pair` and `syauth status` use BlueZ's default adapter too, instead of assuming `hci0`. When an explicitly named adapter is missing, `pair` lists the adapters BlueZ has.
- The phone app stops its connection when Bluetooth turns off and reconnects when it turns on. It retries until the notification subscription is ready.

See [Bluetooth transport and connection recovery](bluetooth.md).

## Pairing

- `syauth pair` is the only pairing path. Upstream's daemon also kept the adapter pairable and discoverable, registered a Bluetooth agent that accepted every numeric-comparison request, and saved a bond for any phone that wrote a key to its pair service. It also took the default agent away from `syauth pair`, so running both at once broke pairing. The fork's daemon does none of this. See [pair a phone](how-to/pair-and-revoke.md).
- After three `bad-signature` results in a row from a bonded phone, `syauth status`, `syauth doctor`, and the KDE lockscreen say that the phone's key changed and that it needs a new pairing. This happens when the app's data is restored from a backup without its Keystore key. See [the phone's key changed](how-to/troubleshoot.md#the-phones-key-changed).

## Android companion

- The fingerprint prompt opens automatically when a request arrives. Dismissing it returns to Authorize/Disallow.
- Pending approvals stay reachable from Recents.
- Tapping Done after pairing activates the bond and starts the connection service without restarting the app.
- A failed Bluetooth bond shows Android's reason and a **Try again** button instead of waiting forever.
- With Location off, **Pair with computer** explains that Android's device picker needs Location before opening it. See [the device picker stays empty](how-to/troubleshoot.md#the-device-picker-stays-empty).
- Each pairing attempt removes the app's older companion-device associations for the same computer, so presence events reach the association in use.
- The home screen warns when the pairing's Keystore key is gone, for example after restoring the app's data from a backup, and asks for a new pairing.
- The home screen warns while Android applies battery optimization to the app and offers to turn it off.

See [Android companion setup](android-setup.md).

## Releases

The fork builds its releases from this repository and signs the APK with its own Android key. That certificate differs from upstream's, so replacing an upstream or debug APK requires uninstalling it and pairing again. Releases publish no separate checksum file. The installer checks each download against the SHA-256 digest GitHub reports for that asset. See [build and publish a release](contributing/releases.md).
