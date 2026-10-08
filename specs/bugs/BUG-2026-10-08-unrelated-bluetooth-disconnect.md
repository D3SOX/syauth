# Daemon startup disconnects unrelated Bluetooth devices

Starting the user daemon on Nico's laptop disconnected the connected
Px7 S2e headphones. Its journal recorded `kick_connected_peers: disconnected
stale peer` for the headphones' address, and `bluetoothctl info` confirmed
`Connected: no`. Stopping the daemon and reconnecting the headphones restored
the original connection.

`PersistentPeripheral::kick_connected_peers` enumerated all devices on the
adapter and disconnected every connected device after GATT registration.
Limit recovery to the phone explicitly configured through
`SYAUTH_RECONNECT_DEVICE`. With no configured address, disconnect nothing.
Malformed configuration returns an error without touching other devices.

Verification includes the address-selection tests and checking that the
headphones remain connected across startup and restart of the corrected
daemon on the laptop. The real phone's reconnect and unlock checks verify
that recovery still works for the configured Pixel.
