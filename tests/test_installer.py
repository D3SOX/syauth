"""Exercise installation against disposable system and home directories."""

import importlib.util
import contextlib
import io
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("syauth_installer", REPO / "scripts/install.py")
INSTALLER = importlib.util.module_from_spec(SPEC)


class InstallerFixture(unittest.TestCase):
    def setUp(self):
        SPEC.loader.exec_module(INSTALLER)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.user = SimpleNamespace(pw_name="alice", pw_uid=1234, pw_gid=1234)
        self.original = {
            "sudo": "# local sudo\nauth include system-auth\naccount include system-auth\nsession optional pam_systemd.so class=none\n",
            "kde": "auth required pam_shells.so\nauth requisite pam_nologin.so\nauth requisite pam_faillock.so preauth\nauth include system-auth\naccount include system-local-login\n",
            "system-auth": "auth required pam_unix.so try_first_pass\n",
        }
        for service, text in self.original.items():
            path = self.root / "etc/pam.d" / service
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)


class SystemInstallTests(InstallerFixture):
    def test_plan_preserves_password_stack_and_mandatory_kde_checks(self):
        plan = INSTALLER.system_plan(self.root, self.user, b"\x7fELFfixture")
        sudo = plan[self.root / "etc/pam.d/sudo"][0].decode()
        kde = plan[self.root / "etc/pam.d/kde"][0].decode()
        self.assertIn("user != alice quiet", sudo)
        self.assertIn("terminal_prompt pwfeedback socket=/run/user/1234/syauth/auth.sock", sudo)
        self.assertIn("session optional pam_systemd.so class=none", sudo)
        self.assertLess(kde.index("pam_faillock.so"), kde.index("pam_syauth.so"))
        self.assertIn("on_empty_password socket=/run/user/1234/syauth/auth.sock", kde)
        self.assertIn("account include system-local-login", kde)
        self.assertEqual(self.original["sudo"], (self.root / "etc/pam.d/sudo").read_text())

    def test_repeat_install_has_one_guard_and_one_module(self):
        for _ in range(2):
            plan = INSTALLER.system_plan(self.root, self.user, b"\x7fELFfixture")
            INSTALLER.Backup(self.root / "backup").apply(plan)
        for service in ("sudo", "kde"):
            text = (self.root / "etc/pam.d" / service).read_text()
            self.assertEqual(1, text.count("pam_syauth.so"))
            self.assertEqual(1, text.count("pam_succeed_if.so"))

    def test_rollback_restores_original_files_and_removes_new_module(self):
        backup = INSTALLER.Backup(self.root / "backup")
        plan = INSTALLER.system_plan(self.root, self.user, b"\x7fELFfixture")
        backup.apply(plan)
        backup.apply(INSTALLER.system_plan(self.root, self.user, b"\x7fELFupdated"))
        backup.restore()
        for service in ("sudo", "kde"):
            self.assertEqual(self.original[service], (self.root / "etc/pam.d" / service).read_text())
        self.assertFalse((self.root / "usr/lib/security/pam_syauth.so").exists())

    def test_rollback_preserves_preexisting_module_contents_and_permissions(self):
        module = self.root / "usr/lib/security/pam_syauth.so"
        module.parent.mkdir(parents=True)
        module.write_bytes(b"old module")
        module.chmod(0o640)
        backup = INSTALLER.Backup(self.root / "backup")
        backup.apply(INSTALLER.system_plan(self.root, self.user, b"\x7fELFfixture"))
        backup.restore()
        self.assertEqual(b"old module", module.read_bytes())
        self.assertEqual(0o640, module.stat().st_mode & 0o777)

    def test_unknown_password_stack_is_rejected_before_any_writes(self):
        (self.root / "etc/pam.d/system-auth").write_text("auth required custom.so\n")
        with self.assertRaisesRegex(ValueError, "try_first_pass"):
            INSTALLER.system_plan(self.root, self.user, b"\x7fELFfixture")
        self.assertEqual(self.original["sudo"], (self.root / "etc/pam.d/sudo").read_text())

    def test_failed_update_restores_the_previous_successful_installation(self):
        backup = INSTALLER.Backup(self.root / "backup")
        backup.apply(INSTALLER.system_plan(self.root, self.user, b"\x7fELFfirst"))
        before = {p: p.read_bytes() for p in (self.root / "etc/pam.d").iterdir()}
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            backup.apply(INSTALLER.system_plan(self.root, self.user, b"\x7fELFsecond"),
                         action=lambda: (_ for _ in ()).throw(RuntimeError("interrupted")))
        self.assertEqual(b"\x7fELFfirst", (self.root / "usr/lib/security/pam_syauth.so").read_bytes())
        self.assertEqual(before, {p: p.read_bytes() for p in (self.root / "etc/pam.d").iterdir()})

    def test_process_death_during_install_can_be_rolled_back(self):
        target, state = self.root / "managed", self.root / "backup"
        target.write_text("original")
        code = f'''import importlib.util,os
from pathlib import Path
s=importlib.util.spec_from_file_location("installer", {str(REPO / "scripts/install.py")!r})
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
m.Backup(Path({str(state)!r})).apply({{Path({str(target)!r}): (b"updated", 0o644)}}, action=lambda: os._exit(23))
'''
        result = subprocess.run([sys.executable, "-c", code], check=False)
        self.assertEqual(23, result.returncode)
        self.assertEqual("updated", target.read_text())
        backup = INSTALLER.Backup(state)
        with self.assertRaisesRegex(ValueError, "interrupted"):
            backup.check()
        backup.restore()
        self.assertEqual("original", target.read_text())
        self.assertFalse(list(self.root.glob(".syauth-attempt-*")))

    def test_concurrent_installations_are_rejected(self):
        with INSTALLER.installation_lock(self.root / "installer.lock"):
            with self.assertRaisesRegex(ValueError, "Another syauth"):
                with INSTALLER.installation_lock(self.root / "installer.lock"):
                    self.fail("second installer acquired the lock")

    def test_rollback_refuses_modified_pam_files_before_restoring_anything(self):
        backup = INSTALLER.Backup(self.root / "backup")
        backup.apply(INSTALLER.system_plan(self.root, self.user, b"\x7fELFfixture"))
        sudo = self.root / "etc/pam.d/sudo"
        sudo.write_text("locally edited")
        with self.assertRaisesRegex(ValueError, "Changed since installation"):
            backup.restore()
        self.assertEqual("locally edited", sudo.read_text())
        self.assertTrue((self.root / "usr/lib/security/pam_syauth.so").exists())

    def test_restore_keeps_existing_pam_files_present_until_atomic_replace(self):
        backup = INSTALLER.Backup(self.root / "backup")
        backup.apply(INSTALLER.system_plan(self.root, self.user, b"\x7fELFfixture"))
        write = INSTALLER.atomic_write
        def observe(path, data, mode):
            if path.parent == self.root / "etc/pam.d":
                self.assertTrue(path.exists(), "PAM files must remain present until replacement")
            write(path, data, mode)
        with mock.patch.object(INSTALLER, "atomic_write", side_effect=observe):
            backup.restore()

    def test_commented_mandatory_checks_do_not_qualify_as_a_valid_kde_stack(self):
        (self.root / "etc/pam.d/kde").write_text("# pam_shells.so pam_nologin.so pam_faillock.so\nauth include system-auth\n")
        with self.assertRaisesRegex(ValueError, "mandatory"):
            INSTALLER.system_plan(self.root, self.user, b"\x7fELFfixture")

    def test_symlinked_destination_is_rejected_without_touching_its_target(self):
        target = self.root / "private"
        target.write_text("unchanged")
        sudo = self.root / "etc/pam.d/sudo"
        sudo.unlink()
        sudo.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "symlink"):
            INSTALLER.system_plan(self.root, self.user, b"\x7fELFfixture")
        self.assertEqual("unchanged", target.read_text())

    def test_old_automatic_phone_stack_is_rejected(self):
        (self.root / "etc/pam.d/kde-fingerprint").write_text("auth sufficient pam_syauth.so\n")
        with self.assertRaisesRegex(ValueError, "kde-fingerprint"):
            INSTALLER.system_plan(self.root, self.user, b"\x7fELFfixture")

    def test_fresh_arch_vendor_kde_stack_is_expanded_without_changing_global_files(self):
        kde = self.root / "etc/pam.d/kde"
        kde.unlink()
        vendor = self.root / "usr/lib/pam.d/kde"
        vendor.parent.mkdir(parents=True)
        vendor.write_text("# vendor\nauth include system-local-login\naccount include system-local-login\nsession include system-local-login\n")
        (self.root / "etc/pam.d/system-local-login").write_text("auth include system-login\naccount include system-login\n")
        (self.root / "etc/pam.d/system-login").write_text("auth required pam_shells.so\nauth requisite pam_nologin.so\nauth include system-auth\naccount required pam_access.so\n")
        password = self.root / "etc/pam.d/system-auth"
        password.write_text("auth required pam_faillock.so preauth\n" + password.read_text())
        before = password.read_bytes()
        plan = INSTALLER.system_plan(self.root, self.user, b"\x7fELFfixture")
        generated = plan[kde][0].decode()
        for name in ("pam_shells.so", "pam_nologin.so", "pam_faillock.so"):
            self.assertLess(generated.index(name), generated.index("pam_syauth.so"))
        self.assertIn("account include system-local-login", generated)
        self.assertNotIn("account required pam_access.so", generated)
        self.assertEqual(before, password.read_bytes())
        INSTALLER.Backup(self.root / "backup").apply(plan)
        INSTALLER.Backup(self.root / "backup").restore()
        self.assertFalse(kde.exists(), "rollback returns to vendor defaults")


