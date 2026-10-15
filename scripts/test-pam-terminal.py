#!/usr/bin/env python3
"""Test the real PAM module on a private PTY and private PAM service.

Requires a readable /var/lib/syauth/bonds.toml with a bonded phone. Only its
public bond metadata is read; a private mock socket replaces the real daemon.
No system PAM configuration, password, key, or Bluetooth state is changed.
"""

import argparse
import os
from pathlib import Path
import pty
import select
import signal
import socket
import struct
import subprocess
import tempfile
import termios
import time


def cbor(value):
    def head(major, length):
        return bytes([major * 32 + length]) if length < 24 else bytes([major * 32 + 24, length])
    if isinstance(value, bool):
        return b"\xf5" if value else b"\xf4"
    if value is None:
        return b"\xf6"
    if isinstance(value, str):
        encoded = value.encode()
        return head(3, len(encoded)) + encoded
    if isinstance(value, bytes):
        return head(2, len(value)) + value
    return head(5, len(value)) + b"".join(cbor(key) + cbor(item) for key, item in value.items())


def response(approved):
    payload = cbor({"kind": "challenge", "ok": approved, "signature": b"s" * 64 if approved else None,
                    "reason": "ok" if approved else "denied"})
    return struct.pack("!I", len(payload)) + payload


def run_case(root, module, fixture, driver, name, password=None, approval=None, interrupt=None, fragment=False, feedback=False):
    directory = root / name
    directory.mkdir()
    path = directory / "auth.sock"
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(path))
    listener.listen(1)
    listener.settimeout(5)
    config = f"auth sufficient {module} terminal_prompt {'pwfeedback' if feedback else ''} socket={path}\nauth required {fixture} test-password\n"
    (directory / "syauth-terminal-test").write_text(config)
    pid, master = pty.fork()
    if pid == 0:
        os.execl(str(driver), str(driver), str(directory))
    connection = None
    output = bytearray()
    status = None
    try:
        connection, _ = listener.accept()
        connection.settimeout(5)
        request = connection.recv(4096)
        assert request, "module must request a phone challenge"
        deadline = time.monotonic() + 5
        while b"Password or approve" not in output and time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                output.extend(os.read(master, 4096))
        assert b"Password or approve" in output, f"terminal prompt missing: {output!r}"
        os.write(master, b"partial-secret" if password is None else password[:2])
        if feedback:
            deadline = time.monotonic() + 1
            while b"**" not in output and time.monotonic() < deadline:
                if select.select([master], [], [], .05)[0]:
                    output.extend(os.read(master, 4096))
            assert b"**" in output, "typed characters must show masked feedback before Enter"
        if fragment:
            connection.sendall(b"\x00")
        if approval is not None:
            connection.sendall(response(approval))
        if password is not None:
            os.write(master, password[2:] + b"\n")
        if interrupt == signal.SIGINT:
            os.write(master, b"\x03")
        elif interrupt is not None:
            os.kill(pid, interrupt)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if select.select([master], [], [], 0.05)[0]:
                try:
                    output.extend(os.read(master, 4096))
                except OSError:
                    pass
            waited, result = os.waitpid(pid, os.WNOHANG)
            if waited:
                status = result
                break
        assert status is not None, f"authentication blocked: {name}: {output!r}"
        os.set_blocking(master, False)
        while True:
            try:
                chunk = os.read(master, 4096)
                if not chunk:
                    break
                output.extend(chunk)
            except (BlockingIOError, OSError):
                break
        assert termios.tcgetattr(master)[3] & termios.ECHO, "terminal echo must be restored"
        if interrupt is not None:
            assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == interrupt, (name, status, output)
        else:
            expected = 7 if password == b"wrong-password" else 0
            assert f"RESULT:{expected}".encode() in output, (name, status, output)
        assert b"Test password:" not in output, "submitted password must be reused without a second prompt"
        assert b"partial-secret" not in output, "password bytes must never be echoed"
        try:
            assert connection.recv(1) == b"", "completed race must close its daemon socket"
        except ConnectionResetError:
            pass  # Closing a socket with an unread denial/partial frame resets it.
        print(f"PASS {name}")
    finally:
        if status is None:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
        if connection is not None:
            connection.close()
        listener.close()
        os.close(master)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", required=True, type=Path)
    parser.add_argument("--fixtures", type=Path, default=Path(__file__).resolve().parents[1] / "crates/syauth-pam/tests/fixtures")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="pam-pty-") as directory:
        root = Path(directory)
        fixture, driver = root / "password.so", root / "driver"
        subprocess.run(["cc", "-shared", "-fPIC", "-o", str(fixture), str(args.fixtures / "pam_submission.c"), "-lpam", "-ldl"], check=True)
        subprocess.run(["cc", "-o", str(driver), str(args.fixtures / "pam_terminal_driver.c"), "-lpam"], check=True)
        cases = [
            ("password-feedback", {"password": b"test-password", "feedback": True}),
            ("feedback-backspace", {"password": b"tex\x7fst-password", "feedback": True}),
            ("feedback-unicode-erase", {"password": b"te\xc3\xa9\x7fst-password", "feedback": True}),
            ("feedback-kill-line", {"password": b"junk\x15test-password", "feedback": True}),
            ("feedback-kill-word", {"password": b"test-junk\x17test-password", "feedback": True}),
            ("feedback-phone-approval", {"approval": True, "feedback": True}),
            ("feedback-ctrl-c", {"interrupt": signal.SIGINT, "feedback": True}),
            ("phone-approval", {"approval": True}),
            ("password-first", {"password": b"test-password"}),
            ("wrong-password", {"password": b"wrong-password"}),
            ("phone-denied", {"password": b"test-password", "approval": False}),
            ("partial-daemon-frame", {"password": b"test-password", "fragment": True}),
            ("ctrl-c", {"interrupt": signal.SIGINT}),
            ("termination", {"interrupt": signal.SIGTERM}),
        ]
        for name, kwargs in cases:
            run_case(root, args.module.resolve(), fixture, driver, name, **kwargs)


if __name__ == "__main__":
    main()
