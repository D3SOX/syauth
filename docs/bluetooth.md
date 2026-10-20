# Bluetooth transport and connection recovery

syauth uses Bluetooth Low Energy. The desktop advertises a GATT service, and
Android connects as its client. Both the post-bond public-key exchange and the
persistent authentication connection explicitly request `TRANSPORT_LE`.
The phone also requests LE when creating the system bond.

BLE still involves pairing and a connection. A paired laptop can appear under
Android's normal Bluetooth settings, and KDE can show the phone as connected.
That status alone does not identify the transport. Android Settings tracks
[system profile connections](https://android.googlesource.com/platform/frameworks/base/+/master/packages/SettingsLib/src/com/android/settingslib/bluetooth/CachedBluetoothDevice.java)
separately from an app's GATT link. An app can keep a BLE connection without
Android showing the device as active for audio or calls. syauth keeps its GATT
link open so the desktop can send an authentication challenge immediately.

Bluetooth audio, calls, contact sharing, and network tethering are unnecessary.
Android and BlueZ may offer these profiles because both devices also support
Classic Bluetooth. The Pixel initially had both encrypted LE and BR/EDR links
to the laptop, with the laptop active for media and calls. Disabling Media audio
and Phone calls removed the BR/EDR link while preserving encrypted LE. The
Pixel's device settings then offered "Connect" instead of showing an active
audio connection. syauth's current desktop recovery code never calls the generic
`Device1.Connect` method, which can connect multiple profiles.

See Android's [GATT transport documentation](https://developer.android.com/reference/android/bluetooth/BluetoothDevice)
and BlueZ's [device connection API](https://github.com/bluez/bluez/blob/master/doc/org.bluez.Device.rst).

## Test the Pixel without audio profiles

1. In the Pixel's Bluetooth settings, open the paired laptop's settings. Turn
   off Media audio and Phone calls if those switches are present. Keep the
   pairing and Bluetooth enabled.
2. Check that syauth still reports a connection. On the laptop,
   `sudo btmgmt con` lists controller connections and distinguishes LE from
   BR/EDR. Private addresses can differ from the saved identity address.
   The UUID list from `bluetoothctl info` lists available services, not active
   connections.
3. Run `sudo -k; sudo true` while watching the Pixel and approve with a
   fingerprint. Only test KDE after sudo succeeds.
4. With [empty-password KDE unlock](pam.md#kde-request-the-phone-with-an-empty-submission),
   lock with Meta+L. The Pixel should stay quiet until you press Enter in the
   empty password field. Approve with a fingerprint, then lock again and unlock
   with the laptop password. The password submission should keep the Pixel quiet.
5. Leave the phone idle with its screen off, then repeat sudo. Check that
   headphones remain connected throughout.

KDE may still show the phone as connected because its BLE link remains open.
Do not disable Classic Bluetooth on the entire adapter; headphones may need it.
Forgetting the laptop on the phone removes the system bond and requires pairing
again.

On 2026-10-08, the Pixel 8 Pro on Android 16 passed private PAM authentication,
`sudo -k; sudo true`, KDE fingerprint unlock, and KDE password unlock with both
audio profiles disabled. Password unlock dismissed the pending phone dialog.
The Pixel's Bluetooth diagnostics reported `ACL BR/EDR:N LE:Y` and an encrypted
LE link after fingerprint approval. The audio and call profiles stayed disabled.

An earlier APK update left a stale desktop notification writer. The daemon
rebuilt its GATT service, but the phone stayed connected without a notification
subscription. Restarting the phone service restored requests. The current client
keeps its 15-second retry watchdog active through connection, service discovery,
and notification setup. Only a successful challenge notification subscription
stops retries. Android service-change events trigger discovery and subscription
again. Callbacks from a closed connection cannot stop the new connection's retry.

On the Pixel 8 Pro with Android 16, restarting the laptop daemon sent a service
change while the BLE link stayed connected. The updated app rediscovered the
service and subscribed without a phone app restart. Private empty-password PAM
authentication also accepted a fingerprint with the updated app. JVM regression
tests cover stalled discovery, failed and successful subscriptions, service
changes, and callbacks from a closed connection. The reconnect tests run on
API 26 and 34; the service-change callback test runs on API 34.

The updated daemon also passed a first-request recovery test on that Pixel:
an empty-password PAM request started immediately after a daemon restart,
waited for the phone's subscription, and accepted a fingerprint in 2.6 seconds.
The daemon tests cover subscription recovery in the same request, a shared
eight-second deadline, cancellation during recovery, and an absent phone.

## Recovery after leaving range or restarting Bluetooth

The phone service watches Android's Bluetooth adapter state. Turning Bluetooth
off closes its GATT handles and stops retry timers. Turning it on starts the
bonded connections again without opening the app.

After a link drops, the client keeps retrying connection and notification setup.
A failed GATT open, including a null handle, leaves the 15-second watchdog armed.
Only a successful notification subscription stops retries. This cadence is a
retry interval, not a maximum time to find the desktop over the radio.

The phone clears the previous notification subscription before enabling it again.
BlueZ can retain the old subscription after a link drops even though its writer
has closed. Enabling an already enabled subscription can then appear successful
on Android while the desktop cannot send requests. Clearing and enabling it
forces a fresh subscription before the connection is considered ready.

On 2026-10-15, the Pixel on Android 16 recovered a Bluetooth off/on cycle in
about 5 seconds. With phone Bluetooth left on, the test made the laptop
peripheral unavailable for 45 seconds. After it returned, the phone reconnected
and the desktop acquired a live notification writer after about 48 seconds.
Neither check reopened the phone app or manually connected the devices.
This tests peer availability without a radio restart; it does not measure a
walk out of physical radio range or hours of phone idle time.

## Recovery after laptop suspend

The daemon selects BlueZ's current default adapter at startup. A USB controller
can return with a different index after suspend, such as `hci1` instead of
`hci0`. Removing the active adapter or losing its advertising registration now
makes the daemon exit with an error. The systemd user service retries after two
seconds and rebuilds the GATT services and advertisements from the saved bonds.
If no adapter is available yet, startup fails and systemd keeps retrying.

Inspect recovery with:

```sh
journalctl --user -u syauth-presenced --since '5 minutes ago' --no-pager
syauth status --json
```

Look for `Bluetooth session lost; restarting peripheral`, followed by
`opening Bluetooth peripheral` with the current adapter name. The peer's
`connected` field becomes `true` once the phone subscribes again. Radio discovery
can take longer than the service's restart delay. If the CLI reports the old
adapter as missing, pass the current name, for example `syauth status --adapter
hci1 --json`.

On 2026-10-16, the laptop had resumed with only `hci1` present. The old daemon
was still running against the removed `hci0` and had failed every advertising
refresh for more than 30 minutes. After installing this fix, it selected `hci1`
and the Pixel subscribed in about four seconds, without reopening the phone app.
The adapter-removal and restart sequence is covered by the private D-Bus tests;
the physical laptop was not suspended again during this check.

The regression suite uses a private D-Bus peer, without a radio. It covers an
`hci1`-only startup, removal of `hci0` followed by `hci1`, an adapter missing at
startup, and a failed advertising registration. Run it with
`cargo test -p syauth-presenced --test bluetooth_recovery`. These tests require
`dbus-daemon`, Python's `dbus` module, and PyGObject; they skip if those tools are
missing.

## Emulator transport matrix

The transport test passed on Android 15/API 35 with Emulator 37.1.11. A
userspace [Bumble peer](https://google.github.io/bumble/transports/android_emulator.html)
joined the emulator's simulated radio. The production public-key exchange and
persistent GATT client transferred fixture keys, subscribed to notifications,
received a challenge, and wrote a response. Both a BLE-only peer and a dual-mode
peer passed. The peer recorded an LE connection in each run, with no Classic
connection.

Use a disposable Android 13+ emulator with Bluetooth netsim support, a full
JDK 17 or 21 installation, the Android SDK, `adb`, and `uv`. The existing native
AAR must include the emulator's ABI; `make android-aar` builds it when needed.

```sh
cd syauth-android
./gradlew :app:testDebugUnitTest :app:assembleDebug :app:assembleDebugAndroidTest
cd ..
```

Create an owned AVD rather than using a personal phone or an existing user's AVD.
For example, start the SDK emulator with an available even-numbered port:

```sh
emulator -avd SYAUTH_TEST_AVD -port 5556 -no-window -no-audio \
  -gpu swangle -feature -Vulkan -no-snapshot -netsim-args '--pcap'
adb -s emulator-5556 shell cmd bluetooth_manager enable
adb -s emulator-5556 install --user 0 -r syauth-android/app/build/outputs/apk/debug/app-debug.apk
adb -s emulator-5556 install --user 0 -r syauth-android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
SYAUTH_BLE_EMULATOR_SERIAL=emulator-5556 cargo test --test bt_matrix -- --ignored --nocapture
```

The runner requires an emulator serial, verifies its emulator identity and
Android user 0, then starts the pinned Bumble peer with BLE-only and dual-mode
configurations. Each case must exchange both fixture keys, receive a notification,
and write the expected response over LE. It requires `OK (1 test)`, rejects a
skipped instrumentation test, and checks the peer's independent `PASS` and exit
status. It stops only the fixture processes it starts. If `uv` selects an
unsuitable Python environment, set `UV_PYTHON` to an installed Python executable.

These cases exercise GATT transport with synthetic fixture bytes. They do not
qualify numeric comparison, Keystore signing, biometrics, power consumption, or
physical-radio recovery. The matrix is explicitly ignored by the ordinary
workspace suite; the explicit command above runs it without accepting skips.

## Recover stale GATT subscriptions

A Bluetooth connection does not prove that the phone has subscribed to unlock
requests. If an empty KDE submission fails immediately, inspect the daemon log:

```sh
journalctl --user -u syauth-presenced --since '5 minutes ago' --no-pager
```

The current daemon logs `waiting for phone notification subscription` when the
phone is not ready and retries the same challenge while the phone subscribes
again. It uses standard BlueZ notifications and keeps its GATT registration when
a notification session closes (BUG-20261018-1736); look for
`notification session closed; awaiting re-subscribe`. Recovery
and fingerprint approval share the original eight-second authentication deadline;
recovery does not extend that deadline. Cancellation stops the pending request.

If the BLE link itself has disconnected, reconnecting can take longer than eight
seconds. Leave the phone in range with Bluetooth enabled, allow its connection
watchdog to retry, then submit the empty field again. You can use the laptop
password after a phone request times out.

Older daemons fail immediately with `no active GATT subscription` or
`notifier_slot=None`. Update both the daemon and Android app. On an older app
that stays connected without resubscribing, reopen the app after restarting
the daemon:

```sh
systemctl --user restart syauth-presenced
```

The [pacman update checker](pam.md#check-the-setup-after-pacman-updates) checks
installed PAM files, package versions, and module dependencies. It does not test
the current Bluetooth connection or phone approval. A passing check does not
rule out a stale subscription, and reconnecting the phone does not require a new
update-check baseline.

The desktop daemon reconnects only the phone explicitly configured through
`SYAUTH_RECONNECT_DEVICE`. Leave it unset to disable forced reconnection;
headphones, keyboards, and other devices remain connected.

After pairing, set the Pixel's bonded BlueZ address in a systemd user drop-in:

```ini
[Service]
Environment=SYAUTH_RECONNECT_DEVICE=AA:BB:CC:DD:EE:FF
```

Reload the user manager and restart `syauth-presenced` after changing this
configuration. The configured phone may disconnect and reconnect when the
daemon rebuilds its GATT registration, for example after adding a bond.

## Pairing troubleshooting

If Android reports `host-pubkey read failed status=1` while the desktop
already lists an active peer, update the companion app. Pairing reads the
desktop key first, then sends the phone key. Sending the phone key commits
pairing and permits the daemon to replace the pair service with its unlock
service. Repeating the exchange after that transition uses invalid handles.

If `syauth status --json` shows no peers, check `syauth list`: revoked records
are retained for audit and cannot authenticate. Complete fresh pairing.
Revoke access with `syauth revoke --id <peer_id>`.

Regression coverage: PairGattOrderTest and RealPairBackendRuntimeTest verify
service replacement ordering and duplicate callback handling without radio I/O.

Open the desktop pairing window with `syauth pair --waybar --force` before
selecting Pair with computer on Android. Confirm matching codes on both sides
within the pairing deadline. Done refreshes the home card and starts the unlock
connection immediately; reopening the app also loads the persisted bond.
