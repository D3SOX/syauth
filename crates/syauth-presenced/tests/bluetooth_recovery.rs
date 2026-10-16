//! Radio-free regression tests for controller re-enumeration after resume.

#[test]
fn bluez_adapter_loss_recovers_through_service_restart() {
    let result = std::process::Command::new("python3")
        .arg(concat!(env!("CARGO_MANIFEST_DIR"), "/tests/bluez_recovery.py"))
        .env("SYAUTH_DAEMON_BINARY", env!("CARGO_BIN_EXE_syauth-presenced"))
        .output()
        .expect("run private BlueZ peer tests");
    assert!(
        result.status.success(),
        "{}\n{}",
        String::from_utf8_lossy(&result.stdout),
        String::from_utf8_lossy(&result.stderr)
    );
}
