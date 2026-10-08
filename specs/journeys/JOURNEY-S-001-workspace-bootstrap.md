# JOURNEY-S-001: workspace bootstrap & CI lint pipeline

## Roadmap link
- Source roadmap: [specs/syauth/ROADMAP.md](../syauth/ROADMAP.md)
- Feature: S-001, Workspace bootstrap & CI lint pipeline

## 1. Journey

When a new contributor (or follow-up roadmap item S-002..S-021) lands in the syauth repo with the spec already accepted I want to clone, run `make build && make test && make lint` once and see all five Cargo crates, the `libpam_syauth.so` cdylib, the Gradle placeholder, and a green CI so I can start implementing the protocol, transport, PAM module, CLI and mobile crate against a required scaffold instead of bikeshedding workspace layout.

## 2. CJM

Today the repo holds only `AGENTS.md`, the promptkit-generated `clippy.toml`, `rustfmt.toml`, and a `Makefile` whose `build` target points at a non-existent `--bin syauth`. Every downstream roadmap item (S-002 framing, S-007 transport, S-008 PAM, S-014 mobile) assumes a Cargo workspace mirroring `~/sources/prrr`: a top-level package plus a `crates/` directory and a `syauth-android/` Gradle module. Defining that layout once lets the remaining 21 steps use consistent crate names, formatting, and CI checks.

### Phase 1: layout decided & dirs materialised

User intent. Have the canonical syauth workspace tree on disk so every later step can `cd crates/syauth-X` and start writing code.

Actions.
- Read SPEC §4.1 (workspace layout) and the prrr Cargo.toml/Makefile.
- Create `crates/syauth-core/`, `crates/syauth-transport/`, `crates/syauth-pam/`, `crates/syauth-cli/`, `crates/syauth-mobile/`, `syauth-android/` with placeholder `Cargo.toml` and `src/lib.rs` (or `src/main.rs` for the CLI) per crate.
- Add the workspace `Cargo.toml` at the repo root listing all five member crates.

Pain / risk.
- Pick names that drift from SPEC (e.g. `syauth_core` vs `syauth-core`) and break later doc links.
- Forget to mark `syauth-pam` as `cdylib` with `name = "pam_syauth"` so `libpam_syauth.so` never lands in `target/release/`.
- Accidentally introduce a `[lib]` that defaults to rlib for the PAM crate, causing every downstream PAM symbol test to fail mysteriously.

Success signal. `ls crates/` shows the five crates; `ls syauth-android/` shows the Gradle placeholder; `cargo metadata --no-deps --format-version=1 | jq '.packages | length'` returns 6 (5 crates + top-level).

### Phase 2: build, test, lint, audit, deny all green

User intent. Have one command per quality gate that returns 0 on a clean tree, so CI can be a thin wrapper.

Actions.
- Extend (do not replace) the existing `Makefile` so `make build` does `cargo build --release --workspace` (and produces `target/release/libpam_syauth.so`), `make test` runs `cargo test --workspace`, `make lint` runs clippy+fmt+audit+deny, `make fmt` formats, `make audit` runs `cargo audit`.
- Add `deny.toml` with denied advisories, a permissive license allow-list (MIT, Apache-2.0, BSD-{2,3}-Clause, ISC, Unicode-DFS-2016, Zlib, MPL-2.0), and an empty bans list.
- Write a single integration test `tests/workspace_smoke.rs` asserting `1 + 1 == 2` so `cargo test --workspace` exercises the workspace path.

Pain / risk.
- `cargo audit` finds a transient CVE in a transitive of one of the placeholders and breaks CI. Mitigate by making `audit` non-fatal in `make lint` (mirrors prrr Makefile line 73).
- `cargo deny check` rejects a license we forgot to allow. Mitigate by mirroring the prrr-comparable allow-list and running once locally before declaring done.
- Workspace inheritance of `[lints]` is fragile pre-Rust-1.74, but our toolchain is 1.85+ per prrr, so we use the `[workspace.lints]` pattern that landed in 1.74.

Success signal. `make build && make test && make lint` exit 0; `cargo deny check` exits 0; `ls target/release/libpam_syauth.so` shows the file.

