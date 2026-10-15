#!/usr/bin/env python3
"""Exercise shell selection, installation, and rollback in private fixtures."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("installer", Path(__file__).with_name("install-kde-status.py"))
INSTALLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALLER)
MAIN_BLOCK = "Item {\n    component FailableLabel : Item {}\n}\n"


def package(directory, main=MAIN_BLOCK):
    lockscreen = directory / "contents/lockscreen"
    lockscreen.mkdir(parents=True)
    (directory / "metadata.json").write_text('{"KPackageStructure":"Plasma/Shell"}')
    (lockscreen / "MainBlock.qml").write_text(main)
    (lockscreen / "LockScreenUi.qml").write_text("if (lockScreenUi.showPrompt) { showPrompt(); }")
    (directory / "contents/Desktop.qml").write_text("unchanged desktop")
    return lockscreen


class InstallerTests(unittest.TestCase):
    def test_installed_status_is_a_loadable_shell_package(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = package(root / "vendor")
            shell = root / "plasma/shells/org.kde.plasma.desktop"
            INSTALLER.install(shell, source, Path("/usr/bin/syauth"), root / "state")
            self.assertTrue((shell / "metadata.json").is_file(), "greeter needs shell metadata to select the patched QML")
            self.assertEqual((shell / "contents/Desktop.qml").read_text(), "unchanged desktop")
            ui = (shell / "contents/lockscreen/LockScreenUi.qml").read_text()
            self.assertIn("!mainBlock.syauthStatus.isSelectorPrompt(authenticator.promptForSecret)", ui)

    def test_default_uses_the_greeters_shell_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = package(root / "vendor")
            cli = root / "syauth"
            cli.touch()
            argv = ["install", "--source", str(source), "--cli", str(cli), "--state-dir", str(root / "state")]
            with patch("sys.argv", argv), patch.dict("os.environ", {"XDG_DATA_HOME": str(root / "data")}), \
                    patch.object(INSTALLER.subprocess, "check_output", return_value="org.kde.plasma.desktop\n") as config:
                INSTALLER.main()
            self.assertIn("plasmashellrc", config.call_args.args[0])
            self.assertIn("ShellPackage", config.call_args.args[0])
            self.assertTrue((root / "data/plasma/shells/org.kde.plasma.desktop/metadata.json").is_file())

    def test_install_is_idempotent_and_uninstall_restores_custom_package(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shell = root / "custom-shell"
            target = package(shell)
            (target / "Custom.qml").write_text("custom lockscreen")
            state = root / "state"
            INSTALLER.install(shell, root / "absent", Path("/path with spaces/syauth"), state)
            installed = (target / "MainBlock.qml").read_text()
            self.assertEqual(installed.count(INSTALLER.MARKER), 1)
            self.assertIn("'/path with spaces/syauth' status --json", installed)
            INSTALLER.install(shell, root / "absent", Path("/path with spaces/syauth"), state)
            self.assertEqual((target / "MainBlock.qml").read_text(), installed)
            INSTALLER.uninstall(state)
            self.assertEqual((target / "MainBlock.qml").read_text(), MAIN_BLOCK)
            self.assertEqual((target / "Custom.qml").read_text(), "custom lockscreen")
            self.assertFalse((target / "PhoneStatus.qml").exists())

    def test_vendor_package_override_is_removed_on_uninstall(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = package(root / "vendor")
            shell, state = root / "shell", root / "state"
            INSTALLER.install(shell, source, Path("/usr/bin/syauth"), state)
            INSTALLER.uninstall(state)
            self.assertFalse(shell.exists())

    def test_unknown_layout_is_rejected_without_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = package(root / "vendor", "Item {}")
            with self.assertRaises(ValueError):
                INSTALLER.install(root / "shell", source, Path("/usr/bin/syauth"), root / "state")
            self.assertFalse((root / "shell").exists())


if __name__ == "__main__":
    unittest.main()
