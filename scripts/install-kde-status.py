#!/usr/bin/env python3
"""Install live phone status into the active user's Plasma shell package."""

import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile


MARKER = "// syauth live phone status"
ANCHOR = "    component FailableLabel"


def default_component():
    """Use the checkout's component, or the copy the syauth package ships."""
    checkout = Path(__file__).resolve().parents[1] / "deploy/kde/PhoneStatus.qml"
    return checkout if checkout.is_file() else Path("/usr/share/syauth/kde/PhoneStatus.qml")


def install(shell, source, cli, state, socket=None, qml=None):
    qml = qml or default_component()
    backup = state / "package"
    manifest = state / "install.json"
    if manifest.exists():
        saved = json.loads(manifest.read_text())
        if saved["target"] != str(shell):
            raise ValueError("A different package is already installed; uninstall it first")
        package = backup if saved["had_original"] else Path(saved["source"])
    else:
        package = shell if shell.exists() else source.parent.parent
    metadata = json.loads((package / "metadata.json").read_text())
    if metadata.get("KPackageStructure") != "Plasma/Shell":
        raise ValueError("The greeter requires a Plasma/Shell package")
    lockscreen = package / "contents/lockscreen"
    original = (lockscreen / "MainBlock.qml").read_text()
    ui = (lockscreen / "LockScreenUi.qml").read_text()
    prompt = "if (lockScreenUi.showPrompt) {"
    if original.count(ANCHOR) != 1 or MARKER in original or ui.count(prompt) != 1:
        raise ValueError("Unsupported lockscreen layout; no package files were changed")
    command = shlex.join([str(cli), "status", "--json"] + (["--socket", str(socket)] if socket else []))
    component = (
        f"    {MARKER}\n"
        "    readonly property alias syauthStatus: syauthStatusItem\n"
        "    PhoneStatus {\n"
        "        id: syauthStatusItem\n"
        "        Layout.fillWidth: true\n"
        "        visible: sessionManager.passwordInputVisible\n"
        f"        command: {json.dumps(command)}\n"
        "    }\n\n"
    )
    state.mkdir(parents=True, exist_ok=True)
    shell.parent.mkdir(parents=True, exist_ok=True)
    if not manifest.exists():
        had_original = shell.exists()
        if had_original:
            shutil.copytree(shell, backup, symlinks=True)
        manifest.write_text(json.dumps({"target": str(shell), "source": str(package), "had_original": had_original}))
    with tempfile.TemporaryDirectory(prefix=".syauth-status-", dir=shell.parent) as temporary:
        staged = Path(temporary) / "package"
        shutil.copytree(package, staged, symlinks=True)
        target = staged / "contents/lockscreen"
        (target / "MainBlock.qml").write_text(original.replace(ANCHOR, component + ANCHOR))
        condition = "if (lockScreenUi.showPrompt && !mainBlock.syauthStatus.isSelectorPrompt(authenticator.promptForSecret)) {"
        (target / "LockScreenUi.qml").write_text(ui.replace(prompt, condition))
        shutil.copyfile(qml, target / "PhoneStatus.qml")
        previous = Path(temporary) / "previous"
        if shell.exists():
            shell.rename(previous)
        try:
            staged.rename(shell)
        except OSError:
            if previous.exists():
                previous.rename(shell)
            raise
    print(f"Installed phone status in {shell}. It appears the next time the lockscreen opens.")


def uninstall(state):
    manifest = state / "install.json"
    saved = json.loads(manifest.read_text())
    target = Path(saved["target"])
    if target.exists():
        shutil.rmtree(target)
    if saved["had_original"]:
        shutil.copytree(state / "package", target, symlinks=True)
    shutil.rmtree(state)
    print(f"Restored {target}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shell-dir", type=Path)
    parser.add_argument("--source", type=Path, default=Path("/usr/share/plasma/shells/org.kde.plasma.desktop/contents/lockscreen"))
    parser.add_argument("--cli", type=Path, default=Path(shutil.which("syauth") or "/usr/bin/syauth"))
    parser.add_argument("--component", type=Path, default=default_component(), help="PhoneStatus.qml to install")
    parser.add_argument("--socket", type=Path)
    parser.add_argument("--state-dir", type=Path, default=Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "syauth/kde-status")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()
    if args.uninstall:
        uninstall(args.state_dir)
        return
    if not args.cli.is_file():
        parser.error(f"syauth CLI not found: {args.cli}")
    shell = args.shell_dir
    if shell is None:
        package = subprocess.check_output(["kreadconfig6", "--file", "plasmashellrc", "--group", "Shell", "--key", "ShellPackage"], text=True).strip() or "org.kde.plasma.desktop"
        if Path(package).name != package:
            parser.error("Cannot determine the active shell; supply --shell-dir")
        shell = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "plasma/shells" / package
        if package != "org.kde.plasma.desktop" and args.source == parser.get_default("source"):
            args.source = Path("/usr/share/plasma/shells") / package / "contents/lockscreen"
    install(shell.resolve(), args.source.resolve(), args.cli.resolve(), args.state_dir.resolve(), args.socket, args.component.resolve())


if __name__ == "__main__":
    main()
