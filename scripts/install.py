#!/usr/bin/env python3
"""Install the Arch Linux sudo/PAM and Plasma phone-authentication setup."""

import argparse
import contextlib
import difflib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib

REPO = Path(__file__).resolve().parents[1]
MODULE = Path("/usr/lib/security/pam_syauth.so")
ROOT_FILES = {MODULE, Path("/etc/pam.d/sudo"), Path("/etc/pam.d/kde")}


def regular_path(path):
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ValueError(f"Refusing a symlink in installation path: {parent}")


def atomic_write(path, data, mode):
    regular_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".syauth-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def fingerprint(path):
    if not path.exists():
        return None
    digest = hashlib.sha256()
    paths = [path, *sorted(path.rglob("*"))] if path.is_dir() else [path]
    for entry in paths:
        digest.update(str(entry.relative_to(path.parent)).encode())
        digest.update(str(entry.lstat().st_mode).encode())
        if entry.is_symlink():
            digest.update(os.readlink(entry).encode())
        elif entry.is_file():
            digest.update(entry.read_bytes())
    return digest.hexdigest()


class Backup:
    """Keep the first installation's originals and journal subsequent writes."""

    def __init__(self, state):
        self.state = state
        regular_path(state)
        manifest = state / "manifest.json"
        self.data = json.loads(manifest.read_text()) if manifest.exists() else {"originals": {}, "installed": {}}

    def save(self):
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_write(self.state / "manifest.json", json.dumps(self.data).encode(), 0o600)

    def remember(self, path):
        regular_path(path)
        name = str(path)
        if name in self.data["originals"]:
            return
        record = None
        if path.exists():
            info = path.stat()
            slot = str(len(self.data["originals"]))
            target = self.state / slot
            self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
            if path.is_dir():
                shutil.copytree(path, target, symlinks=True)
            else:
                shutil.copy2(path, target)
            record = {"slot": slot, "directory": path.is_dir(), "mode": info.st_mode & 0o777,
                      "uid": info.st_uid, "gid": info.st_gid}
        self.data["originals"][name] = record
        self.save()

    def check(self, for_rollback=False):
        if self.data.get("pending"):
            if for_rollback:
                return
            raise ValueError("An interrupted installation needs recovery: run 'python3 scripts/install.py rollback'")
        for name, expected in self.data["installed"].items():
            if fingerprint(Path(name)) != expected:
                raise ValueError(f"Changed since installation: {name}. Review backups in {self.state} before rollback.")

    def restore(self, check=True):
        if check:
            self.check(for_rollback=True)
        for name, record in self.data["originals"].items():
            path = Path(name)
            regular_path(path)
            if record is None:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink(missing_ok=True)
            else:
                original = self.state / record["slot"]
                path.parent.mkdir(parents=True, exist_ok=True)
                if record["directory"]:
                    with tempfile.TemporaryDirectory(prefix=".syauth-restore-", dir=path.parent) as temporary:
                        staged = Path(temporary) / "package"
                        previous = Path(temporary) / "previous"
                        shutil.copytree(original, staged, symlinks=True)
                        if path.exists():
                            path.rename(previous)
                        try:
                            staged.rename(path)
                        except OSError:
                            if previous.exists():
                                previous.rename(path)
                            raise
                else:
                    atomic_write(path, original.read_bytes(), record["mode"])
                if os.geteuid() == 0:
                    os.chown(path, record["uid"], record["gid"])
        attempt = Path(self.data["attempt"]) if self.data.get("attempt") else None
        if attempt and attempt.parent == self.state.parent and attempt.name.startswith(".syauth-attempt-"):
            regular_path(attempt)
            shutil.rmtree(attempt, ignore_errors=True)
        shutil.rmtree(self.state)

    def apply(self, files, extra_paths=(), action=lambda: None):
        self.check()
        paths = [*files, *extra_paths]
        self.state.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".syauth-attempt-", dir=self.state.parent) as temporary:
            previous = Backup(Path(temporary) / "backup")
            for path in paths:
                previous.remember(path)
                self.remember(path)
            self.data.update(pending=True, attempt=temporary)
            self.save()
            try:
                for path, (data, mode) in files.items():
                    atomic_write(path, data, mode)
                action()
            except BaseException:
                previous.restore(check=False)
                self.data["pending"] = False
                self.data.pop("attempt", None)
                self.save()
                raise
        self.data["installed"].update({str(path): fingerprint(path) for path in paths})
        self.data["pending"] = False
        self.data.pop("attempt", None)
        self.save()