class AndroidInstallTests(unittest.TestCase):
    def setUp(self):
        SPEC.loader.exec_module(INSTALLER)

    def test_other_android_users_are_rejected_before_build_or_install(self):
        with mock.patch.object(INSTALLER, "require"), mock.patch.object(INSTALLER, "output", return_value="10"), \
                mock.patch.object(INSTALLER, "build_android") as build, mock.patch.object(INSTALLER, "run") as run:
            with self.assertRaisesRegex(ValueError, "user to be 0"):
                INSTALLER.install_android(SimpleNamespace(android="test-device", skip_build=False))
        build.assert_not_called()
        run.assert_not_called()

    def test_installation_requires_adbs_explicit_success_and_preserves_app_data(self):
        with mock.patch.object(INSTALLER, "require"), mock.patch.object(INSTALLER, "output", side_effect=lambda c: "36" if c[-1] == "ro.build.version.sdk" else "0"), \
                mock.patch.object(INSTALLER, "run", return_value=SimpleNamespace(stdout="Performing Streamed Install\n", stderr="")) as run:
            with self.assertRaisesRegex(ValueError, "did not confirm"):
                INSTALLER.install_android(SimpleNamespace(android="test-device", skip_build=True))
        command = run.call_args.args[0]
        self.assertEqual(["adb", "-s", "test-device", "install", "--user", "0", "-r"], command[:-1])

    def test_successful_install_opens_the_app_for_user_zero(self):
        with mock.patch.object(INSTALLER, "require"), mock.patch.object(INSTALLER, "output", side_effect=lambda c: "36" if c[-1] == "ro.build.version.sdk" else "0"), \
                mock.patch.object(INSTALLER, "build_android") as build, \
                mock.patch.object(INSTALLER, "run", return_value=SimpleNamespace(stdout="Success\n", stderr="")) as run:
            INSTALLER.install_android(SimpleNamespace(android="test-device", skip_build=False))
        build.assert_called_once()
        self.assertEqual(["adb", "-s", "test-device", "shell", "am", "start", "--user", "0", "-n", "com.sy.syauth.android/.MainActivity"], run.call_args.args[0])

    def test_unsupported_android_version_is_rejected_before_building(self):
        with mock.patch.object(INSTALLER, "require"), mock.patch.object(INSTALLER, "output", side_effect=["0", "26"]), \
                mock.patch.object(INSTALLER, "build_android") as build, mock.patch.object(INSTALLER, "run") as run:
            with self.assertRaisesRegex(ValueError, "API 33"):
                INSTALLER.install_android(SimpleNamespace(android="test-device", skip_build=False))
        build.assert_not_called()
        run.assert_not_called()

    def test_switching_android_users_during_build_prevents_installation(self):
        with mock.patch.object(INSTALLER, "require"), mock.patch.object(INSTALLER, "output", side_effect=["0", "36", "10"]), \
                mock.patch.object(INSTALLER, "build_android"), mock.patch.object(INSTALLER, "run") as run:
            with self.assertRaisesRegex(ValueError, "user changed"):
                INSTALLER.install_android(SimpleNamespace(android="test-device", skip_build=False))
        run.assert_not_called()


