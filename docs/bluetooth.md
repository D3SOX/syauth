# Bluetooth pairing troubleshooting

The desktop advertises; the phone connects using LE Secure Connections.
Keep the devices nearby and compare the numeric code before accepting a bond.
Unlocks require approval on the phone for each challenge.

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

## Reconnecting an existing phone

Returning into range uses the stored bond; do not run pairing again. The updated
companion service closes its GATT handle when Bluetooth is disabled and starts
the same owned client immediately when Bluetooth is enabled. Setup retries stay
active through service discovery and notification subscription, rather than
stopping at the first connection callback. Retries pause while the radio is off.

A nearby-phone radio cycle measured approximately 8 seconds to subscription
after this repair, versus 22 seconds before. These are individual observations,
not a guaranteed latency. Physical leave-and-return and Doze need separate
qualification. Android and radio scheduling still affect reconnection.

Inspect both sides when recovery stalls:

```sh
adb logcat -s syauth.bg.persistent
journalctl --user -u syauth-presenced --since '5 minutes ago'
```

On the phone, `descriptor write status=0` for UUID
`00002902-0000-1000-8000-00805f9b34fb` means notification subscription succeeded.
The desktop should log `phone subscribed`. A desktop `cached writer dead`
followed by `rebuilding GATT application` identifies the remaining desktop
recovery problem; repeated pairing does not repair that lifecycle.
The desktop repair in BUG-20261018-1736 instead logs
`notification session closed; awaiting re-subscribe` and retains its GATT
registration. Confirm which daemon build is running when comparing these logs.
`last_connect_ms_ago` currently records a challenge timestamp, not actual
Bluetooth readiness.

The [recovery design investigation](../specs/frds/FRD-20261018-recovery.md)
records the desktop registration, pairing confirmation, CDM association, and
observability changes still needed, with a qualification matrix.