@contextlib.contextmanager
def installation_lock(path):
    regular_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another syauth installation is running") from None
        yield
    finally:
        os.close(fd)


def pam_source(root, service):
    for directory in ("etc/pam.d", "usr/lib/pam.d"):
        source = root / directory / service
        regular_path(source)
        if source.is_file():
            return source.read_text()
    raise ValueError(f"Missing PAM service: {service}")


def pam_config(original, user, service):
    lines = original.splitlines(keepends=True)
    clean = []
    for line in lines:
        if "pam_syauth.so" in line and not line.lstrip().startswith("#"):
            fields = line.split()
            allowed = {"terminal_prompt", "pwfeedback", "on_empty_password", f"socket=/run/user/{user.pw_uid}/syauth/auth.sock"}
            if fields[:3] != ["auth", "sufficient", "pam_syauth.so"] or set(fields[3:]) - allowed:
                raise ValueError(f"Review the existing custom syauth configuration in {service}")
            guard = f"auth [success=1 default=ignore] pam_succeed_if.so user != {user.pw_name} quiet"
            if not clean or " ".join(clean[-1].split()) != guard:
                raise ValueError(f"Missing matching user guard in {service}; review the existing setup")
            clean.pop()
        else:
            clean.append(line)
    indexes = [i for i, line in enumerate(clean) if line.split() == ["auth", "include", "system-auth"]]
    if len(indexes) != 1:
        raise ValueError(f"Expected one 'auth include system-auth' in {service}; custom stacks need manual review")
    options = "terminal_prompt pwfeedback" if service == "sudo" else "on_empty_password"
    block = (f"auth [success=1 default=ignore] pam_succeed_if.so user != {user.pw_name} quiet\n"
             f"auth sufficient pam_syauth.so {options} socket=/run/user/{user.pw_uid}/syauth/auth.sock\n")
    clean.insert(indexes[0], block)
    return "".join(clean).encode()


def kde_auth_stack(root, original, password):
    """Expand Arch's auth includes locally; leave every global service untouched."""
    def expand(text, seen):
        result = []
        for line in text.splitlines(keepends=True):
            row = line.split()
            if len(row) == 3 and row[:2] == ["auth", "include"] and row[2] in {"system-local-login", "system-login"}:
                if row[2] in seen:
                    raise ValueError("Cyclic KDE PAM includes")
                source = pam_source(root, row[2])
                auth = "".join(part for part in source.splitlines(keepends=True)
                               if part.split() and part.split()[0].lstrip("-") == "auth")
                result.append(expand(auth, seen | {row[2]}))
            else:
                result.append(line)
        return "".join(result)
    expanded = expand(original, set())
    if expanded != original:
        rows = list(map(str.split, expanded.splitlines()))
        if not any("pam_faillock.so" in row and "preauth" in row for row in rows):
            preauth = next((row for row in map(str.split, password.splitlines())
                            if len(row) >= 4 and row[0] == "auth" and row[1] in {"required", "requisite"}
                            and row[2] == "pam_faillock.so" and "preauth" in row), None)
            if preauth is None:
                raise ValueError("Cannot preserve KDE's mandatory faillock preauth check")
            lines = expanded.splitlines(keepends=True)
            index = next((i for i, line in enumerate(lines) if line.split() == ["auth", "include", "system-auth"]), None)
            if index is None:
                raise ValueError("Unsupported KDE auth include chain")
            lines.insert(index, "auth requisite " + " ".join(preauth[2:]) + "\n")
            expanded = "".join(lines)
    return expanded


