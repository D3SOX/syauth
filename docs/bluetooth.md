# Bluetooth transport and connection recovery

syauth uses Bluetooth Low Energy. The desktop advertises a GATT service, and
Android connects as its client. Both the post-bond public-key exchange and the
persistent authentication connection explicitly request `TRANSPORT_LE`.
The phone also requests LE when creating the system bond.

BLE still involves pairing and a connection. A paired laptop can appear under
Android's normal Bluetooth settings, and KDE can show the phone as connected.
That status alone does not identify the transport. The app keeps its GATT link
open so the desktop can send an authentication challenge immediately.

Bluetooth audio, calls, contact sharing, and network tethering are unnecessary.
Android and BlueZ may offer these profiles because both devices also support
Classic Bluetooth. In the tested Pixel setup, BlueZ exposed separate A2DP and
AVRCP objects for the phone. This observation does not establish which process
opened them. syauth's current desktop recovery code never calls the generic
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
4. Lock KDE with Meta+L and approve on the phone. Then repeat using the laptop
   password and check that the phone dialog closes.
5. Leave the phone idle with its screen off, then repeat sudo. Check that
   headphones remain connected throughout.

The phone may still appear as connected after disabling audio profiles because
its BLE link remains open. Do not disable Classic Bluetooth on the entire
adapter; headphones may need it. Forgetting the laptop on the phone removes the
system bond and requires pairing again.

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
