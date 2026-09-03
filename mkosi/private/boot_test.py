"""Deterministic serial-console boot lifecycle used by Bazel boot tests."""

import json
import os

os.environ["PATH"] = ""

import importlib.util
import pathlib
import shutil
import socket
import subprocess
import sys
import time


def _load_diagnostics():
    path = pathlib.Path(__file__).with_name("diagnostics.py")
    spec = importlib.util.spec_from_file_location("mkosi_diagnostics", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("diagnostic formatter cannot be loaded: {}".format(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


diagnostics = _load_diagnostics()


class QmpHandshakeError(RuntimeError):
    """QEMU did not complete its management initialization handshake."""


def _resolve_runfile(path):
    if os.path.isabs(path):
        return path
    manifest = os.environ.get("RUNFILES_MANIFEST_FILE")
    if manifest and os.path.isfile(manifest):
        with open(manifest, encoding="utf-8") as entries:
            for line in entries:
                logical, physical = line.rstrip("\n").split(" ", 1)
                if logical in (path, "../" + path, "external/" + path):
                    return physical
    root = os.environ.get("RUNFILES_DIR", sys.argv[0] + ".runfiles")
    candidates = (
        os.path.join(root, path),
        os.path.join(root, "_main", path),
        os.path.join(root, path.removeprefix("external/")),
        os.path.join(root, "_main", path.removeprefix("external/")),
    )
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    diagnostics.fail(
        "TOOLCHAIN_FAILURE",
        "required Bazel runfile is unavailable: {}".format(path),
    )


def _read_log(path):
    try:
        return pathlib.Path(path).read_bytes()
    except OSError:
        return b"<log unavailable>\n"


def _diagnose(kind, message, serial_log, qemu_log, diagnostic_bytes):
    diagnostics.report("VM_FAILURE", "{}: {}".format(kind, message))
    for title, path in (("serial log", serial_log), ("QEMU log", qemu_log)):
        print("%s (%s):" % (title, path), file=sys.stderr)
        print(
            _read_log(path)[-diagnostic_bytes:].decode(errors="replace"),
            file=sys.stderr,
        )
    raise SystemExit(1)


def _perform_qmp_handshake(connection, timeout):
    connection.settimeout(timeout)
    reader = connection.makefile("rb")
    try:
        greeting_line = reader.readline()
        if not greeting_line:
            raise QmpHandshakeError("QMP greeting was empty")
        try:
            greeting = json.loads(greeting_line)
        except json.JSONDecodeError as error:
            raise QmpHandshakeError("QMP greeting was not valid JSON") from error
        if not isinstance(greeting, dict) or "QMP" not in greeting:
            raise QmpHandshakeError("QMP greeting was missing")

        connection.sendall(b'{"execute":"qmp_capabilities"}\r\n')
        response_line = reader.readline()
        if not response_line:
            raise QmpHandshakeError("QMP capabilities response was empty")
        try:
            response = json.loads(response_line)
        except json.JSONDecodeError as error:
            raise QmpHandshakeError(
                "QMP capabilities response was not valid JSON",
            ) from error
        if not isinstance(response, dict) or "return" not in response:
            raise QmpHandshakeError("QMP capabilities command failed")
    except socket.timeout as error:
        raise QmpHandshakeError("QMP handshake timed out") from error
    finally:
        reader.close()


def _qmp_handshake(process, socket_path, timeout, monotonic=time.monotonic, sleep=time.sleep):
    deadline = monotonic() + timeout
    last_error = "QMP socket was not ready"
    while monotonic() < deadline:
        if process.poll() is not None:
            raise QmpHandshakeError(
                "QEMU exited with status %d before QMP initialization"
                % process.returncode,
            )
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.settimeout(max(0.1, deadline - monotonic()))
            connection.connect(socket_path)
            _perform_qmp_handshake(connection, max(0.1, deadline - monotonic()))
            return
        except (OSError, QmpHandshakeError) as error:
            last_error = str(error)
        finally:
            connection.close()
        sleep(0.05)
    raise QmpHandshakeError(last_error)


def _guest_started(serial):
    return b"Linux version" in serial or b"systemd[" in serial


def _classify_process_exit(qemu_initialized, serial, returncode):
    del returncode
    if not qemu_initialized:
        return "QEMU_INITIALIZATION_FAILURE"
    if _guest_started(serial):
        return "GUEST_FAILURE"
    return "FIRMWARE_FAILURE"


def _qemu_environment(scratch):
    return {
        "HOME": str(scratch),
        "LANG": "C.UTF-8",
        "PATH": "",
        "TMPDIR": str(scratch),
    }


def _has_clean_shutdown(serial_log, markers):
    serial = _read_log(serial_log)
    return all(marker.encode() in serial for marker in markers)


def _stop_process(process, timeout=5):
    if process.poll() is not None:
        return True
    process.terminate()
    try:
        process.wait(timeout=timeout)
        return True
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.wait(timeout=timeout)
            return True
        except subprocess.TimeoutExpired:
            return False


def _boot(
    image,
    qemu,
    system_data,
    *,
    qemu_args=(),
    machine_args=(),
    firmware_code=None,
    firmware_vars=None,
    kernel_preflight=None,
    readiness_marker="",
    expected_failure_marker="",
    stop_after_readiness=False,
    shutdown_markers=(),
    boot_timeout_seconds=180,
    qmp_initialization_timeout_seconds=15,
    shutdown_timeout_seconds=30,
    diagnostic_bytes=65536,
    process_factory=subprocess.Popen,
    qmp_handshake=_qmp_handshake,
    monotonic=time.monotonic,
    sleep=time.sleep,
):
    scratch = pathlib.Path(os.environ.get("TEST_TMPDIR", "boot-test-state"))
    scratch.mkdir(parents=True, exist_ok=True)
    image = os.path.abspath(image)
    qemu = os.path.abspath(qemu)
    system_data = os.path.abspath(system_data)
    if firmware_code:
        firmware_code = os.path.abspath(firmware_code)
    if firmware_vars:
        firmware_vars = os.path.abspath(firmware_vars)
    vars_copy = scratch / "firmware-vars.fd"
    serial_log = scratch / "guest-serial.log"
    qemu_log = scratch / "qemu.log"
    qmp_socket = "qmp.sock"
    qmp_socket_file = scratch / qmp_socket
    process = None
    try:
        if kernel_preflight:
            diagnostics.run_kernel_preflight(kernel_preflight, "QEMU boot test")
        if firmware_vars:
            shutil.copyfile(firmware_vars, vars_copy)
            vars_copy.chmod(0o600)
        expanded_qemu_args = [
            argument.replace("{firmware_code}", firmware_code or "").replace(
                "{firmware_vars}",
                str(vars_copy),
            )
            for argument in (qemu_args or machine_args)
        ]
        command = [
            qemu,
            "-L",
            system_data,
        ] + expanded_qemu_args + [
            "-accel",
            "tcg",
            "-nodefaults",
            "-nographic",
            "-no-reboot",
            "-serial",
            "none",
            "-chardev",
            "file,id=serial0,path=%s" % serial_log,
            "-device",
            "isa-serial,chardev=serial0",
            "-qmp",
            "unix:%s,server=on,wait=off" % qmp_socket,
            "-drive",
            "if=virtio,format=raw,snapshot=on,file=%s" % image,
        ]
        environment = _qemu_environment(scratch)
        with open(qemu_log, "wb") as output:
            try:
                process = process_factory(
                    command,
                    cwd=scratch,
                    env=environment,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                )
            except OSError as error:
                _diagnose(
                    "QEMU_EXEC_FAILURE",
                    str(error),
                    serial_log,
                    qemu_log,
                    diagnostic_bytes,
                )

            try:
                original_cwd = os.open(".", os.O_RDONLY)
                try:
                    os.chdir(scratch)
                    try:
                        qmp_handshake(
                            process,
                            qmp_socket,
                            qmp_initialization_timeout_seconds,
                            monotonic,
                            sleep,
                        )
                    except QmpHandshakeError as error:
                        _diagnose(
                            "QEMU_INITIALIZATION_FAILURE",
                            str(error),
                            serial_log,
                            qemu_log,
                            diagnostic_bytes,
                        )
                finally:
                    os.fchdir(original_cwd)
                    os.close(original_cwd)

                deadline = monotonic() + boot_timeout_seconds
                while monotonic() < deadline:
                    serial = _read_log(serial_log)
                    readiness_offset = serial.find(readiness_marker.encode())
                    failure_offset = (
                        serial.find(expected_failure_marker.encode())
                        if expected_failure_marker else -1
                    )
                    if expected_failure_marker:
                        if failure_offset >= 0 and (
                            readiness_offset < 0 or failure_offset < readiness_offset
                        ):
                            excerpt_start = max(0, failure_offset - 256)
                            excerpt_end = min(
                                len(serial),
                                failure_offset + len(expected_failure_marker) + 256,
                            )
                            print(
                                "Expected failure evidence:\n{}".format(
                                    serial[excerpt_start:excerpt_end].decode(errors="replace")
                                )
                            )
                            _stop_process(process)
                            return
                        if readiness_offset >= 0:
                            _diagnose(
                                "GUEST_FAILURE",
                                "observed readiness before exact expected failure marker %r"
                                % expected_failure_marker,
                                serial_log,
                                qemu_log,
                                diagnostic_bytes,
                            )
                    elif readiness_offset >= 0:
                        if stop_after_readiness:
                            _stop_process(process)
                            return
                        break
                    if process.poll() is not None:
                        _diagnose(
                            _classify_process_exit(True, serial, process.returncode),
                            "QEMU exited before readiness",
                            serial_log,
                            qemu_log,
                            diagnostic_bytes,
                        )
                    sleep(0.1)
                else:
                    _diagnose(
                        "READINESS_TIMEOUT",
                        "did not observe exact serial marker %r" % readiness_marker,
                        serial_log,
                        qemu_log,
                        diagnostic_bytes,
                    )

                try:
                    process.wait(timeout=shutdown_timeout_seconds)
                except subprocess.TimeoutExpired:
                    _stop_process(process)
                    _diagnose(
                        "SHUTDOWN_FAILURE",
                        "guest did not terminate before the shutdown deadline",
                        serial_log,
                        qemu_log,
                        diagnostic_bytes,
                    )
                if process.returncode != 0:
                    _diagnose(
                        "GUEST_FAILURE",
                        "QEMU exited with status %d after readiness" % process.returncode,
                        serial_log,
                        qemu_log,
                        diagnostic_bytes,
                    )
                if not _has_clean_shutdown(serial_log, shutdown_markers):
                    _diagnose(
                        "SHUTDOWN_FAILURE",
                        "guest exited without the exact shutdown markers",
                        serial_log,
                        qemu_log,
                        diagnostic_bytes,
                    )
                print("guest readiness and clean shutdown verified")
            finally:
                if process.poll() is None:
                    if not _stop_process(process):
                        _diagnose(
                            "SHUTDOWN_FAILURE",
                            "QEMU did not exit after the kill deadline",
                            serial_log,
                            qemu_log,
                            diagnostic_bytes,
                        )
    finally:
        try:
            qmp_socket_file.unlink()
        except FileNotFoundError:
            pass


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: boot_test.py CONFIG")
    config = json.loads(pathlib.Path(_resolve_runfile(sys.argv[1])).read_text())
    _boot(
        _resolve_runfile(config["image"]),
        _resolve_runfile(config["qemu"]),
        _resolve_runfile(config["system_data"]),
        qemu_args=config["qemu_args"],
        firmware_code=_resolve_runfile(config["firmware_code"]),
        firmware_vars=_resolve_runfile(config["firmware_vars"]),
        kernel_preflight=_resolve_runfile(config["kernel_preflight"]),
        readiness_marker=config["readiness_marker"],
        expected_failure_marker=config.get("expected_failure_marker", ""),
        stop_after_readiness=config.get("stop_after_readiness", False),
        shutdown_markers=config["shutdown_markers"],
        boot_timeout_seconds=config["boot_timeout_seconds"],
        qmp_initialization_timeout_seconds=config["qmp_initialization_timeout_seconds"],
        shutdown_timeout_seconds=config["shutdown_timeout_seconds"],
        diagnostic_bytes=config["diagnostic_bytes"],
    )


if __name__ == "__main__":
    main()