def system_plan(root, user, module):
    if not module.startswith(b"\x7fELF"):
        raise ValueError("The PAM module must be a built ELF library")
    password = pam_source(root, "system-auth")
    if not any("pam_unix.so" in row and {"try_first_pass", "use_first_pass"} & set(row)
               for row in map(str.split, password.splitlines()) if row and row[0] == "auth"):
        raise ValueError("The password stack must reuse PAM_AUTHTOK with pam_unix.so try_first_pass or use_first_pass")
    for directory in ("etc/pam.d", "usr/lib/pam.d"):
        old = root / directory / "kde-fingerprint"
        if old.exists() and re.search(r"^\s*auth\s+.*pam_syauth\.so", old.read_text(), re.M):
            raise ValueError("Remove the old automatic phone block from kde-fingerprint using docs/pam.md first")
    result = {root / str(MODULE).lstrip("/"): (module, 0o644)}
    for service in ("sudo", "kde"):
        original = pam_source(root, service)
        if service == "kde":
            original = kde_auth_stack(root, original, password)
            rows = list(map(str.split, original.splitlines()))
            include = next((i for i, row in enumerate(rows) if row == ["auth", "include", "system-auth"]), 0)
            mandatory = (("required", "pam_shells.so"), ("requisite", "pam_nologin.so"), ("requisite", "pam_faillock.so"))
            if not all(any(row[:3] == ["auth", control, name] and (name != "pam_faillock.so" or "preauth" in row)
                           for row in rows[:include]) for control, name in mandatory):
                raise ValueError("KDE's mandatory shell, nologin, and faillock checks must precede system-auth; review this custom stack")
        result[root / "etc/pam.d" / service] = (pam_config(original, user, service), 0o644)
    return result


def run(command, **kwargs):
    print("+ " + " ".join(map(str, command)), flush=True)
    return subprocess.run(list(map(str, command)), check=True, **kwargs)


def output(command):
    return subprocess.check_output(list(map(str, command)), text=True, timeout=15).strip()


def system_action(args):
    if os.geteuid() != 0:
        raise ValueError("System installation requires pkexec")
    user = pwd.getpwnam(args.user)
    if user.pw_uid == 0 or not re.fullmatch(r"[a-z_][a-z0-9_-]*\$?", user.pw_name):
        raise ValueError("Select an ordinary local user with a PAM-compatible login name")
    state = Path("/var/lib/syauth-installer")
    regular_path(state)
    if state.exists() and (state.stat().st_uid != 0 or state.stat().st_mode & 0o077):
        raise ValueError(f"Backup directory must be root-owned and private: {state}")
    backup = Backup(state)
    if backup.data.get("user", user.pw_uid) != user.pw_uid:
        raise ValueError("This installer manages one desktop user; restore the previous setup first")
    if args.system_action == "rollback":
        if (state / "manifest.json").exists():
            if not set(backup.data["originals"]) <= set(map(str, ROOT_FILES)):
                raise ValueError("Unexpected paths in system backup")
            backup.restore()
        return
    install_system(Path("/"), user, args.artifacts_dir.joinpath("libpam_syauth.so").read_bytes())


def install_system(root, user, module):
    """Apply the system phase; root is injectable for isolated filesystem tests."""
    plan = system_plan(root, user, module)
    backup = Backup(root / "var/lib/syauth-installer")
    for relative in ("var/lib/syauth", "var/lib/syauth/keys", "var/log/syauth"):
        directory = root / relative
        regular_path(directory)
        if directory.exists():
            if directory.stat().st_uid != user.pw_uid or directory.stat().st_mode & 0o077:
                raise ValueError(f"Expected a private directory owned by {user.pw_name}: {directory}")
        else:
            directory.mkdir(parents=True, mode=0o700)
            os.chown(directory, user.pw_uid, user.pw_gid)
    backup.data["user"] = user.pw_uid
    backup.apply(plan)


