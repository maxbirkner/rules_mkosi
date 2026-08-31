import contextlib
import io
import os
import pathlib
import shutil
import site
import socket
import subprocess
import sys
import threading
import unittest
from unittest import mock

import boot_test


class _FakeClock:
    def __init__(self, values):
        self._values = iter(values)
        self._last = 0

    def monotonic(self):
        try:
            self._last = next(self._values)
        except StopIteration:
            pass
        return self._last

    def sleep(self, _):
        return None


class _FakeProcess:
    def __init__(self, poll_values=None, wait_timeout=False):
        self._poll_values = iter(poll_values or [])
        self._wait_timeout = wait_timeout
        self._wait_calls = 0
        self.returncode = None
        self.terminate_called = False
        self.kill_called = False

    def poll(self):
        if self.returncode is not None:
            return self.returncode
        try:
            value = next(self._poll_values)
        except StopIteration:
            value = None
        if value is not None:
            self.returncode = value
        return value

    def wait(self, timeout=None):
        self._wait_calls += 1
        if self._wait_timeout and self._wait_calls == 1:
            raise subprocess.TimeoutExpired("fake-qemu", timeout)
        self.returncode = 0
        return self.returncode

    def terminate(self):
        self.terminate_called = True
        self.returncode = 0

    def kill(self):
        self.kill_called = True
        self.returncode = -9


class _FakeFactory:
    def __init__(self, process=None, error=None):
        self.process = process
        self.error = error

    def __call__(self, _command, stdout, **_kwargs):
        if self.error is not None:
            raise self.error
        stdout.write(b"qemu diagnostic\n")
        stdout.flush()
        return self.process


class _QmpServer:
    def __init__(self, path, mode):
        self.path = path
        self.mode = mode
        self.error = None
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(path)
        self._server.listen(1)
        self._server.settimeout(1)
        self._thread = threading.Thread(target=self._serve)
        self._thread.start()

    def _serve(self):
        try:
            try:
                connection, _ = self._server.accept()
            except socket.timeout:
                return
            with connection:
                if self.mode == "malformed":
                    connection.sendall(b"not-json\r\n")
                elif self.mode == "partial":
                    connection.sendall(b'{"QMP"')
                else:
                    connection.sendall(b'{"QMP":{"version":{"qemu":{"major":9}}}}\r\n')
                    connection.settimeout(5)
                    connection.recv(4096)
                    if self.mode == "caps_error":
                        connection.sendall(b'{"error":{"class":"GenericError"}}\r\n')
                    elif self.mode == "caps_eof":
                        return
                    else:
                        connection.sendall(b'{"return":{}}\r\n')
        except BaseException as error:
            self.error = error

    def close(self):
        self._server.close()
        self._thread.join(timeout=5)


