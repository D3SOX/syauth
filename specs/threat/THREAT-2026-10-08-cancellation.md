# Threat model: approval cancellation

Scope: PAM RPC lifetime, daemon challenge state, BLE cancellation notifications,
and Android approval/biometric lifetime. Pairing, key storage, password policy,
and OS/BlueZ remain existing boundaries. Assets are bond keys, signing keys,
challenge nonces, authentication outcomes, and availability of password unlock.
Actors include radio/relay attackers, another local account, a thief with one
device, and a process already running as the authenticated desktop user.

Trust boundaries: restricted local Unix socket; BLE bond and frame MAC; Android
app process; hardware-backed signing key. Cancellation crosses BLE only as an
authenticated v1 frame and is interpreted only after UniFFI verification.

| Element | Spoofing/tampering | Repudiation | Disclosure | Denial of service | Elevation |
|---|---|---|---|---|---|
| PAM RPC | Existing socket permissions | Cancelled outcome audited | No new secrets | EOF releases request slot | Cancel cannot grant |
| Daemon/BLE | Existing bond MAC covers marker and nonce | Cancel/timeout audit | No new identifiers | Best-effort dismissal | Cancel is terminal failure |
| Android UI | Verify MAC and match peer/nonce | Host cancellation is distinct from denial | No key export | Cancel only matching activity | Late callbacks suppressed |
| Bond store/pairing/CLI/config | Unchanged by this addition | Existing audit | Existing storage risks | Existing recovery | Existing boundaries |

Listed abuse paths:
1. Relay: cancellation does not enable a signed response; phone approval remains
   a fresh, hardware-gated gesture. Radio relay can still cause disruption.
2. Replay: an old cancellation does not match a fresh challenge nonce. Replaying
   cancellation for the same pending nonce repeats an already terminal action.
3. Pairing MitM: pairing and its numeric/OOB verification are unchanged.
4. Rogue bonding: no new pairing entry point or bond material is added.
5. PAM misconfiguration: password is a deliberate independent fallback. The
   cancellation outcome cannot become PAM success.
6. Phone theft: a cancelled prompt never uses the signing key; approval retains
   BIOMETRIC_STRONG and per-use Keystore authentication.
7. Root key extraction: inherited key-storage risks are unchanged; an already
   compromised desktop account can manipulate its own UI/authentication setup.
8. Denial of unlock: forged frames are discarded; wrong-peer/nonces cannot
   dismiss a current approval. Lost cancellation can leave UI pending, but
   cannot grant auth, and password remains usable.
9. Tracking: notification payload adds no stable identifier; UUID rotation and
   discovery remain unchanged.
10. Side channels: MAC comparison remains in existing shared crypto; no key
    comparisons or signature operations are introduced by cancellation.

Tests address active cancellation, matching nonce/MAC, failed verification,
wrong nonce, delayed activity launch, permit release, and late biometric success.
Residual risk: BLE delivery is best effort. A lost cancellation can leave the
phone UI visible; it does not keep the PAM caller or authentication alive.

| Finding | Severity | Status | Mitigation / evidence |
|---|---|---|---|
| C-001: forged or stale cancellation disrupts approval | Medium | Mitigated | UniFFI MAC verification, peer/nonce matching; Android rejection tests |
| C-002: late biometric callback responds after host cancellation | Medium | Mitigated | Terminal activity state; late-success test |
| C-003: radio loses cancellation notification | Info | Accepted residual risk | Best-effort transport can affect UI only; socket EOF still terminates auth and releases the slot |

Radio attackers can inject or relay traffic but do not possess the bond key.
Other local accounts cannot access the restricted socket. Root or a compromised
owner account already controls the deployment; cancellation adds no authority.
Phone/desktop thieves have one device but lack the other's fresh authentication.

The cancellation tests map C-001/C-002 to `BiometricPromptTest`; the real-socket
test `disconnected_pam_client_cancels_matching_phone_challenge` verifies release
of the authentication slot. C-003 is a documented delivery limitation: password
unlock and rejection of expired signatures do not depend on the notification.