def elevate(args, action):
    run(["pkexec", "/usr/bin/python3", Path(__file__).resolve(), "--system-action", action,
         "--user", pwd.getpwuid(os.getuid()).pw_name, "--artifacts-dir", args.artifacts_dir])


def paths_for_user():
    home = Path.home()
    config = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    data = Path(os.environ.get("XDG_DATA_HOME", home / ".local/share"))
    state = Path(os.environ.get("XDG_STATE_HOME", home / ".local/state")) / "syauth"
    if not all(path.is_absolute() for path in (home, config, data, state)):
        raise ValueError("XDG configuration, data, and state paths must be absolute")
    return home, config, data, state


def shell_package(config, data):
    name = output(["kreadconfig6", "--file", config / "plasmashellrc", "--group", "Shell", "--key", "ShellPackage"])
    name = name or "org.kde.plasma.desktop"
    if Path(name).name != name:
        raise ValueError("The active Plasma shell must be a package name")
    return data / "plasma/shells" / name, Path("/usr/share/plasma/shells") / name / "contents/lockscreen"


def user_plan(args, home, config):
    directory = config / "systemd/user"
    dropins = directory / "syauth-presenced.service.d"
    files = {
        home / ".local/bin/syauth": ((args.artifacts_dir / "syauth").read_bytes(), 0o755),
        home / ".local/libexec/syauth-presenced": ((args.artifacts_dir / "syauth-presenced").read_bytes(), 0o755),
        directory / "syauth-presenced.service": ((REPO / "crates/syauth-presenced/dist/syauth-presenced.service").read_bytes(), 0o644),
        dropins / "runtime.conf": (b"[Service]\nRuntimeDirectory=syauth\nRuntimeDirectoryMode=0700\nReadWritePaths=%t/syauth\n", 0o644),
        dropins / "binary.conf": (b"[Service]\nExecStart=\nExecStart=%h/.local/libexec/syauth-presenced\n", 0o644),
    }
    if args.phone_address:
        if not re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", args.phone_address):
            raise ValueError("--phone-address must be the phone's bonded Bluetooth MAC address")
        files[dropins / "phone.conf"] = (f"[Service]\nEnvironment=SYAUTH_RECONNECT_DEVICE={args.phone_address.upper()}\n".encode(), 0o644)
    return files


def require(commands):
    missing = [name for name in commands if shutil.which(name) is None]
    if missing:
        raise ValueError("Missing prerequisites: " + ", ".join(missing) + ". See docs/getting-started.md.")


def preflight(args):
    release = Path("/etc/os-release").read_text()
    if not re.search(r"^ID=\"?arch\"?$", release, re.M):
        raise ValueError("This installer supports Arch Linux with KDE Plasma; other systems need the manual guide")
    require(["pkexec", "systemctl", "kreadconfig6", "kwriteconfig6", "bluetoothctl", "pacman", "ldd", "nm"])
    versions = output(["pacman", "-Q", "plasma-desktop", "kscreenlocker"])
    if any(tuple(map(int, line.split()[1].split(":")[-1].split(".")[:2])) < (6, 8) for line in versions.splitlines()):
        raise ValueError("Live lockscreen status requires Plasma and kscreenlocker 6.8 or newer")
    if "Powered: yes" not in output(["bluetoothctl", "show"]):
        raise ValueError("Enable a Bluetooth adapter in KDE before installing")
    output(["systemctl", "--user", "show", "--property=Version", "--value"])
    if not args.skip_build:
        require(["cargo", "cc", "pkg-config"])
    user = pwd.getpwuid(os.getuid())
    # Validate the current stacks before downloading or building anything.
    system_plan(Path("/"), user, b"\x7fELFpreflight")
    home, config, data, _ = paths_for_user()
    shell, source = shell_package(config, data)
    existing_status = paths_for_user()[3] / "kde-status/install.json"
    if existing_status.exists():
        saved = json.loads(existing_status.read_text())
        if saved["target"] != str(shell):
            raise ValueError("The existing live-status installation uses another shell; restore it first")
        package = existing_status.parent / "package" if saved["had_original"] else Path(saved["source"])
    else:
        package = shell if shell.exists() else source.parent.parent
    main = (package / "contents/lockscreen/MainBlock.qml").read_text()
    ui = (package / "contents/lockscreen/LockScreenUi.qml").read_text()
    if main.count("    component FailableLabel") != 1 or ui.count("if (lockScreenUi.showPrompt) {") != 1:
        raise ValueError("Live status requires the supported Plasma 6.8 shell layout")
    print(f"Desktop user: {user.pw_name} (UID {user.pw_uid})\nCLI: {home / '.local/bin/syauth'}\nPlasma override: {shell}")
    return shell, source


