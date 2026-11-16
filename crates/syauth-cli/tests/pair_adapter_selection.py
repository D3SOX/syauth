"""Run `syauth pair` against an isolated BlueZ D-Bus peer, without a radio."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

try:
    import dbus
except ImportError:
    dbus = None

CONTROL = "com.sy.syauth.Test"


@unittest.skipUnless(dbus is not None and shutil.which("dbus-daemon"), "requires python-dbus, PyGObject and dbus-daemon")
class PairAdapterSelection(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bond_dir = Path(self.temp.name) / "bonds"
        bus_process = self.start(["dbus-daemon", "--session", "--nofork", "--print-address=1"])
        address = bus_process.stdout.readline().strip()
        self.env = dict(os.environ, DBUS_SYSTEM_BUS_ADDRESS=address)
        mock = self.start([sys.executable, os.environ["SYAUTH_BLUEZ_MOCK"], "--mock"], env=self.env)
        self.assertEqual(mock.stdout.readline().strip(), "READY")
        bus = dbus.bus.BusConnection(address)
        self.addCleanup(bus.close)
        self.control = dbus.Interface(bus.get_object("org.bluez", "/", introspect=False), CONTROL)

    def start(self, command, **kwargs):
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, **kwargs)
        self.addCleanup(self.stop, process)
        return process

    @staticmethod
    def stop(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()

    def pair(self, *args):
        return self.start([os.environ["SYAUTH_CLI_BINARY"], "pair", "--bond-dir", str(self.bond_dir), *args],
                          env=self.env)

    def pair_error(self, *args):
        process = self.pair(*args)
        try:
            _, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            self.fail("pair kept running instead of failing")
        self.assertNotEqual(process.returncode, 0)
        return stderr

    def test_default_adapter_follows_renamed_controller(self):
        self.control.AddAdapter("hci1")
        process = self.pair()
        self.assertEqual(process.stdout.readline().strip(), "adapter hci1 ready (LE Secure Connections: yes)")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            apps, advertisements = self.control.Registrations()
            if "hci1" in apps and "hci1" in advertisements:
                return
            if process.poll() is not None:
                self.fail("pair exited before advertising: " + process.stderr.read())
            time.sleep(0.02)
        self.fail("pair did not register GATT and advertise on hci1")

    def test_missing_named_adapter_lists_the_available_ones(self):
        self.control.AddAdapter("hci1")
        self.assertIn("error: bluetooth adapter 'hci0' not found; available adapters: hci1; "
                      "omit --adapter to use BlueZ's default", self.pair_error("--adapter", "hci0"))

    def test_no_adapter_at_all_is_reported(self):
        self.assertIn("error: no bluetooth adapter found", self.pair_error())


if __name__ == "__main__":
    unittest.main()
