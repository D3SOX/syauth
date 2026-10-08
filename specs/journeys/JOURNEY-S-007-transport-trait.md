# JOURNEY-S-007: `syauth-transport`, `BtPeer` trait + in-process mock

## Roadmap link
- Source roadmap: [specs/syauth/ROADMAP.md §S-007](../syauth/ROADMAP.md)
- Feature: async `BtPeer` / `Session` trait pair plus a configurable in-process
  `MockBtPeer` for end-to-end testing without real BlueZ radios.

## 1. Journey

When I am the engineer wiring `syauth-pam` (S-008/S-009) into the rest of the
stack, I want a single async trait pair (`BtPeer`, `Session`) whose only
v0.1 implementation is an in-process `MockBtPeer` driven by `tokio::sync::mpsc`
channels and a typed `MockScenario` enum, so I can exercise every one of
the nine mandatory SPEC §4.3 e2e scenarios end-to-end before a single byte of
`bluer` code lands in S-010.

## 2. CJM

The downstream user is the future maintainer of `syauth-pam::auth` (the
`pam_sm_authenticate` body) and of the integration tests under `tests/`. They
need to assert PAM return codes for golden / offline / slow / replay / wrong-
version / reordered behaviors without owning a real Bluetooth radio. The
roadmap deliberately ships S-007 *before* S-010 so that the PAM tests in S-009
have a hermetic, deterministic peer they can swap in via `OnceLock<Box<dyn
BtPeer>>`. This journey delivers the trait API, the typed error enum, and a
mock peer whose every behavior is parametrized by a `MockScenario` variant that
maps 1-to-1 to a SPEC §4.3 e2e scenario row.

### Scenario mapping (SPEC §4.3 ↔ `MockScenario`)

| SPEC §4.3 row | `MockScenario` variant | Observable behavior at the trait API |
|--------------|------------------------|------------------------------------------|
| golden: ≤ 2 s success | `Golden` | `send_frame` is accepted; `recv_frame` returns the request's frame with the payload XORed by a constant, a deterministic, non-trivial echo proving the test data made the round trip. |
| peer offline: `PAM_AUTHINFO_UNAVAIL` ≤ 1.2 s | `Offline` | `connect()` returns `Err(TransportError::Unreachable)` immediately. |
| peer denies: `PAM_AUTH_ERR` | (modeled in `syauth-core` once the bond-store / sign layers land; S-007 only owns transport-level errors. The mock surfaces denial as a `Reordered` or wire-level corrupt frame via S-009 glue.) |, |
| replay (resend prior response): `PAM_AUTH_ERR` | `Replay { duplicate_count }` | The mock emits the same frame `duplicate_count + 1` times in sequence; the upper-layer replay cache (S-003) is what rejects, but the transport is the one that delivers the duplicate. |
| bad signature: `PAM_AUTH_ERR` | (lives in `syauth-core::sign`, S-004; not transport-level.) |, |
| wrong version: `PAM_AUTH_ERR` | `WrongVersion { injected_version }` | The mock mutates the first byte of the frame the central sends, the byte the `Frame::decode` layer in S-002 keys off, to `injected_version`, producing a `FrameError::BadVersion` at the receiver. |
| revoked peer: never goes to radio; `PAM_AUTH_ERR` | (revocation is a bond-store check that bypasses the transport entirely; not represented here.) |, |
| MTU split frame: reassembled and succeeds | `Reordered` | The mock buffers the first inbound frame and emits the second one *before* the first; the upper layer must reassemble or reject. (`Reordered` is the cleanest minimal model of fragmentation reordering at the trait API, the actual MTU-split test in S-010 will use real `bluer` fragments.) |
| panic in core: `catch_unwind` boundary catches | (lives in `syauth-pam::entry`; not transport-level.) |, |
| additional `/bt` matrix row. slow peer (>budget) → `PAM_AUTHINFO_UNAVAIL` over budget | `Slow { delay }` | `recv_frame` waits `delay` before reading from the channel. The caller's `timeout` is shorter than `delay`, so the caller observes `TransportError::Timeout` before `delay` elapses. |

Note: S-007 owns the *transport-layer* mock matrix. The seven rows above with
", " are mitigated above the transport seam (signature, replay cache, bond-store
revocation, PAM `catch_unwind`). S-009 stitches them together; this step only
ships the trait + the six `MockScenario` variants documented in the DoD.

### Phase 1: define the seam

