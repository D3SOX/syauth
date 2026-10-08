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

## Emulator transport test

The transport test passed on Android 15/API 35 with Emulator 37.1.11. A
userspace [Bumble peer](https://google.github.io/bumble/transports/android_emulator.html)
joined the emulator's simulated radio. The production public-key exchange and
persistent GATT client transferred fixture keys, subscribed to notifications,
received a challenge, and wrote a response. Both a BLE-only peer and a dual-mode
peer passed. The peer recorded an LE connection in each run, with no Classic
connection.

This test covers GATT transport. It does not validate numeric-comparison pairing,
Keystore signing, fingerprint approval, power consumption, or physical-radio
reconnection. The Pixel acceptance steps above cover the user-facing behavior.

Build the native AAR with the emulator's ABI using the
[Android build procedure](getting-started.md#build-and-install-android), then:

```sh
cd syauth-android
./gradlew :app:assembleDebug :app:assembleDebugAndroidTest :app:testDebugUnitTest
cd ..
```

Start an owned Android 13+ emulator with Bluetooth simulation. The tested launch
used these options with an existing API 35 AVD:

```sh
emulator -avd AVD_NAME -port 5556 -no-window -no-audio -gpu swangle \
  -no-snapshot -netsim-args '--pcap'
```

Use an available port and the emulator SDK's executable. Enable Bluetooth,
verify that its current Android user is 0, and install both APKs. Substitute its
serial for `EMULATOR_SERIAL`:

```sh
adb -s EMULATOR_SERIAL shell am get-current-user
adb -s EMULATOR_SERIAL install --user 0 -r syauth-android/app/build/outputs/apk/debug/app-debug.apk
adb -s EMULATOR_SERIAL install --user 0 -r syauth-android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
uv run scripts/ble-emulator-peer.py
```

The peer prints `READY blePeerAddress=...`. In another terminal, run the test
with that address, omitting the `/P` suffix:

```sh
adb -s EMULATOR_SERIAL shell am instrument -w -r \
  -e class com.sy.syauth.android.bg.BluetoothLeTransportTest \
  -e blePeerAddress PEER_ADDRESS \
  com.sy.syauth.android.test/androidx.test.runner.AndroidJUnitRunner
```

Require `OK (1 test)` from Android and `PASS` with exit code 0 from the peer.
Repeat with `uv run scripts/ble-emulator-peer.py --dual-mode`. Without
`blePeerAddress`, the instrumentation test skips itself. It also skips on
physical devices. The peer exits after 180 seconds if no test completes.
`uv` and Bumble are development tools; neither is needed on the laptop or Pixel
to use syauth.

## Recover stale GATT subscriptions

A Bluetooth connection does not prove that the phone has subscribed to unlock
requests. If an empty KDE submission fails immediately, inspect the daemon log:

```sh
journalctl --user -u syauth-presenced --since '5 minutes ago' --no-pager
```

`no active GATT subscription` or `notifier_slot=None` means the request could not
reach the phone. A dead notification writer causes the daemon to rebuild its
GATT service. Leave the phone in range with Bluetooth enabled and allow its
connection watchdog to retry, then submit the empty field again. On an older
app that stays connected without resubscribing, reopen the app after restarting
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
daemon rebuilds its GATT registration to recover stale subscriptions.
