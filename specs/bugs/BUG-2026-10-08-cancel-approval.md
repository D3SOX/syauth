# Pending Pixel approval survives password unlock

Observed on nico-laptop: KDE unlock succeeds through its password service while
the parallel kde-fingerprint PAM worker has an outstanding phone request. The
Pixel approval remains open. `server.rs::handle_connection` awaits dispatch
without observing client EOF; the Android activity has no host-cancel path.

Keep the existing v1 frame format. Empty payload means challenge; the literal
ASCII payload `cancel` means cancellation of the same nonce. Both carry the
existing bond-key MAC. Cancellation never produces an authentication success.

Acceptance:
- Closing a PAM RPC client sends a MAC-authenticated cancellation for its nonce.
- Deadline expiry also dismisses the expired approval.
- The per-peer challenge permit is released after cancellation.
- Android verifies the MAC before interpreting the cancellation payload.
- Only the matching peer and nonce are dismissed; unrelated and forged frames
  cannot close an approval.
- Cancel the active BiometricPrompt and ignore late callbacks after host cancel.
- Real KDE password unlock dismisses the Pixel prompt; Pixel fingerprint still
  unlocks KDE and sudo.