User intent. Declare the smallest async API that lets the PAM module
drive a roundtrip with a single phone, `connect → send_frame → recv_frame`.

Actions.
- Create `crates/syauth-transport/src/{lib.rs,error.rs,mock.rs}`.
- In `lib.rs`, declare `BtPeer` (returns a boxed `Session`) and `Session`
  (`send_frame` + `recv_frame`). Both are `Send + Sync` and use
  `#[async_trait::async_trait]`.
- Add `syauth-core = { path = "../syauth-core" }` so the trait can speak in
  terms of `syauth_core::Frame` and `syauth_core::FrameError`.

Pain / risk.
- A leaky trait signature (e.g. exposing `tokio::net::TcpStream` or a `bluer`
  type) would force S-010 to re-wrap or break the API. Mitigated by
  having only `Frame` and `Duration` cross the trait boundary.
- Forgetting `Send + Sync` would make the PAM module unable to hold the peer
  in a `OnceLock`. Mitigated by declaring it on both traits.
- Returning a non-boxed `Session` would couple the trait to a concrete
  associated type and prevent `dyn BtPeer` use. Mitigated by `Box<dyn
  Session>`.

Success signal. `cargo check -p syauth-transport` succeeds with the trait
declared and an empty mock.

### Phase 2: typed error types

User intent. Give the PAM module exactly enough error variants to map onto
PAM return codes without losing information.

Actions. Declare `TransportError` in `error.rs` with the six variants
`Timeout`, `Unreachable`, `Closed`, `BadFrame(FrameError)`, `WrongVersion(u8)`,
`Replay`. Each variant carries the minimum data the test or the PAM layer
needs to log it.

Pain / risk.
- A `String` error type would force callers to substring-match, fragile.
  Mitigated by an enum.
- Conflating `Timeout` and `Unreachable` would lose the distinction between
  "peer doesn't answer fast enough" and "peer not on the air at all".
  Mitigated by separate variants; the `Slow` mock test asserts `Timeout` and
  the `Offline` mock test asserts `Unreachable`.

Success signal. Negative test cases assert specific `TransportError`
variants by structural equality.

### Phase 3: mock peer

User intent. Make the six `MockScenario` variants behave per the table
above, with every parameter exposed as a named module-level constant.

Actions.
- Define `MockScenario` enum with variants
  `Golden | Offline | Slow { delay } | Reordered | Replay { duplicate_count } | WrongVersion { injected_version }`.
- Module-level consts: `MOCK_CHAN_CAP`, `SLOW_DEFAULT_DELAY`,
  `WRONG_VERSION_DEFAULT`, `REPLAY_DEFAULT_DUPLICATES`,
  `GOLDEN_PAYLOAD_XOR_MASK`, `REORDERED_BUFFER_DEPTH`. Every magic number a
  test would otherwise hand-type.
- `MockBtPeer::expect(MockScenario)` is the only constructor. The peer's
  internal state is an `Arc<Mutex<…>>` over a small buffer plus the scenario;
  the channel is built lazily in `connect()`.

Pain / risk.
- `std::thread::sleep` inside an async fn would freeze the runtime. Mitigated
  by using `tokio::time::sleep` everywhere.
- Tests pinning real wall-clock duration are flaky. Mitigated by making each
  test assert a *bound* (e.g. wall-clock ≤ `TIMEOUT_BUDGET_MULT * timeout`)
  rather than an exact value, and by keeping the timeouts in the 5–50 ms
  range so even a heavily-loaded CI runner clears them.
- The `Reordered` scenario could deadlock if both directions block. Mitigated
  by buffering inside `Session::recv_frame` and emitting from the buffer on
  the next call.

Success signal. One `#[tokio::test]` per scenario, all green.

### Phase 4: golden roundtrip

User intent. Prove end-to-end that the trait + mock are wired correctly by
sending a frame and observing a deterministic response.

Actions. Build a `MockBtPeer::expect(MockScenario::Golden)`, `connect()`,
`send_frame(req)`, `recv_frame(timeout)`. Assert the returned frame has the
same nonce, same tag, and payload `req.payload XOR GOLDEN_PAYLOAD_XOR_MASK`.
Wall-clock budget: `< GOLDEN_ROUNDTRIP_BUDGET` (= 100 ms).

Pain / risk.
- Forgetting to assert wall-clock would let an accidental `tokio::time::sleep`
  slip into the success path. Mitigated by an explicit `Instant::now()`
  bracket.

