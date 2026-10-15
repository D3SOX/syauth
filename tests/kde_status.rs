//! Exercise the user-theme installer and the native Qt status component.

use std::{path::Path, process::Command};

#[test]
fn kde_status_installer_preserves_the_theme_and_supports_rollback() {
    let result = Command::new("python3")
        .arg("scripts/test-kde-status.py")
        .output()
        .expect("run installer tests");
    assert!(result.status.success(), "{}", String::from_utf8_lossy(&result.stderr));
}

#[test]
fn kde_status_updates_without_password_submission() {
    let runner = Path::new("/usr/lib/qt6/bin/qmltestrunner");
    if !runner.is_file() {
        eprintln!("Qt Quick Test not installed; native QML checks require qmltestrunner");
        return;
    }
    let result = Command::new(runner)
        .env("QT_QPA_PLATFORM", "offscreen")
        .args(["-input", "deploy/kde/tests"])
        .output()
        .expect("run QML tests");
    assert!(
        result.status.success(),
        "{}\n{}",
        String::from_utf8_lossy(&result.stdout),
        String::from_utf8_lossy(&result.stderr)
    );
}

#[test]
fn greeter_loads_the_shell_override_and_tracks_connection_changes() {
    let result = Command::new("python3")
        .arg("scripts/test-kde-greeter.py")
        .output()
        .expect("run isolated native greeter test");
    assert!(
        result.status.success(),
        "{}\n{}",
        String::from_utf8_lossy(&result.stdout),
        String::from_utf8_lossy(&result.stderr)
    );
}