class DesktopFlowTests(InstallerFixture):
    def exercise_desktop(self, custom_shell):
        home = self.root / "home with spaces"
        config, data, state = home / ".config", home / ".local/share", home / ".local/state/syauth"
        config.mkdir(parents=True)
        screen = config / "kscreenlockerrc"
        screen.write_text("[Daemon]\nTimeout=42\n")
        source = self.root / "vendor/contents/lockscreen"
        source.mkdir(parents=True)
        (source.parent.parent / "metadata.json").write_text('{"KPackageStructure":"Plasma/Shell"}')
        (source / "MainBlock.qml").write_text("Item {\n    component FailableLabel : Item {}\n}\n")
        (source / "LockScreenUi.qml").write_text("if (lockScreenUi.showPrompt) { showPrompt(); }")
        (source.parent / "Desktop.qml").write_text("vendor desktop")
        shell = data / "plasma/shells/org.kde.plasma.desktop"
        if custom_shell:
            shutil.copytree(source.parent.parent, shell)
            (shell / "contents/Custom.qml").write_text("custom desktop")
        before = INSTALLER.fingerprint(shell)
        artifacts = self.root / "target/release"
        artifacts.mkdir(parents=True)
        for name in ("syauth", "syauth-presenced"):
            shutil.copyfile(shutil.which("true"), artifacts / name)
        subprocess.run(["cc", "-shared", "-fPIC", "-x", "c", "-o", str(artifacts / "libpam_syauth.so"), "-"],
                       input="int pam_sm_authenticate(void) { return 9; }\nint pam_sm_setcred(void) { return 0; }\n", text=True, check=True)
        args = SimpleNamespace(phone_address="aa:bb:cc:dd:ee:ff", android=None, skip_build=not custom_shell,
                               dry_run=False, artifacts_dir=artifacts)
        user = pwd.getpwuid(os.getuid())
        real_run = subprocess.run
        commands = []
        def process(command, **kwargs):
            commands.append(list(map(str, command)))
            if command[0] == "systemctl":
                return subprocess.CompletedProcess(command, 3 if command[2].startswith("is-") else 0)
            if command[0] == "cargo":
                self.assertEqual(str(artifacts.parent), kwargs["env"]["CARGO_TARGET_DIR"])
                return subprocess.CompletedProcess(command, 0)
            if "stdout" not in kwargs and "stderr" not in kwargs:
                kwargs.setdefault("capture_output", True)
            kwargs.setdefault("text", True)
            return real_run(command, **kwargs)
        def system(unused, action):
            if action == "install":
                INSTALLER.install_system(self.root, user, (artifacts / "libpam_syauth.so").read_bytes())
            else:
                INSTALLER.Backup(self.root / "var/lib/syauth-installer").restore()
        # All system writes are redirected to self.root. Qt tools and the QML
        # installer run as real child processes against the private home.
        with mock.patch.object(INSTALLER, "paths_for_user", return_value=(home, config, data, state)), \
                mock.patch.object(INSTALLER, "preflight", return_value=(shell, source)), \
                mock.patch.object(INSTALLER, "elevate", side_effect=system), \
                mock.patch.object(INSTALLER.subprocess, "run", side_effect=process), \
                contextlib.redirect_stdout(io.StringIO()):
            INSTALLER.install_desktop(args)
            (self.root / "var/lib/syauth/keys/keep.bin").write_bytes(b"existing pairing key")
            INSTALLER.install_desktop(args)
            self.assertTrue((home / ".local/bin/syauth").is_file())
            self.assertIn("AA:BB:CC:DD:EE:FF", (config / "systemd/user/syauth-presenced.service.d/phone.conf").read_text())
            self.assertEqual(1, (shell / "contents/lockscreen/MainBlock.qml").read_text().count("// syauth live phone status"))
            self.assertIn("ShowPromptInRegularAuthenticator=true", screen.read_text())
            INSTALLER.rollback(args)
        self.assertEqual(before, INSTALLER.fingerprint(shell))
        self.assertEqual("[Daemon]\nTimeout=42\n", screen.read_text())
        self.assertFalse((home / ".local/bin/syauth").exists())
        self.assertEqual(self.original["sudo"], (self.root / "etc/pam.d/sudo").read_text())
        self.assertEqual(b"existing pairing key", (self.root / "var/lib/syauth/keys/keep.bin").read_bytes())
        self.assertIn(["systemctl", "--user", "disable", "syauth-presenced"], commands)

    @unittest.skipUnless(shutil.which("kwriteconfig6") and shutil.which("cc"), "requires KDE config tools and a C compiler")
    def test_fresh_install_repeat_and_rollback_with_real_qml_installer(self):
        self.exercise_desktop(False)

    @unittest.skipUnless(shutil.which("kwriteconfig6") and shutil.which("cc"), "requires KDE config tools and a C compiler")
    def test_custom_shell_and_existing_settings_survive_full_install_and_rollback(self):
        self.exercise_desktop(True)


if __name__ == "__main__":
    unittest.main()
