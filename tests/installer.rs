//! Run the installation and rollback journeys against private system/home trees.

use std::process::Command;

#[test]
fn desktop_installer_preserves_authentication_settings_and_pairing_data() {
    let result = Command::new("python3")
        .args(["-m", "unittest", "discover", "-s", "tests", "-p", "test_installer.py"])
        .output()
        .expect("run isolated installer tests");
    assert!(
        result.status.success(),
        "{}\n{}",
        String::from_utf8_lossy(&result.stdout),
        String::from_utf8_lossy(&result.stderr)
    );
}
