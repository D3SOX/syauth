# Bluetooth connection recovery

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