Success signal. `golden_roundtrip_decodes_xor_echo_within_budget` passes.

### Phase 5: negative-path tests

User intent. Lock in the timeout / offline / wrong-version / replay /
reordered behaviors.

Actions. One `#[tokio::test]` per remaining variant. Each test sets a
`SHORT_CALLER_TIMEOUT` (= 30 ms) and asserts:

- `Offline` → `connect()` returns `Err(TransportError::Unreachable)`.
- `Slow { delay = MOCK_SLOW_DELAY (200 ms) }` → `recv_frame(SHORT_CALLER_TIMEOUT)`
  returns `Err(TransportError::Timeout)` *and* wall-clock ≤
  `TIMEOUT_BUDGET_MULT * SHORT_CALLER_TIMEOUT` (so the caller's timeout
  triggered, not `delay`).
- `WrongVersion { injected_version: 0x02 }` → `recv_frame` returns
  `Err(TransportError::BadFrame(FrameError::BadVersion(0x02)))`.
- `Replay { duplicate_count: 1 }` → calling `recv_frame` twice yields the
  same frame both times (the transport delivers the duplicate; the upper
  layer is the one that rejects it).
- `Reordered` → two sent frames come back in reverse order.

Pain / risk.
- Reading wall-clock with `std::time::Instant::now()` and comparing to a
  millisecond budget is exactly the kind of thing that flakes on a noisy CI.
  Mitigated by generous `TIMEOUT_BUDGET_MULT` (= 6× the caller timeout, so
  30 ms × 6 = 180 ms, still under `delay` = 200 ms, proving the test
  distinguishes them).
- Forgetting that `recv_frame` *returns* an error rather than panicking would
  let an unwrap creep in. Mitigated by `assert!(matches!(err,
  TransportError::Timeout))`.

Success signal. Six tests pass; `make lint` / `make test` exit 0.

### Friction and opportunity

| Friction | Phase | Opportunity |
|----------|-------|-------------|
| The PAM module would otherwise need real BlueZ to test | 1–5 | Mock-first development; S-009 wires the same trait, real radio arrives in S-010 |
| `bluer` types could leak through the trait | 1 | Trait speaks only `Frame`, `Duration`, and `TransportError` |
| Wall-clock flake risk in timeout tests | 5 | `TIMEOUT_BUDGET_MULT` is generous; tested ranges (30 ms / 200 ms) leave 6× headroom |
| Hand-rolled magic numbers | 3 | Every scenario parameter is a `const` at module top |

### Expected outcome

A PAM-module author imports `syauth_transport::{BtPeer, Session,
MockBtPeer, MockScenario}` and installs
`MockBtPeer::expect(MockScenario::Golden)` in a `OnceLock`. The same calling
code that will later use `BlueZBtPeer` passes the end-to-end tests. Only the
mock uses `tokio::time::sleep`, only tests use `unwrap`, and this step adds
no `bluer` dependency. The six scenarios match the SPEC §4.3 test matrix
needed by S-009.


## 3. UX implementation and assessment

### Time to first value
- [x] One `use syauth_transport::*;` and one `MockBtPeer::expect(...)` call is
       enough to drive a full roundtrip.

### Onboarding clarity
- [x] `MockScenario` variants are self-documenting and map to SPEC §4.3 rows.
- [x] Each `TransportError` variant carries the data needed to log it.

### Production-ready defaults
- [x] Constants `MOCK_CHAN_CAP`, `SLOW_DEFAULT_DELAY`, etc., are documented
       inline.
- [x] `connect` and `recv_frame` accept an explicit `timeout: Duration`,        there is no implicit one.

### Success path checks
- [x] `MockScenario::Golden` roundtrip completes in < `GOLDEN_ROUNDTRIP_BUDGET`
       (100 ms) on every supported runner.

### Decision load
- [x] The caller chooses scenario, timeout, and frame contents. Everything
       else is fixed.

### Progressive complexity
- [x] Public API: two traits (`BtPeer`, `Session`), one mock impl, one
       error enum, one scenario enum. No additional types.

### Error quality
- [x] `TransportError::Timeout` distinguishes the caller's deadline from
       `Unreachable` (peer not on the air).
- [x] `BadFrame(FrameError)` re-uses the upstream typed error verbatim, no
       string substitutions.

### Failure safety
- [x] `unsafe_code = "deny"` inherited from workspace.
- [x] No `unwrap`/`expect` outside `#[cfg(test)]`.
- [x] `tokio::time::sleep` in mock, never `std::thread::sleep`, so
       `tokio::time::pause()` could drive deterministic tests in future.

