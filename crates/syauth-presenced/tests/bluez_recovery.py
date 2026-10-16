"""Exercise the real daemon against an isolated BlueZ D-Bus peer, without a radio."""

import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

try:
    import dbus
    import dbus.service
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib
except ImportError:
    dbus = None

ADAPTER = "org.bluez.Adapter1"
OBJECTS = "org.freedesktop.DBus.ObjectManager"
CONTROL = "com.sy.syauth.Test"
PROPERTIES = "org.freedesktop.DBus.Properties"


def serve_mock():
    DBusGMainLoop(set_as_default=True)
    bus = dbus.bus.BusConnection(os.environ["DBUS_SYSTEM_BUS_ADDRESS"])
    name = dbus.service.BusName("org.bluez", bus)

    class Adapter(dbus.service.Object):
        def __init__(self, controller):
            self.controller = controller
            self.props = {"Address": "AA:BB:CC:DD:EE:FF", "Powered": True}
            super().__init__(name, "/org/bluez/" + controller)

        @dbus.service.method(PROPERTIES, in_signature="ss", out_signature="v")
        def Get(self, interface, prop):
            return self.props[prop]

        @dbus.service.method(PROPERTIES, in_signature="ssv", out_signature="")
        def Set(self, interface, prop, value):
            self.props[prop] = value

        @dbus.service.method("org.bluez.GattManager1", in_signature="oa{sv}", out_signature="")
        def RegisterApplication(self, path, options):
            root.apps.append(self.controller)

        @dbus.service.method("org.bluez.GattManager1", in_signature="o", out_signature="")
        def UnregisterApplication(self, path):
            pass

        @dbus.service.method("org.bluez.LEAdvertisingManager1", in_signature="oa{sv}", out_signature="")
        def RegisterAdvertisement(self, path, options):
            if root.fail_advertising:
                raise dbus.exceptions.DBusException("registration lost", name="org.bluez.Error.Failed")
            root.advertisements.append(self.controller)

        @dbus.service.method("org.bluez.LEAdvertisingManager1", in_signature="o", out_signature="")
        def UnregisterAdvertisement(self, path):
            pass

    class Root(dbus.service.Object):
        def __init__(self):
            self.adapters = {}
            self.apps = []
            self.advertisements = []
            self.fail_advertising = False
            super().__init__(name, "/")

        @dbus.service.method(OBJECTS, out_signature="a{oa{sa{sv}}}")
        def GetManagedObjects(self):
            return {adapter.__dbus_object_path__: {ADAPTER: adapter.props} for adapter in self.adapters.values()}

        @dbus.service.signal(OBJECTS, signature="oas")
        def InterfacesRemoved(self, path, interfaces):
            pass

        @dbus.service.method(CONTROL, in_signature="s", out_signature="")
        def AddAdapter(self, controller):
            self.adapters[controller] = Adapter(controller)

        @dbus.service.method(CONTROL, in_signature="s", out_signature="")
        def RemoveAdapter(self, controller):
            adapter = self.adapters.pop(controller)
            self.InterfacesRemoved(adapter.__dbus_object_path__, [ADAPTER])
            adapter.remove_from_connection()

        @dbus.service.method(CONTROL, out_signature="asas")
        def Registrations(self):
            return self.apps, self.advertisements

        @dbus.service.method(CONTROL, in_signature="b", out_signature="")
        def FailAdvertising(self, fail):
            self.fail_advertising = bool(fail)

    class Agent(dbus.service.Object):
        @dbus.service.method("org.bluez.AgentManager1", in_signature="os", out_signature="")
        def RegisterAgent(self, path, capability):
            pass

        @dbus.service.method("org.bluez.AgentManager1", in_signature="o", out_signature="")
        def RequestDefaultAgent(self, path):
            pass

        @dbus.service.method("org.bluez.AgentManager1", in_signature="o", out_signature="")
        def UnregisterAgent(self, path):
            pass

    root = Root()
    agent = Agent(name, "/org/bluez")
    print("READY", flush=True)
    GLib.MainLoop().run()


@unittest.skipUnless(dbus is not None and shutil.which("dbus-daemon"), "requires python-dbus, PyGObject and dbus-daemon")
class BluetoothRecovery(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bus_process = self.start(["dbus-daemon", "--session", "--nofork", "--print-address=1"])
        address = self.bus_process.stdout.readline().strip()
        self.env = dict(os.environ, DBUS_SYSTEM_BUS_ADDRESS=address)
        self.mock = self.start([sys.executable, __file__, "--mock"], env=self.env)
        self.assertEqual(self.mock.stdout.readline().strip(), "READY")
        bus = dbus.bus.BusConnection(address)
        self.addCleanup(bus.close)
        self.control = dbus.Interface(bus.get_object("org.bluez", "/", introspect=False), CONTROL)
        self.binary = os.environ["SYAUTH_DAEMON_BINARY"]

    def start(self, command, **kwargs):
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **kwargs)
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
        process.stdout.close()
        process.stderr.close()

    def daemon(self):
        return self.start([self.binary, "--socket", str(self.root / "auth.sock"),
                           "--pidfile", str(self.root / "daemon.pid"), "--bonds-file", str(self.root / "bonds.toml"),
                           "--keys-dir", str(self.root / "keys"), "--audit-log", str(self.root / "audit.log")], env=self.env)

    def wait_advertised(self, process, controller):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            apps, advertisements = self.control.Registrations()
            if controller in apps and controller in advertisements:
                return
            if process.poll() is not None:
                self.fail("daemon exited before advertising: " + process.stderr.read())
            time.sleep(0.02)
        self.fail(f"daemon did not register GATT and advertise on {controller}")

    def assert_restartable_exit(self, process):
        try:
            self.assertNotEqual(process.wait(timeout=5), 0, "systemd needs a failure exit to restart")
        except subprocess.TimeoutExpired:
            self.fail("daemon stayed alive with unusable Bluetooth registrations")
        self.assertFalse((self.root / "auth.sock").exists())
        self.assertFalse((self.root / "daemon.pid").exists())

    def test_only_hci1_is_available_after_resume(self):
        self.control.AddAdapter("hci1")
        self.wait_advertised(self.daemon(), "hci1")

    def test_adapter_reenumerates_and_next_process_rehydrates(self):
        self.control.AddAdapter("hci0")
        first = self.daemon()
        self.wait_advertised(first, "hci0")
        self.control.RemoveAdapter("hci0")
        self.control.AddAdapter("hci1")
        self.assert_restartable_exit(first)
        self.wait_advertised(self.daemon(), "hci1")

    def test_no_adapter_at_startup_exits_for_retry(self):
        self.assert_restartable_exit(self.daemon())
        self.control.AddAdapter("hci1")
        self.wait_advertised(self.daemon(), "hci1")

    def test_initial_advertisement_failure_exits_for_retry(self):
        self.control.AddAdapter("hci0")
        self.control.FailAdvertising(True)
        self.assert_restartable_exit(self.daemon())
        self.control.FailAdvertising(False)
        self.wait_advertised(self.daemon(), "hci0")

    def test_failed_advertisement_exits_instead_of_rotating_forever(self):
        self.control.AddAdapter("hci0")
        first = self.daemon()
        self.wait_advertised(first, "hci0")
        self.control.FailAdvertising(True)
        os.kill(first.pid, signal.SIGHUP)
        self.assert_restartable_exit(first)
        self.control.FailAdvertising(False)
        self.wait_advertised(self.daemon(), "hci0")


if __name__ == "__main__":
    if "--mock" in sys.argv:
        serve_mock()
    else:
        unittest.main()
