import contextlib
import io
import json
import pathlib
import socket
import subprocess
import tempfile
import unittest
from unittest import mock

from mkosi.private import boot_test


class _Process:
    def __init__(self, polls=(), wait_error=False, returncode=0):
        self._polls = iter(polls)
        self._wait_error = wait_error
        self.returncode = None
        self.final_returncode = returncode
        self.terminated = False
        self.killed = False

    def poll(self):
        if self.returncode is not None:
            return self.returncode
        try:
            value = next(self._polls)
        except StopIteration:
            value = None
        if value is not None:
            self.returncode = value
        return value

    def wait(self, timeout=None):
        if self._wait_error and not self.terminated:
            raise subprocess.TimeoutExpired("qemu", timeout)
        self.returncode = self.final_returncode
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9


class _StubbornProcess(_Process):
    def wait(self, timeout=None):
        raise subprocess.TimeoutExpired("qemu", timeout)


class BootLifecycleTest(unittest.TestCase):
    def _run(
        self,
        expected,
        *,
        serial=b"serial diagnostic\n",
        process=None,
        process_error=None,
        handshake=None,
        clock_values=(0, 1),
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "vars.fd").write_bytes(b"vars")
            (root / "guest-serial.log").write_bytes(serial)
            process = process or _Process()

            def factory(_command, stdout, **_kwargs):
                stdout.write(b"qemu diagnostic\n")
                stdout.flush()
                if process_error:
                    raise process_error
                return process

            clock = iter(clock_values)
            last = [0]

            def monotonic():
                try:
                    last[0] = next(clock)
                except StopIteration:
                    pass
                return last[0]

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit):
                    with mock.patch.dict(
                        "os.environ",
                        {"TEST_TMPDIR": directory},
                        clear=False,
                    ):
                        boot_test._boot(
                            "image.raw",
                            "qemu",
                            "qemu-data",
                            firmware_code="code.fd",
                            firmware_vars=str(root / "vars.fd"),
                            readiness_marker="READY",
                            shutdown_markers=("SHUTDOWN", "POWERDOWN"),
                            process_factory=factory,
                            qmp_handshake=handshake or (lambda *_args: None),
                            monotonic=monotonic,
                            sleep=lambda _seconds: None,
                        )
            output = stderr.getvalue()
            self.assertIn(expected + ":", output)
            self.assertIn(serial.decode().splitlines()[0], output)
            self.assertIn("qemu diagnostic", output)
            self.assertFalse((root / "qmp.sock").exists())
            return process

    def test_launch_failure(self):
        self._run("QEMU_EXEC_FAILURE", process_error=OSError("missing qemu"))

    def test_qmp_initialization_failure(self):
        self._run(
            "QEMU_INITIALIZATION_FAILURE",
            handshake=lambda *_args: (_ for _ in ()).throw(
                boot_test.QmpHandshakeError("malformed greeting"),
            ),
        )

    def test_firmware_exit_before_readiness(self):
        self._run("FIRMWARE_FAILURE", process=_Process(polls=(1,)))

    def test_guest_exit_before_readiness(self):
        self._run(
            "GUEST_FAILURE",
            serial=b"Linux version 6.1\n",
            process=_Process(polls=(1,)),
        )

    def test_readiness_timeout(self):
        self._run(
            "READINESS_TIMEOUT",
            process=_Process(),
            clock_values=(0, 0, 181),
        )

    def test_unexpected_guest_exit_after_readiness(self):
        self._run(
            "GUEST_FAILURE",
            serial=b"READY\nLinux version 6.1\n",
            process=_Process(returncode=1),
        )

    def test_shutdown_timeout(self):
        process = _Process(wait_error=True)
        self._run(
            "SHUTDOWN_FAILURE",
            serial=b"READY\nSHUTDOWN\nPOWERDOWN\n",
            process=process,
        )
        self.assertTrue(process.terminated)

    def test_post_kill_cleanup_is_bounded(self):
        process = _StubbornProcess()
        self._run(
            "SHUTDOWN_FAILURE",
            serial=b"READY\nSHUTDOWN\nPOWERDOWN\n",
            process=process,
        )
        self.assertTrue(process.killed)

    def test_qmp_socket_stays_short_with_long_test_tmpdir(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory) / ("long-" * 30)
            root.mkdir()
            vars_file = root / "vars.fd"
            vars_file.write_bytes(b"vars")
            (root / "guest-serial.log").write_bytes(b"READY\n")
            process = _Process()
            observed = {}

            def factory(command, stdout, cwd, env, **_kwargs):
                observed["command"] = command
                observed["cwd"] = cwd
                observed["env"] = env
                stdout.flush()
                return process

            def handshake(_process, socket_path, *_args):
                observed["socket_path"] = socket_path

            with mock.patch.dict(
                "os.environ",
                {"TEST_TMPDIR": str(root)},
                clear=False,
            ):
                boot_test._boot(
                    "image.raw",
                    "qemu",
                    "qemu-data",
                    firmware_code="code.fd",
                    firmware_vars=str(vars_file),
                    readiness_marker="READY",
                    shutdown_markers=(),
                    process_factory=factory,
                    qmp_handshake=handshake,
                    sleep=lambda _seconds: None,
                )

            self.assertEqual("qmp.sock", observed["socket_path"])
            self.assertEqual(root, observed["cwd"])
            self.assertIn("unix:qmp.sock,server=on,wait=off", observed["command"])
            self.assertTrue(observed["command"][0].startswith("/"))
            self.assertIn("file=/", observed["command"][-1])
            self.assertEqual(str(root), observed["env"]["TMPDIR"])
            self.assertEqual("", observed["env"]["PATH"])
            self.assertFalse((root / "qmp.sock").exists())

    def test_qmp_malformed_and_eof_are_bounded_errors(self):
        for payload in (b"not-json\n", b""):
            left, right = socket.socketpair()
            try:
                right.sendall(payload)
                right.shutdown(socket.SHUT_WR)
                with self.assertRaises(boot_test.QmpHandshakeError):
                    boot_test._perform_qmp_handshake(left, 0.2)
            finally:
                left.close()
                right.close()

    def test_config_is_json_and_preserves_exact_markers(self):
        value = json.dumps(
            {
                "readiness_marker": "READY",
                "shutdown_markers": ["SHUTDOWN", "POWERDOWN"],
            },
        )
        self.assertEqual("READY", json.loads(value)["readiness_marker"])


if __name__ == "__main__":
    unittest.main()