### Runtime transparency
- [x] Wall-clock bound is asserted in the `Slow` test (`≤
       TIMEOUT_BUDGET_MULT * SHORT_CALLER_TIMEOUT`).

### Debuggability
- [x] `TransportError` derives `Debug`, `PartialEq`, `Eq`, and uses
       `thiserror::Error`.
- [x] `MockScenario` derives `Debug`, `Clone`.

### Consistency across interfaces
- [x] The same trait will be implemented by `BlueZBtPeer` in S-010.

### Workflow consistency
- [x] Tests live in `#[cfg(test)] mod tests` alongside `mock.rs`, per AGENTS.md.

### Change safety
- [x] Adding a new `MockScenario` variant is additive; existing tests stay
       green.

### Experimentation safety
- [x] All side effects are in-process; no real radio is ever touched.

### Interaction latency
- [x] `Golden` scenario: < 100 ms wall-clock.

### Developer feedback speed
- [x] Six `#[tokio::test]` cases run in ≤ 500 ms total on a laptop.

### Team scale
- [x] Trait + mock under 250 lines combined; reviewable in one sitting.

### System scale
- [x] Channel capacity (`MOCK_CHAN_CAP` = 16) bounded; no unbounded buffers.

### Right behavior by default
- [x] No "trust me" entry point; `MockBtPeer::expect(...)` is the only
       constructor.

### Anti-bypass design
- [x] No way to construct a `MockBtPeer` that ignores `MockScenario`, the
       scenario is the only configuration knob.

## 4. Tests

### TC-01: golden roundtrip decodes XOR echo within budget

Given a `MockBtPeer::expect(MockScenario::Golden)`.
When the caller connects, sends a frame with a non-trivial payload, and
calls `recv_frame(GOLDEN_RECV_TIMEOUT)`.
Then the returned frame's payload equals the request payload XORed with
`GOLDEN_PAYLOAD_XOR_MASK`, and the total wall-clock is < `GOLDEN_ROUNDTRIP_BUDGET`
(100 ms).

### TC-02: offline returns unreachable

Given a `MockBtPeer::expect(MockScenario::Offline)`.
When the caller calls `connect(...)`.
Then the call returns `Err(TransportError::Unreachable)`.

### TC-03: slow peer times out before delay elapses

Given a `MockBtPeer::expect(MockScenario::Slow { delay: MOCK_SLOW_DELAY })`
(`MOCK_SLOW_DELAY` = 200 ms).
When the caller connects, sends a frame, and calls `recv_frame(timeout =
SHORT_CALLER_TIMEOUT)` (30 ms).
Then the call returns `Err(TransportError::Timeout)` *and* the observed
wall-clock is ≤ `TIMEOUT_BUDGET_MULT * SHORT_CALLER_TIMEOUT` (180 ms, proves
the caller's timeout fired, not the mock's delay).

### TC-04: wrong-version mutates first byte and yields BadFrame

Given a `MockBtPeer::expect(MockScenario::WrongVersion { injected_version:
WRONG_VERSION_DEFAULT })` (= 0x02).
When the caller sends a frame and `recv_frame(timeout)`.
Then the call returns `Err(TransportError::BadFrame(
FrameError::BadVersion(WRONG_VERSION_DEFAULT)))`.

### TC-05: replay emits the same frame N times

Given a `MockBtPeer::expect(MockScenario::Replay { duplicate_count: 1 })`.
When the caller sends one frame and calls `recv_frame` twice.
Then both calls return `Ok(frame)` and the two frames are byte-equal.

### TC-06: reordered swaps two successive frames

Given a `MockBtPeer::expect(MockScenario::Reordered)`.
When the caller sends frame A then frame B, then calls `recv_frame` twice.
Then the first `recv_frame` returns frame B and the second returns frame
A.

## Traceability
- Roadmap item: [specs/syauth/ROADMAP.md §S-007](../syauth/ROADMAP.md#step-s-007-syauth-transport-btpeer-trait--in-process-mock)
- Implementation files: `crates/syauth-transport/src/lib.rs`,
  `crates/syauth-transport/src/error.rs`,
  `crates/syauth-transport/src/mock.rs`,
  `crates/syauth-transport/Cargo.toml`
- Test files: `crates/syauth-transport/src/mock.rs` `#[cfg(test)] mod tests`