### Phase 3: CI runs the same gates on every push

User intent. Catch a clippy regression in any future PR before review, on stable Rust on Ubuntu, with cached `target/`.

Actions.
- Add `.github/workflows/ci.yml` that on push and pull_request: checks out, installs stable Rust + clippy + rustfmt, installs `cargo-audit` and `cargo-deny`, restores the cargo cache, runs `make lint` then `make test`.

Pain / risk.
- Network access for `cargo install cargo-deny` in CI is slow (~3 min on cold cache). Mitigate by using `taiki-e/install-action` for binary install (~5 s) instead of `cargo install`.
- Forget to specify the `cdylib` link dependencies (`libpam0g-dev` on Debian) and the build fails. Mitigate: we do not link PAM C headers in S-001, the placeholder cdylib does not include `pam-sys`, so no apt install is needed at this step. We will revisit in S-008.

Success signal. A push to a branch triggers a green CI run; a deliberate `let unused = 1;` in any crate turns the run red on clippy.

### Friction and opportunity

| Friction | Phase | Opportunity |
|----------|-------|-------------|
| Existing Makefile has a `--bin syauth` target that doesn't exist | 2 | Replace the build line with `cargo build --release --workspace`; keep the rest of the Makefile intact |
| The promptkit-generated header says "do not edit" | 2 | Extend with our own targets after the generated block, Make happily accepts duplicate targets only if we redefine them; safer to comment that the new section is hand-maintained and rerunning promptkit would clobber it |
| prrr has no `deny.toml` or CI workflow to copy from | 2-3 | Author from scratch using cargo-deny default template, calibrated to the prrr crate's licenses |

### Expected outcome

A contributor clones syauth and runs `make build && make test && make lint`.
The commands compile one cdylib, four library crates, and one CLI. The tests
pass, clippy reports no warnings, and `cargo deny check` passes. GitHub
Actions runs the same commands on the PR. Later roadmap items use the
established `crates/syauth-X/` layout.


## 3. UX implementation and assessment

### Time to first value
- [x] `make build` from a clean clone in under 60 s on a developer laptop (placeholder crates compile fast).
- [x] First-run lint completes in under 30 s.

### Onboarding clarity
- [x] `make help` lists the five quality-gate targets with one-line descriptions.
- [x] `deny.toml` has comments explaining each allow/deny block.

### Production-ready defaults
- [x] `cargo audit` is non-fatal by default in `make lint` (matches prrr); a sibling `make audit` target is fatal for explicit checks.
- [x] `make lint` runs clippy with `-D warnings` so no warning is ever silently merged.

### Success path checks
- [x] `tests/workspace_smoke.rs` proves `cargo test --workspace` exercises the workspace, including all member crates.
- [x] `ls target/release/libpam_syauth.so` succeeds, proves the cdylib crate-type resolves correctly even before any PAM symbol exists.

### Decision load
- [x] Member-crate names are fixed by SPEC §4.1; no choice of crate names.
- [x] License allow-list is derived from the established prrr crate's transitive dep set.

### Progressive complexity
- [x] Placeholder lib.rs is empty (`//! placeholder for S-002` doc comment only) so downstream items start from a clean slate.
- [x] No business code lands in S-001, the only Rust expression is the `assert_eq!(1 + 1, 2)` smoke test.

### Error quality
- [x] `make lint` prints which phase failed (clippy, fmt, audit, deny) on the line above the failure.
- [x] CI failure on clippy points at the offending file:line via the standard rustc diagnostic.

### Failure safety
- [x] Extending (not rewriting) the Makefile preserves any future promptkit regeneration.
- [x] No file under `docs/`, `specs/`, `.agents/`, `.claude/`, `.promptkit*` is touched.

### Runtime transparency
- [x] Every `make` target echoes the cargo command before running it.

### Debuggability
- [x] CI uploads the `target/` cache on success only, failed runs fall back to stderr.

### Consistency across interfaces
- [x] Crate names match SPEC §4.1 verbatim: `syauth-core`, `syauth-transport`, `syauth-pam`, `syauth-cli`, `syauth-mobile`.
- [x] Workspace `edition = "2024"` matches AGENTS.md and prrr.

