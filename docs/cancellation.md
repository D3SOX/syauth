# Approval cancellation

KDE can run its password and biometric PAM services in parallel. When the
password succeeds, KDE terminates the outstanding biometric worker. The daemon
observes EOF on that worker's RPC socket, dismisses the matching phone request,
and releases the per-peer challenge slot. Deadline expiry also dismisses an
unanswered request.

The existing v1 frame format remains `[version:1][nonce:16][payload:N][tag:16]`.
An empty payload requests approval. ASCII `cancel` dismisses the request with
the same nonce. The cancellation carries the same bond-key BLAKE3 MAC as the
challenge. Android verifies the complete frame through UniFFI before acting
on its payload. Unknown payloads and failed verification are ignored.

Cancellation matches both the bonded peer and the current request nonce. It
cancels the BiometricPrompt, closes the approval activity, and suppresses late
biometric callbacks. It never signs a frame or grants authentication. The most
recent cancellation remains available to an activity launched after the
cancellation arrives, covering notification/activity scheduling races.

On Arch KDE, preserve `/usr/lib/pam.d/kde` as the normal password service and
place phone authentication in an override of `/usr/lib/pam.d/kde-fingerprint`.
An optional `pam_echo.so` message before `pam_syauth.so` tells KDE that the
biometric service presented a prompt. Keep existing mandatory checks and the
existing laptop fingerprint fallback.

Validation: `challenge_flow` exercises real Unix-socket EOF, verifies the
cancellation nonce and MAC, then authenticates another challenge. Android
activity tests cover cancellation during biometrics, a late success callback,
wrong nonce, failed verification, and cancellation before activity launch.

Bug: [Pending approval survives password unlock](../specs/bugs/BUG-2026-10-08-cancel-approval.md).