def validate_artifacts(directory):
    for name in ("syauth", "syauth-presenced", "libpam_syauth.so"):
        if not (directory / name).read_bytes().startswith(b"\x7fELF"):
            raise ValueError(f"Expected a built ELF artifact: {directory / name}")
    module = directory / "libpam_syauth.so"
    result = run(["ldd", "-r", module], capture_output=True, text=True)
    diagnostics = result.stdout + result.stderr
    if "not found" in diagnostics or "undefined symbol:" in diagnostics:
        raise ValueError(f"PAM module has unresolved libraries or symbols:\n{diagnostics}")
    exports = {line.split()[-1] for line in output(["nm", "-D", "--defined-only", module]).splitlines() if line.split()}
    if not {"pam_sm_authenticate", "pam_sm_setcred"} <= exports:
        raise ValueError("The module is missing required PAM entry points")


def install_desktop(args):
    shell, source = preflight(args)
    if not args.skip_build and args.artifacts_dir.name != "release":
        raise ValueError("Build output must end in /release; use --skip-build for other artifact directories")
    if args.phone_address and not re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", args.phone_address):
        raise ValueError("--phone-address must be the phone's bonded Bluetooth MAC address")
    if args.dry_run:
        user = pwd.getpwuid(os.getuid())
        plan = system_plan(Path("/"), user, b"\x7fELFpreview")
        for service in ("sudo", "kde"):
            before = pam_source(Path("/"), service).splitlines(keepends=True)
            path = Path("/etc/pam.d") / service
            print("".join(difflib.unified_diff(before, plan[path][0].decode().splitlines(keepends=True),
                                             fromfile=str(path), tofile=str(path))), end="")
        build = "use existing desktop binaries" if args.skip_build else "build desktop binaries"
        print(f"Dry run: {build}, back up existing files, install sudo/PAM and live Plasma status via pkexec, enable the user daemon.")
        if args.android:
            print(f"Optional Android: build the AAR and APK, then update device {args.android} for Android user 0.")
        return
    if args.skip_build:
        validate_artifacts(args.artifacts_dir)
    if args.android:
        install_android(args)
    if not args.skip_build:
        build_env = dict(os.environ, CARGO_TARGET_DIR=str(args.artifacts_dir.parent))
        run(["cargo", "build", "--release", "--locked", "-p", "syauth-cli", "-p", "syauth-pam", "-p", "syauth-presenced"], cwd=REPO, env=build_env)
    home, config, _, state = paths_for_user()
    files = user_plan(args, home, config)
    if not args.skip_build:
        validate_artifacts(args.artifacts_dir)
    backup = Backup(state / "installer")
    if "service" not in backup.data:
        backup.data["service"] = {name: subprocess.run(["systemctl", "--user", f"is-{name}", "syauth-presenced"], capture_output=True).returncode == 0
                                  for name in ("active", "enabled")}

    def configure():
        run([sys.executable, REPO / "scripts/install-kde-status.py", "--shell-dir", shell,
             "--source", source, "--state-dir", state / "kde-status", "--cli", home / ".local/bin/syauth"])
        run(["kwriteconfig6", "--file", config / "kscreenlockerrc", "--group", "UI",
             "--key", "ShowPromptInRegularAuthenticator", "--type", "bool", "true"])
        elevate(args, "install")

    backup.apply(files, [shell, state / "kde-status", config / "kscreenlockerrc"], configure)
    run(["systemctl", "--user", "daemon-reload"])
    run(["systemctl", "--user", "enable", "--now", "syauth-presenced"])
    run(["systemctl", "--user", "restart", "syauth-presenced"])
    print("Installed. Open a new lockscreen to see live phone status. Test sudo with 'sudo -k' followed by 'sudo -i'.")
    print("Pair a new phone with: python3 scripts/install.py pair")
    print("After testing phone and password authentication, enable the pacman checker with: python3 scripts/install.py update-check")