### Workflow consistency
- [x] Makefile target names match prrr: `build`, `test`, `testv`, `lint`, `fmt`, `audit`, `bench`, `clean`.

### Change safety
- [x] No `unsafe` is introduced in any crate. The PAM crate is a `cdylib` with `lib.rs` containing only a doc comment.

### Experimentation safety
- [x] All placeholder crates are publishable to a local registry without exposing any API (no `pub` items).

### Interaction latency
- [x] `cargo test --workspace` on a clean tree under 5 s (only one test).

### Developer feedback speed
- [x] `make lint` short-circuits on the first failing tool (clippy → fmt → audit → deny) so the first error is the first thing the developer sees.

### Team scale
- [x] `Cargo.lock` is committed for reproducible builds.
- [x] `deny.toml` is the shared definition for license policy.

### System scale
- [x] Adding a new crate later is `mkdir crates/syauth-X && cargo init --lib crates/syauth-X` + one line in workspace members.

### Right behavior by default
- [x] `make lint` denies warnings without any opt-in flag.
- [x] CI runs on every push and pull_request, not behind a label or manual trigger.

### Anti-bypass design
- [x] Clippy runs with `-D warnings`; no per-crate `#![allow(...)]` is introduced.
- [x] CI is required: a future branch protection rule on `main` can wire it in.

## 4. Tests

### TC-01: workspace resolves and compiles

Given a clean checkout of the repo with the new workspace `Cargo.toml`.
When the developer runs `make build`.
Then every member crate compiles in release mode, and `target/release/libpam_syauth.so` exists.

### TC-02: workspace smoke test passes

Given the workspace from TC-01.
When the developer runs `make test`.
Then `tests/workspace_smoke.rs` runs and asserts `1 + 1 == 2`, exit code 0.

### TC-03: lint pipeline is green on a clean tree

Given the workspace from TC-01 with no developer code.
When the developer runs `make lint`.
Then clippy, fmt, audit, deny all pass with exit code 0; `make lint` exits 0.

### TC-04: clippy regression is caught by `make lint`

Given a developer adds a deliberate clippy warning (e.g. `let _x: u32 = 1u32 + 0;`) to any crate.
When they run `make lint`.
Then the command exits non-zero with the clippy diagnostic.

### TC-05: cargo-deny rejects a disallowed license

Given the developer adds a dependency under a license not in the allow-list (e.g. GPL-3.0).
When they run `cargo deny check`.
Then the command exits non-zero with a license violation diagnostic.

### TC-06: CI workflow runs on push

Given the `.github/workflows/ci.yml` is committed.
When any push lands on a branch.
Then GitHub Actions runs `make lint` and `make test`, both green on the bootstrap commit.

## Traceability
- Roadmap item: [S-001](../syauth/ROADMAP.md#step-s-001-workspace-bootstrap--ci-lint-pipeline)
- Implementation files:
  - `/Cargo.toml`, workspace declaration with five member crates.
  - `/crates/syauth-core/Cargo.toml`, `/crates/syauth-core/src/lib.rs`, placeholder library.
  - `/crates/syauth-transport/Cargo.toml`, `/crates/syauth-transport/src/lib.rs`, placeholder library.
  - `/crates/syauth-pam/Cargo.toml`, `/crates/syauth-pam/src/lib.rs`, placeholder `cdylib` named `pam_syauth`.
  - `/crates/syauth-cli/Cargo.toml`, `/crates/syauth-cli/src/main.rs`, placeholder binary.
  - `/crates/syauth-mobile/Cargo.toml`, `/crates/syauth-mobile/src/lib.rs`, placeholder library.
  - `/syauth-android/settings.gradle.kts`, `/syauth-android/README.md`, Gradle placeholder.
  - `/Makefile`, extended with workspace-aware build/test/lint/fmt/audit/deny targets.
  - `/deny.toml`, cargo-deny policy.
  - `/.github/workflows/ci.yml`, GitHub Actions CI workflow.
- Test files:
  - `/tests/workspace_smoke.rs`, single integration test, `1 + 1 == 2`.
