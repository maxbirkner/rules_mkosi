import os
import pathlib
import socket
import sys
import site
import threading
import unittest

import boot_test


class QmpHandshakeTest(unittest.TestCase):
    def test_greeting_and_capabilities_transition_to_initialized(self):
        client, server = socket.socketpair()

        def respond():
            with server:
                server.sendall(b'{"QMP":{"version":{"qemu":{"major":9}}}}\r\n')
                self.assertIn(b"qmp_capabilities", server.recv(4096))
                server.sendall(b'{"return":{}}\r\n')

        responder = threading.Thread(target=respond)
        responder.start()
        try:
            self.assertTrue(boot_test._perform_qmp_handshake(client))
        finally:
            client.close()
            responder.join()

    def test_invalid_greeting_does_not_initialize_qemu(self):
        client, server = socket.socketpair()
        with server:
            server.sendall(b'{"error":{"class":"GenericError"}}\r\n')
            with self.assertRaisesRegex(boot_test.QmpHandshakeError, "greeting"):
                boot_test._perform_qmp_handshake(client)
        client.close()


class LauncherContractTest(unittest.TestCase):
    def test_initial_executable_is_managed_python_without_user_site(self):
        interpreter = pathlib.Path(sys.executable).resolve()
        self.assertIn("rules_python", str(interpreter))
        self.assertTrue(interpreter.name.startswith("python3."))
        self.assertTrue(sys.argv[0].endswith("boot_test_unit.py"))
        self.assertEqual("", os.environ["PATH"])
        self.assertEqual("1", os.environ.get("PYTHONNOUSERSITE"))
        self.assertFalse(site.ENABLE_USER_SITE)
        self.assertNotIn(str(pathlib.Path.home()), sys.path)

    def test_qemu_child_has_empty_path(self):
        environment = boot_test._qemu_environment(pathlib.Path("test-state"))
        self.assertEqual("", environment["PATH"])


class ExitClassificationTest(unittest.TestCase):
    def test_exit_before_qmp_handshake_is_qemu_initialization_failure(self):
        self.assertEqual(
            "QEMU_INITIALIZATION_FAILURE",
            boot_test._classify_process_exit(False, b"", 1),
        )

    def test_initialized_qemu_without_linux_is_firmware_failure(self):
        self.assertEqual(
            "FIRMWARE_FAILURE",
            boot_test._classify_process_exit(True, b"OVMF initialized\n", 1),
        )

    def test_initialized_qemu_with_linux_is_guest_failure(self):
        self.assertEqual(
            "GUEST_FAILURE",
            boot_test._classify_process_exit(True, b"Linux version 6.1\n", 1),
        )


if __name__ == "__main__":
    unittest.main(argv=[__file__])