def rollback(args):
    state = paths_for_user()[3] / "installer"
    backup = Backup(state)
    backup.check(for_rollback=True)
    elevate(args, "rollback")
    if not (state / "manifest.json").exists():
        print("No desktop-user backup to restore.")
        return
    service = backup.data["service"]
    run(["systemctl", "--user", "stop", "syauth-presenced"])
    if not service["enabled"]:
        run(["systemctl", "--user", "disable", "syauth-presenced"])
    backup.restore()
    run(["systemctl", "--user", "daemon-reload"])
    if service["enabled"]:
        run(["systemctl", "--user", "enable", "syauth-presenced"])
    if service["active"]:
        run(["systemctl", "--user", "start", "syauth-presenced"])
    print("Restored the pre-installer setup. Pairing data and the Android app were preserved.")


def pair():
    cli = Path.home() / ".local/bin/syauth"
    if not cli.is_file():
        raise ValueError("Run the desktop installer before pairing")
    active = subprocess.run(["systemctl", "--user", "is-active", "syauth-presenced"], capture_output=True).returncode == 0
    run(["systemctl", "--user", "stop", "syauth-presenced"])
    try:
        print("Open Pair with computer on your phone. Compare and confirm both Bluetooth and app codes on both devices.")
        run([cli, "pair", "--timeout-secs", "300"])
    finally:
        if active:
            run(["systemctl", "--user", "start", "syauth-presenced"])


def install_android(args):
    require(["adb"])
    adb = ["adb", "-s", args.android]
    if output([*adb, "shell", "am", "get-current-user"]) != "0":
        raise ValueError("Android installation requires the selected device's current user to be 0")
    if int(output([*adb, "shell", "getprop", "ro.build.version.sdk"])) < 33:
        raise ValueError("Production pairing requires Android 13/API 33 or newer with Keystore Ed25519 support")
    if not args.skip_build:
        build_android()
    if output([*adb, "shell", "am", "get-current-user"]) != "0":
        raise ValueError("Android user changed during the build; switch back to user 0 before installing")
    apk = REPO / "syauth-android/app/build/outputs/apk/debug/app-debug.apk"
    result = run([*adb, "install", "--user", "0", "-r", apk], capture_output=True, text=True)
    if "Success" not in result.stdout.splitlines():
        raise ValueError(f"Android did not confirm installation: {result.stdout}\n{result.stderr}")
    run([*adb, "shell", "am", "start", "--user", "0", "-n", "com.sy.syauth.android/.MainActivity"])


