"""Drive install.sh end to end against private system and home directories.

Journey: specs/journeys/JOURNEY-S-013-pam-install-helper.md
"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
VERSION = "0.1.1"
PACKAGE = f"syauth-{VERSION}-1-x86_64.pkg.tar.zst"
APK = f"syauth-{VERSION}-android.apk"
SUDO = "# local sudo\nauth include system-auth\naccount include system-auth\nsession optional pam_systemd.so class=none\n"
KDE = ("auth required pam_shells.so\nauth requisite pam_nologin.so\nauth requisite pam_faillock.so preauth\n"
       "auth include system-auth\naccount include system-local-login\n")
PASSWORD = "auth required pam_unix.so try_first_pass\n"


class InstallerFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root, self.home, self.bin = base / "root", base / "home with spaces", base / "bin"
        self.log = base / "commands.log"
        self.bin.mkdir()
        self.config = self.home / ".config"
        self.state = self.home / ".local/state/syauth"
        self.shell = self.home / ".local/share/plasma/shells/org.kde.plasma.desktop"
        self.dropins = self.config / "systemd/user/syauth-presenced.service.d"
        self.screen = self.config / "kscreenlockerrc"
        self.config.mkdir(parents=True)
        self.screen.write_text("[Daemon]\nTimeout=42\n")
        for service, text in (("sudo", SUDO), ("kde", KDE), ("system-auth", PASSWORD)):
            self.write(self.root / "etc/pam.d" / service, text)
        self.os_release = base / "os-release"
        self.os_release.write_text("ID=arch\n")
        self.packaged_files()
        self.vendor_shell()
        self.payloads = {PACKAGE: b"arch package", APK: b"android package"}
        self.mock_commands()
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", HOME=str(self.home),
                        SYAUTH_ROOT=str(self.root), SYAUTH_OS_RELEASE=str(self.os_release),
                        TMPDIR=str(base), LOG=str(self.log), STATE_FLAGS=str(base / "flags"))
        for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
            self.env.pop(name, None)

    def write(self, path, text, mode=0o644):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        path.chmod(mode)

    def packaged_files(self):
        """Lay out what the syauth package installs below the private root."""
        self.write(self.root / "usr/bin/syauth", '#!/bin/sh\nprintf "syauth %s\\n" "$*" >> "$LOG"\n', 0o755)
        helper = self.root / "usr/lib/syauth/install-kde-status"
        helper.parent.mkdir(parents=True)
        shutil.copyfile(REPO / "scripts/install-kde-status.py", helper)
        helper.chmod(0o755)
        shutil.copyfile(REPO / "scripts/install.sh", self.root / "usr/lib/syauth/install.sh")
        for source, destination in (("deploy/kde/PhoneStatus.qml", "usr/share/syauth/kde/PhoneStatus.qml"),
                                    ("deploy/arch/95-syauth-check.hook", "usr/share/syauth/pacman/95-syauth-check.hook")):
            self.write(self.root / destination, (REPO / source).read_text())
        self.write(self.root / "usr/lib/syauth/check-pam-update",
                   '#!/bin/sh\nprintf "checker %s\\n" "$*" >> "$LOG"\n', 0o755)

    def vendor_shell(self):
        vendor = self.root / "usr/share/plasma/shells/org.kde.plasma.desktop"
        self.write(vendor / "metadata.json", '{"KPackageStructure":"Plasma/Shell"}')
        self.write(vendor / "contents/lockscreen/MainBlock.qml", "Item {\n    component FailableLabel : Item {}\n}\n")
        self.write(vendor / "contents/lockscreen/LockScreenUi.qml", "if (lockScreenUi.showPrompt) { showPrompt(); }")
        self.write(vendor / "contents/Desktop.qml", "vendor desktop")

    def command(self, name, body):
        self.write(self.bin / name, f'#!/bin/sh\nprintf "{name} %s\\n" "$*" >> "$LOG"\n{body}\n', 0o755)

    def mock_commands(self):
        self.command("sudo", 'exec "$@"')
        self.command("uname", "echo x86_64")
        self.command("getconf", "echo 'glibc 2.42'")
        self.command("pacman", 'case "$1" in -Q) echo "plasma-desktop 6.8.0-1"; echo "kscreenlocker 1:6.8.1-1";; esac')
        self.command("bluetoothctl", "echo 'Powered: yes'")
        self.command("kreadconfig6", "true")
        self.command("kwriteconfig6", 'printf "[UI]\\nShowPromptInRegularAuthenticator=true\\n" >> "$2"')
        self.command("systemctl", '''case "$2" in
    is-active|is-enabled) grep -qx "$2" "$STATE_FLAGS" 2>/dev/null;;
    show) echo 256;;
esac''')
        self.command("adb", 'echo 0')
        assets = [{"name": name, "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
                   "browser_download_url": f"https://github.invalid/{name}"} for name, data in self.payloads.items()]
        (self.root.parent / "release.json").write_text(json.dumps({"tag_name": f"v{VERSION}", "assets": assets}))
        for name, data in self.payloads.items():
            (self.root.parent / name).write_bytes(data)
        self.command("curl", f'''out=
while [ "$#" -gt 0 ]; do case "$1" in -o|--output) out=$2; shift 2;; *) url=$1; shift;; esac; done
case "$url" in
    */releases/latest|*/releases/tags/*) cp '{self.root.parent}/release.json' "$out";;
    */download/v{VERSION}/*) cp '{self.root.parent}'/"${{url##*/}}" "$out";;
    *) exit 22;;
esac''')

    def run_installer(self, *args, check=True, **kwargs):
        result = subprocess.run(["sh", str(REPO / "scripts/install.sh"), *args], env=self.env,
                                text=True, capture_output=True, **kwargs)
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def commands(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def snapshot(self):
        paths = [self.root / "etc/pam.d", self.shell, self.screen, self.dropins]
        return {str(path): sorted((str(p.relative_to(path)), p.read_bytes()) for p in path.rglob("*") if p.is_file())
                if path.is_dir() else path.read_bytes() if path.exists() else None for path in paths}


class DesktopInstallTests(InstallerFixture):
    def test_desktop_install_configures_pam_status_and_daemon_from_the_release_package(self):
        result = self.run_installer("--desktop", "--phone-address", "aa:bb:cc:dd:ee:ff")
        sudo = (self.root / "etc/pam.d/sudo").read_text()
        kde = (self.root / "etc/pam.d/kde").read_text()
        user, uid = os.environ.get("USER") or subprocess.check_output(["id", "-un"], text=True).strip(), os.getuid()
        self.assertIn(f"pam_succeed_if.so user != {user} quiet", sudo)
        self.assertIn(f"terminal_prompt pwfeedback socket=/run/user/{uid}/syauth/auth.sock", sudo)
        self.assertIn("session optional pam_systemd.so class=none", sudo)
        self.assertLess(kde.index("pam_faillock.so"), kde.index("pam_syauth.so"))
        self.assertIn(f"on_empty_password socket=/run/user/{uid}/syauth/auth.sock", kde)
        self.assertIn(f"pacman -U --noconfirm", "\n".join(self.commands()))
        self.assertIn("SYAUTH_RECONNECT_DEVICE=AA:BB:CC:DD:EE:FF", (self.dropins / "phone.conf").read_text())
        self.assertIn("RuntimeDirectory=syauth", (self.dropins / "runtime.conf").read_text())
        self.assertEqual(1, (self.shell / "contents/lockscreen/MainBlock.qml").read_text().count("// syauth live phone status"))
        self.assertIn(str(self.root / "usr/bin/syauth"), (self.shell / "contents/lockscreen/MainBlock.qml").read_text())
        self.assertIn("ShowPromptInRegularAuthenticator=true", self.screen.read_text())
        self.assertIn("systemctl --user enable --now syauth-presenced", self.commands())
        for directory in ("var/lib/syauth", "var/lib/syauth/keys", "var/log/syauth"):
            self.assertEqual(0o700, (self.root / directory).stat().st_mode & 0o777)
        self.assertIn("Installed.", result.stdout)

    def test_dry_run_previews_pam_changes_without_installing(self):
        before = self.snapshot()
        result = self.run_installer("--desktop", "--dry-run")
        self.assertIn("+auth sufficient pam_syauth.so terminal_prompt pwfeedback", result.stdout)
        self.assertIn("Verified " + PACKAGE, result.stdout)
        self.assertEqual(before, self.snapshot())
        self.assertNotIn("pacman -U", "\n".join(self.commands()))

    def test_repeat_install_has_one_guard_and_one_module(self):
        self.run_installer("--desktop")
        (self.root / "var/lib/syauth/keys/keep.bin").write_bytes(b"existing pairing key")
        self.run_installer("--desktop")
        for service in ("sudo", "kde"):
            text = (self.root / "etc/pam.d" / service).read_text()
            self.assertEqual(1, text.count("pam_syauth.so"))
            self.assertEqual(1, text.count("pam_succeed_if.so"))
        self.assertEqual(b"existing pairing key", (self.root / "var/lib/syauth/keys/keep.bin").read_bytes())

    def test_rollback_restores_every_file_and_the_service_state(self):
        before = self.snapshot()
        self.run_installer("--desktop", "--phone-address", "AA:BB:CC:DD:EE:FF")
        (self.root / "var/lib/syauth/keys/keep.bin").write_bytes(b"existing pairing key")
        self.run_installer("rollback")
        self.assertEqual(before, self.snapshot())
        self.assertEqual(b"existing pairing key", (self.root / "var/lib/syauth/keys/keep.bin").read_bytes())
        self.assertIn("systemctl --user disable syauth-presenced", self.commands())
        self.assertFalse((self.state / "installer").exists())
        self.assertFalse((self.root / "var/lib/syauth-installer").exists())

    def test_rollback_restarts_a_service_that_was_running_before(self):
        (self.root.parent / "flags").write_text("is-active\nis-enabled\n")
        self.run_installer("--desktop")
        self.run_installer("rollback")
        self.assertNotIn("systemctl --user disable syauth-presenced", self.commands())
        self.assertEqual("systemctl --user start syauth-presenced", self.commands()[-1])

    def test_custom_shell_and_existing_settings_survive_install_and_rollback(self):
        shutil.copytree(self.root / "usr/share/plasma/shells/org.kde.plasma.desktop", self.shell)
        (self.shell / "contents/Custom.qml").write_text("custom desktop")
        before = self.snapshot()
        self.run_installer("--desktop")
        self.assertEqual("custom desktop", (self.shell / "contents/Custom.qml").read_text())
        self.run_installer("rollback")
        self.assertEqual(before, self.snapshot())

    def test_fresh_arch_vendor_kde_stack_is_expanded_without_changing_global_files(self):
        (self.root / "etc/pam.d/kde").unlink()
        self.write(self.root / "usr/lib/pam.d/kde", "# vendor\nauth include system-local-login\naccount include system-local-login\nsession include system-local-login\n")
        self.write(self.root / "etc/pam.d/system-local-login", "auth include system-login\naccount include system-login\n")
        self.write(self.root / "etc/pam.d/system-login", "auth required pam_shells.so\nauth requisite pam_nologin.so\nauth include system-auth\naccount required pam_access.so\n")
        password = self.root / "etc/pam.d/system-auth"
        password.write_text("auth required pam_faillock.so preauth\n" + PASSWORD)
        before = password.read_bytes()
        self.run_installer("--desktop")
        generated = (self.root / "etc/pam.d/kde").read_text()
        for name in ("pam_shells.so", "pam_nologin.so", "pam_faillock.so"):
            self.assertLess(generated.index(name), generated.index("pam_syauth.so"))
        self.assertIn("auth requisite pam_faillock.so preauth", generated)
        self.assertIn("account include system-local-login", generated)
        self.assertNotIn("account required pam_access.so", generated)
        self.assertEqual(before, password.read_bytes())
        self.run_installer("rollback")
        self.assertFalse((self.root / "etc/pam.d/kde").exists(), "rollback returns to vendor defaults")


class DesktopSafetyTests(InstallerFixture):
    def assert_rejected_before_changes(self, message, *args):
        before = self.snapshot()
        result = self.run_installer("--desktop", *args, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(message, result.stderr)
        self.assertEqual(before, self.snapshot())
        self.assertNotIn("pacman -U", "\n".join(self.commands()))

    def test_unknown_password_stack_is_rejected_before_any_writes(self):
        (self.root / "etc/pam.d/system-auth").write_text("auth required custom.so\n")
        self.assert_rejected_before_changes("try_first_pass")

    def test_commented_mandatory_checks_do_not_qualify_as_a_valid_kde_stack(self):
        (self.root / "etc/pam.d/kde").write_text("# pam_shells.so pam_nologin.so pam_faillock.so\nauth include system-auth\n")
        self.assert_rejected_before_changes("mandatory")

    def test_custom_syauth_block_requires_review(self):
        (self.root / "etc/pam.d/sudo").write_text("auth sufficient pam_syauth.so debug\nauth include system-auth\n")
        self.assert_rejected_before_changes("custom syauth configuration")

    def test_symlinked_destination_is_rejected_without_touching_its_target(self):
        target = self.root.parent / "private"
        target.write_text("unchanged")
        sudo = self.root / "etc/pam.d/sudo"
        sudo.unlink()
        sudo.symlink_to(target)
        self.assert_rejected_before_changes("symlink")
        self.assertEqual("unchanged", target.read_text())

    def test_old_automatic_phone_stack_is_rejected(self):
        self.write(self.root / "etc/pam.d/kde-fingerprint", "auth sufficient pam_syauth.so\n")
        self.assert_rejected_before_changes("kde-fingerprint")

    def test_user_unit_overriding_the_package_is_rejected(self):
        self.write(self.config / "systemd/user/syauth-presenced.service", "[Service]\nExecStart=/old\n")
        self.assert_rejected_before_changes("overrides the packaged service")

    def test_old_plasma_is_rejected(self):
        self.command("pacman", 'case "$1" in -Q) echo "plasma-desktop 6.7.5-1"; echo "kscreenlocker 6.7.5-1";; esac')
        self.assert_rejected_before_changes("6.8 or newer")

    def test_desktop_setup_requires_arch(self):
        self.os_release.write_text("ID=debian\n")
        self.command("apt-get", "true")
        self.assert_rejected_before_changes("Arch Linux")

    def test_failed_update_restores_the_previous_successful_installation(self):
        self.run_installer("--desktop")
        before = self.snapshot()
        self.command("kwriteconfig6", 'printf "partial\\n" >> "$2"; exit 1')
        result = self.run_installer("--desktop", "--phone-address", "AA:BB:CC:DD:EE:FF", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, self.snapshot())
        self.run_installer("rollback")

    def test_failed_system_phase_restores_user_files(self):
        before = self.snapshot()
        self.command("sudo", 'case "$*" in *__system*) exit 7;; esac; exec "$@"')
        result = self.run_installer("--desktop", check=False)
        self.assertEqual(result.returncode, 7)
        self.assertEqual(before, self.snapshot())

    def test_process_death_during_install_can_be_rolled_back(self):
        before = self.snapshot()
        self.command("kwriteconfig6", 'printf "[UI]\\n" >> "$2"; kill -KILL 0')
        result = self.run_installer("--desktop", check=False, start_new_session=True)
        self.assertEqual(result.returncode, -9)
        self.assertNotEqual(before, self.snapshot())
        interrupted = self.run_installer("--desktop", check=False)
        self.assertIn("interrupted", interrupted.stderr)
        self.run_installer("rollback")
        self.assertEqual(before, self.snapshot())
        self.assertEqual([], list(self.state.glob(".syauth-attempt-*")))

    def test_concurrent_installations_are_rejected(self):
        self.state.mkdir(parents=True)
        lock = self.state / ".installer.lock"
        with subprocess.Popen(["flock", str(lock), "sleep", "30"]) as holder:
            try:
                for _ in range(200):
                    if subprocess.run(["flock", "-n", str(lock), "true"]).returncode != 0:
                        break
                result = self.run_installer("--desktop", check=False)
            finally:
                holder.kill()
        self.assertIn("Another syauth installation is running", result.stderr)

    def test_rollback_refuses_modified_pam_files_before_restoring_anything(self):
        self.run_installer("--desktop")
        sudo = self.root / "etc/pam.d/sudo"
        sudo.write_text("locally edited")
        before = self.snapshot()
        result = self.run_installer("rollback", check=False)
        self.assertIn("Changed since installation", result.stderr)
        self.assertEqual(before, self.snapshot())

    def test_rollback_without_an_installation_changes_nothing(self):
        result = self.run_installer("rollback")
        self.assertIn("No desktop-user backup to restore.", result.stdout)


class SourceAndOptionTests(InstallerFixture):
    def checkout(self):
        checkout = self.root.parent / "checkout"
        self.write(checkout / "Cargo.toml", f'[workspace]\nmembers = []\n\n[workspace.package]\nversion = "{VERSION}"\n')
        self.write(checkout / "scripts/build-linux-packages.sh", '''#!/bin/sh
printf "packager %s\\n" "$*" >> "$LOG"
while [ "$#" -gt 0 ]; do case "$1" in --output) out=$2; shift 2;; *) shift;; esac; done
mkdir -p "$out"; printf local > "$out/''' + PACKAGE + '''"
''', 0o755)
        self.command("cargo", "true")
        self.command("cc", "true")
        self.command("pkg-config", "true")
        return checkout

    def test_source_mode_builds_and_installs_a_local_package(self):
        checkout = self.checkout()
        self.run_installer("--source", str(checkout))
        log = "\n".join(self.commands())
        self.assertIn("cargo build --locked --release -p syauth-cli -p syauth-pam -p syauth-presenced", log)
        self.assertIn(f"packager --version {VERSION} --arch x86_64", log)
        self.assertRegex(log, rf"pacman -U --noconfirm .*/packages/{PACKAGE}")
        self.assertNotIn("curl", log)

    def test_source_dry_run_builds_nothing(self):
        result = self.run_installer("--source", str(self.checkout()), "--dry-run")
        self.assertIn(f"build syauth {VERSION}", result.stdout)
        self.assertNotIn("cargo", "\n".join(self.commands()))

    def test_source_mode_needs_a_checkout(self):
        result = self.run_installer("--source", str(self.root.parent), check=False)
        self.assertIn("Not a syauth checkout", result.stderr)

    def test_invalid_option_combinations_are_rejected(self):
        for args, message in ((["--phone-address", "AA:BB:CC:DD:EE:FF"], "--desktop"),
                              (["--desktop", "--phone-address", "phone"], "MAC address"),
                              (["--source", "--version", "0.1.1"], "--version selects a release"),
                              (["rollback", "--desktop"], "Options apply only to install"),
                              (["--android", "bad serial"], "ADB serial")):
            with self.subTest(args=args):
                result = self.run_installer(*args, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
        self.assertNotIn("curl", "\n".join(self.commands()))

    def test_update_check_installs_the_pacman_hook_after_a_passing_baseline(self):
        self.run_installer("update-check")
        hook = self.root / "etc/pacman.d/hooks/95-syauth-check.hook"
        self.assertIn("Exec = /usr/lib/syauth/check-pam-update", hook.read_text())
        self.assertEqual(["checker --record-baseline", "checker "], [line for line in self.commands() if line.startswith("checker")])
        repeated = self.run_installer("update-check", check=False)
        self.assertIn("Already exists", repeated.stderr)

    def test_failed_update_check_baseline_leaves_no_hook(self):
        self.write(self.root / "usr/lib/syauth/check-pam-update", "#!/bin/sh\nexit 2\n", 0o755)
        result = self.run_installer("update-check", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "etc/pacman.d/hooks/95-syauth-check.hook").exists())

    def test_pair_pauses_a_running_daemon_and_restarts_it(self):
        (self.root.parent / "flags").write_text("is-active\n")
        self.run_installer("pair")
        commands = self.commands()
        stop = commands.index("systemctl --user stop syauth-presenced")
        self.assertLess(stop, commands.index("syauth pair --timeout-secs 300"))
        self.assertEqual("systemctl --user start syauth-presenced", commands[-1])


class AndroidInstallTests(InstallerFixture):
    def adb(self, users="0", sdk="36", install="Success"):
        """Answer get-current-user from a sequence so tests can switch users mid-run."""
        sequence = self.root.parent / "users"
        sequence.write_text("\n".join(users.split()) + "\n")
        self.command("adb", f'''case "$*" in
    *get-current-user*) head -n 1 '{sequence}'; [ "$(wc -l < '{sequence}')" -le 1 ] || sed -i 1d '{sequence}';;
    *getprop*) echo {sdk};;
    *" install "*) echo "{install}";;
esac''')

    def test_release_apk_is_verified_installed_for_user_zero_and_opened(self):
        self.adb()
        self.run_installer("--android", "test-device")
        commands = self.commands()
        self.assertTrue(any(line.startswith("adb -s test-device install --user 0 -r ") and line.endswith(APK) for line in commands))
        self.assertEqual(f"adb -s test-device shell am start --user 0 -n com.sy.syauth.android/.MainActivity", commands[-1])

    def test_other_android_users_are_rejected_before_any_install(self):
        self.adb(users="10")
        result = self.run_installer("--android", "test-device", check=False)
        self.assertIn("current user to be 0", result.stderr)
        self.assertFalse(any("install" in line and line.startswith(("adb", "pacman -U")) for line in self.commands()))

    def test_unsupported_android_version_is_rejected_before_installing(self):
        self.adb(sdk="26")
        result = self.run_installer("--android", "test-device", check=False)
        self.assertIn("API 33", result.stderr)
        self.assertNotIn("pacman -U", "\n".join(self.commands()))

    def test_switching_android_users_before_install_prevents_it(self):
        self.adb(users="0 10")
        result = self.run_installer("--android", "test-device", check=False)
        self.assertIn("user changed", result.stderr)
        self.assertFalse(any(" install --user" in line for line in self.commands()))

    def test_installation_requires_adbs_explicit_success(self):
        self.adb(install="Performing Streamed Install")
        result = self.run_installer("--android", "test-device", check=False)
        self.assertIn("did not confirm", result.stderr)
        self.assertNotIn("am start", "\n".join(self.commands()))

    def test_signature_mismatch_explains_the_reinstall(self):
        self.adb(install="Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE: signatures do not match]")
        result = self.run_installer("--android", "test-device", check=False)
        self.assertIn("different signing key", result.stderr)


if __name__ == "__main__":
    unittest.main()
