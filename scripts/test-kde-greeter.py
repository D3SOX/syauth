#!/usr/bin/env python3
"""Test actual greeter package selection and status changes with isolated PAM."""

import importlib.util
import json
import os
from pathlib import Path
import queue
import shlex
import shutil
import subprocess
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("installer", ROOT / "scripts/install-kde-status.py")
INSTALLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALLER)
GREETER = Path("/usr/lib/kscreenlocker_greet")
SOURCE = Path("/usr/share/plasma/shells/org.kde.plasma.desktop/contents/lockscreen")


def run():
    if not GREETER.is_file() or not SOURCE.is_dir() or not shutil.which("bwrap"):
        print("SKIP: native greeter test requires Plasma and bubblewrap")
        return
    if (SOURCE / "MainBlock.qml").read_text().count(INSTALLER.ANCHOR) != 1 or \
            (SOURCE / "LockScreenUi.qml").read_text().count("if (lockScreenUi.showPrompt) {") != 1:
        print("SKIP: native greeter test requires the supported Plasma 6.8 layout")
        return
    with tempfile.TemporaryDirectory(prefix="kde-greeter-") as temporary:
        root = Path(temporary)
        for name in ["pam", "config", "cache", "data", "runtime"]:
            (root / name).mkdir(mode=0o700)
        report = root / "report.json"
        report.write_text(json.dumps({"daemon": {"state": "up", "peers": [{"connected": True}]}}))
        cli = root / "status"
        cli.write_text("#!/bin/sh\ncat " + shlex.quote(str(report)) + "\n")
        cli.chmod(0o700)
        shell = root / "data/plasma/shells/org.kde.plasma.desktop"
        INSTALLER.install(shell, SOURCE, cli, root / "state")
        lockscreen = shell / "contents/lockscreen"
        status = lockscreen / "PhoneStatus.qml"
        status.write_text(status.read_text().replace("    id: status", '''    id: status
    onTextChanged: value => console.log("SYAUTH-STATUS " + value)
    Component.onCompleted: console.log("SYAUTH-PACKAGE " + Qt.resolvedUrl("."))'''))
        ui = lockscreen / "LockScreenUi.qml"
        ui.write_text(ui.read_text().replace("    id: lockScreenUi", '''    id: lockScreenUi
    Timer {
        interval: 200; running: true
        onTriggered: { lockScreenRoot.uiVisible = true; authenticator.startAuthenticating(); }
    }''').replace(
            "function onPromptForSecretChanged() {",
            'function onPromptForSecretChanged() { console.log("SYAUTH-SELECTOR " + authenticator.promptForSecret);'))
        main = lockscreen / "LockScreen.qml"
        main.write_text(main.read_text().replace("    id: root", '''    id: root
    onNotificationChanged: console.log("SYAUTH-NOTIFICATION " + notification)'''))
        (root / "config/kscreenlockerrc").write_text("[UI]\nShowPromptInRegularAuthenticator=true\n")
        for service in ["kde", "kde-fingerprint", "kde-smartcard", "other"]:
            (root / "pam" / service).write_text("auth requisite pam_deny.so\n")
        environment = os.environ | {
            "QT_FORCE_STDERR_LOGGING": "1", "QT_LOGGING_RULES": "qml.debug=true;kscreenlocker_greet.debug=true;kf.package.debug=true", "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software", "QML_DISABLE_DISK_CACHE": "1",
            "XDG_DATA_HOME": str(root / "data"), "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_CACHE_HOME": str(root / "cache"), "XDG_RUNTIME_DIR": str(root / "runtime"),
            "TMPDIR": str(root), "PLASMA_DEFAULT_SHELL": "org.kde.plasma.desktop",
        }
        bus = root / "bus.conf"
        bus.write_text(f'<busconfig><type>session</type><listen>unix:tmpdir={root / "runtime"}</listen><auth>EXTERNAL</auth><policy context="default"><allow send_destination="*"/><allow receive_sender="*"/><allow own="*"/></policy></busconfig>')
        process = subprocess.Popen([
            "bwrap", "--ro-bind", "/", "/", "--dev-bind", "/dev", "/dev", "--bind", str(root), str(root),
            "--ro-bind", str(root / "pam"), "/etc/pam.d", "--ro-bind", str(root / "pam"), "/usr/lib/pam.d",
            "--unshare-pid", "--unshare-net", "--die-with-parent", "--",
            "dbus-run-session", "--config-file", str(bus), "--", str(GREETER), "--testing", "--immediateLock",
        ], env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
        lines = queue.Queue()
        captured = []
        def read():
            for line in process.stdout:
                lines.put(line)
        threading.Thread(target=read, daemon=True).start()
        def until(expected, timeout=10):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    line = lines.get(timeout=.1)
                except queue.Empty:
                    continue
                captured.append(line)
                if expected in line:
                    return
            raise AssertionError(f"Greeter did not report {expected!r}:\n{''.join(captured)}")
        try:
            until("SYAUTH-PACKAGE " + lockscreen.as_uri())
            until("SYAUTH-STATUS Phone connected")
            report.write_text(json.dumps({"daemon": {"state": "up", "peers": [{"connected": True, "in_flight_challenges": 1}]}}))
            until("SYAUTH-STATUS Waiting for approval on your phone", 4)
            report.write_text(json.dumps({"daemon": {"state": "up", "peers": [{"connected": True, "in_flight_challenges": 0}]}}))
            until("SYAUTH-STATUS Phone connected", 4)
            report.write_text(json.dumps({"daemon": {"state": "up", "peers": [{"connected": False}]}}))
            until("SYAUTH-STATUS Phone disconnected", 4)
            report.write_text("unavailable")
            until("SYAUTH-STATUS Phone status unavailable", 4)
            assert not any("SYAUTH-NOTIFICATION" in line and "press Enter to use your phone" in line for line in captured), captured
            print("PASS: actual greeter selected user shell, updated live status,")
        finally:
            try:
                os.killpg(process.pid, 9)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
            # bubblewrap may place children in another session. Limit cleanup
            # to the unique XDG_DATA_HOME belonging to this private test.
            marker = ("XDG_DATA_HOME=" + str(root / "data")).encode()
            for entry in Path("/proc").iterdir():
                if entry.name.isdigit():
                    try:
                        if marker in (entry / "environ").read_bytes().split(b"\0"):
                            os.kill(int(entry.name), 9)
                    except (OSError, ProcessLookupError):
                        pass


if __name__ == "__main__":
    run()