def build_android():
    require(["cargo", "cargo-ndk", "rustup", "java", "jar", "zip", "make"])
    env = os.environ.copy()
    sdk = Path(env.get("ANDROID_HOME", Path.home() / "Android/Sdk"))
    if not sdk.is_dir():
        raise ValueError("Set ANDROID_HOME to an installed Android SDK, including platform 34")
    env["ANDROID_HOME"] = str(sdk)
    ndks = sorted((p for p in (sdk / "ndk").glob("*") if re.fullmatch(r"\d+\.\d+\.\d+", p.name)), key=lambda p: tuple(map(int, p.name.split("."))))
    ndk = Path(env["NDK_HOME"]) if env.get("NDK_HOME") else ndks[-1] if ndks else None
    if ndk is None or not ndk.is_dir():
        raise ValueError("Install an Android NDK and set NDK_HOME")
    env["NDK_HOME"] = str(ndk)
    env["CARGO_TARGET_DIR"] = str(REPO / "target")
    env.pop("DEBUG", None)
    env.pop("DRY_RUN", None)
    run(["rustup", "target", "add", "aarch64-linux-android", "armv7-linux-androideabi", "x86_64-linux-android", "i686-linux-android"])
    version = next(p["version"] for p in tomllib.loads((REPO / "Cargo.lock").read_text())["package"] if p["name"] == "uniffi")
    with tempfile.TemporaryDirectory(prefix="syauth-bindgen-") as directory:
        tool = Path(directory)
        (tool / "src").mkdir()
        (tool / "Cargo.toml").write_text(f'[package]\nname = "syauth-bindgen-tool"\nversion = "0.1.0"\nedition = "2024"\n[dependencies]\nuniffi = {{ version = "={version}", features = ["cli"] }}\n[[bin]]\nname = "uniffi-bindgen"\npath = "src/main.rs"\n')
        (tool / "src/main.rs").write_text("fn main() { uniffi::uniffi_bindgen_main(); }\n")
        run(["cargo", "build", "--release", "--manifest-path", tool / "Cargo.toml"], env=env)
        env["PATH"] = str(REPO / "target/release") + os.pathsep + env["PATH"]
        run(["make", "android-aar"], cwd=REPO, env=env)
    run([REPO / "syauth-android/gradlew", "-p", REPO / "syauth-android", "--no-parallel",
         "-Pkotlin.compiler.execution.strategy=in-process", ":app:assembleDebug", ":app:testDebugUnitTest"], env=env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("install", "rollback", "pair", "update-check"), default="install")
    parser.add_argument("--phone-address", help="Bonded phone MAC; preserve an existing phone.conf when omitted")
    parser.add_argument("--android", metavar="SERIAL", help="Also build/install the Android app on this ADB device, user 0")
    parser.add_argument("--skip-build", action="store_true", help="Use existing desktop binaries and, with --android, an existing APK")
    parser.add_argument("--artifacts-dir", type=Path, default=REPO / "target/release")
    parser.add_argument("--dry-run", action="store_true", help="Check the installation plan without builds or file changes")
    parser.add_argument("--system-action", choices=("install", "rollback"), help=argparse.SUPPRESS)
    parser.add_argument("--user", help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.artifacts_dir = args.artifacts_dir.resolve()
    if args.system_action:
        if not args.user:
            parser.error("System phase requires --user")
        if os.geteuid() != 0:
            raise ValueError("System installation requires pkexec")
        with installation_lock(Path("/var/lib/syauth-installer.lock")):
            system_action(args)
        return
    if os.geteuid() == 0:
        parser.error("Run as your desktop user, not with sudo or pkexec. The installer elevates only its system phase.")
    if args.dry_run and args.action != "install":
        parser.error("--dry-run is supported only for install")
    lock = contextlib.nullcontext() if args.dry_run else installation_lock(paths_for_user()[3] / ".installer.lock")
    with lock:
        if args.action == "install":
            install_desktop(args)
        elif args.action == "rollback":
            rollback(args)
        elif args.action == "pair":
            pair()
        else:
            run(["pkexec", "/usr/bin/bash", REPO / "deploy/arch/install-update-check.sh"])


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Installation failed: {error}", file=sys.stderr)
        for detail in (getattr(error, "stdout", None), getattr(error, "stderr", None)):
            if detail:
                print(detail, file=sys.stderr)
        sys.exit(1)
