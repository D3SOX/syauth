//! Radio-free regression tests for `syauth pair` adapter selection when the
//! kernel has renamed the controller (only `hci1` present).
//!
//! Reuses the private BlueZ D-Bus peer from `syauth-presenced`'s recovery
//! tests so both binaries are checked against the same fake.

#[test]
fn pair_selects_the_adapter_bluez_actually_has() {
    let result = std::process::Command::new("python3")
        .arg(concat!(env!("CARGO_MANIFEST_DIR"), "/tests/pair_adapter_selection.py"))
        .env("SYAUTH_CLI_BINARY", env!("CARGO_BIN_EXE_syauth"))
        .env(
            "SYAUTH_BLUEZ_MOCK",
            concat!(env!("CARGO_MANIFEST_DIR"), "/../syauth-presenced/tests/bluez_recovery.py"),
        )
        .output()
        .expect("run private BlueZ peer tests");
    assert!(
        result.status.success(),
        "{}\n{}",
        String::from_utf8_lossy(&result.stdout),
        String::from_utf8_lossy(&result.stderr)
    );
}