class BootLifecycleTest(unittest.TestCase):
    def _run_failure(
        self,
        *,
        expected,
        serial=b"serial diagnostic\n",
        process=None,
        process_error=None,
        qmp_mode=None,
        clock=None,
        expect_terminate=False,
    ):
        root = pathlib.Path(os.environ.get("TEST_TMPDIR", "boot-unit-state"))
        state = root / self._testMethodName
        shutil.rmtree(state, ignore_errors=True)
        state.mkdir(parents=True)
        (state / "ovmf-vars.fd").write_bytes(b"vars")
        (state / "guest-serial.log").write_bytes(serial)
        qmp_server = None
        if qmp_mode is not None:
            previous_cwd = os.getcwd()
            os.chdir(state)
            try:
                qmp_server = _QmpServer("qmp.sock", qmp_mode)
            finally:
                os.chdir(previous_cwd)

        factory = _FakeFactory(process=process, error=process_error)
        test_clock = clock
        if test_clock is None:
            if qmp_mode in {"malformed", "partial", "caps_error", "caps_eof"}:
                test_clock = _FakeClock([100, 0, 200])
            elif qmp_mode == "success":
                test_clock = _FakeClock([100, 0, 0, 1])
            else:
                test_clock = _FakeClock([100, 0])
        kwargs = {
            "process_factory": factory,
            "monotonic": test_clock.monotonic,
            "sleep": test_clock.sleep,
        }

        stderr = io.StringIO()
        try:
            with contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit):
                    with mock.patch.dict(os.environ, {"TEST_TMPDIR": str(state)}):
                        boot_test._boot(
                            "image.raw",
                            "qemu",
                            "qemu-data",
                            "ovmf-code",
                            str(state / "ovmf-vars.fd"),
                            **kwargs
                        )
        finally:
            if qmp_server is not None:
                qmp_server.close()
                self.assertFalse(qmp_server._thread.is_alive())

        output = stderr.getvalue()
        self.assertIn(expected + ":", output)
        self.assertIn(serial.decode(errors="replace").strip(), output)
        if process_error is None:
            self.assertIn("qemu diagnostic", output)
        if expect_terminate:
            self.assertTrue(process.terminate_called)
        self.assertFalse((state / "qmp.sock").exists())
        shutil.rmtree(state, ignore_errors=True)
        return output

    def test_exec_failure_uses_exec_category_and_cleanup(self):
        self._run_failure(
            expected="QEMU_EXEC_FAILURE",
            process_error=OSError("missing qemu"),
        )

    def test_process_exit_before_qmp_is_initialization_failure(self):
        process = _FakeProcess(poll_values=[2])
        self._run_failure(
            expected="QEMU_INITIALIZATION_FAILURE",
            process=process,
        )
        self.assertFalse(process.terminate_called)

    def test_qmp_socket_deadline_is_initialization_failure(self):
        process = _FakeProcess()
        clock = _FakeClock([0, 16])
        self._run_failure(
            expected="QEMU_INITIALIZATION_FAILURE",
            process=process,
            clock=clock,
        )
        self.assertTrue(process.terminate_called)

    def test_malformed_qmp_greeting_is_initialization_failure(self):
        self._run_failure(
            expected="QEMU_INITIALIZATION_FAILURE",
            process=_FakeProcess(),
            qmp_mode="malformed",
            expect_terminate=True,
        )

    def test_partial_qmp_greeting_is_initialization_failure(self):
        self._run_failure(
            expected="QEMU_INITIALIZATION_FAILURE",
            process=_FakeProcess(),
            qmp_mode="partial",
            expect_terminate=True,
        )

    def test_capabilities_error_is_initialization_failure(self):
        self._run_failure(
            expected="QEMU_INITIALIZATION_FAILURE",
            process=_FakeProcess(),
            qmp_mode="caps_error",
            expect_terminate=True,
        )

    def test_capabilities_eof_is_initialization_failure(self):
        self._run_failure(
            expected="QEMU_INITIALIZATION_FAILURE",
            process=_FakeProcess(),
            qmp_mode="caps_eof",
            expect_terminate=True,
        )

    def test_initialized_qemu_then_pre_linux_exit_is_firmware_failure(self):
        self._run_failure(
            expected="FIRMWARE_FAILURE",
            process=_FakeProcess(poll_values=[None, 1]),
            qmp_mode="success",
        )

    def test_initialized_qemu_then_linux_exit_is_guest_failure(self):
        self._run_failure(
            expected="GUEST_FAILURE",
            serial=b"Linux version 6.1\n",
            process=_FakeProcess(poll_values=[None, 1]),
            qmp_mode="success",
        )

    def test_readiness_timeout_terminates_process(self):
        process = _FakeProcess()
        clock = _FakeClock([100, 0, 0, 181])
        self._run_failure(
            expected="READINESS_TIMEOUT",
            process=process,
            qmp_mode="success",
            clock=clock,
        )
        self.assertTrue(process.terminate_called)
        self.assertFalse(process.kill_called)

    def test_shutdown_timeout_terminates_process(self):
        process = _FakeProcess(wait_timeout=True)
        self._run_failure(
            expected="SHUTDOWN_FAILURE",
            serial=boot_test.MARKER + b"\n",
            process=process,
            qmp_mode="success",
        )
        self.assertTrue(process.terminate_called)
        self.assertFalse(process.kill_called)


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


if __name__ == "__main__":
    unittest.main(argv=[__file__])
