"""Deterministic serial-console boot lifecycle used by Bazel boot tests."""

import json
import os

os.environ["PATH"] = ""

import dataclasses
import pathlib
import runpy
import shutil
import socket
import subprocess
import sys
import time

_load_sibling = runpy.run_path(str(pathlib.Path(__file__).with_name("sibling_loader.py")))["load_sibling"]
diagnostics = _load_sibling(__file__, "diagnostics")


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


def _bounded_content(data, limit):
    if len(data) <= limit:
        return data
    marker = b"\n--- bounded log: middle omitted ---\n"
    if limit <= len(marker):
        return data[:limit]
    remaining = max(0, limit - len(marker))
    head = remaining // 2
    return data[:head] + marker + data[-(remaining - head) :]


def _actual_boot_evidence(firmware, serial, limit, markers=(), accelerator=None):
    stages = (
        ("firmware", firmware, (b"SeaBIOS", b"Booting from Hard Disk", b"Booting from 0000:7c00")),
        (
            "serial",
            serial,
            (
                b"GRUB",
                b"Linux version",
                b"systemd[1]: Hostname set to",
                b"systemd-shutdown[1]: Powering off.",
                b"reboot: Power down",
            )
            + tuple(marker.encode() for marker in markers if marker),
        ),
    )
    output = [b"[qemu] accelerator: " + (accelerator or "unknown").encode()]
    for source, content, markers in stages:
        for line in content.splitlines():
            if any(marker in line for marker in markers):
                output.append(b"[" + source.encode() + b"] " + line)
    return _bounded_content(b"\n".join(output) + b"\n", limit)


def _export_boot_logs(serial_log, firmware_log, qemu_log, diagnostic_bytes, markers=(), accelerator=None):
    output_directory = os.environ.get("TEST_UNDECLARED_OUTPUTS_DIR")
    if not output_directory:
        return
    destination = pathlib.Path(output_directory)
    try:
        destination.mkdir(parents=True, exist_ok=True)
        limit = min(diagnostic_bytes, 256 * 1024)
        serial = _read_log(serial_log)
        firmware = _read_log(firmware_log)
        for name, content in (
            ("guest-serial.log", serial),
            ("firmware.log", firmware),
            ("qemu.log", _read_log(qemu_log)),
            ("boot-evidence.log", _actual_boot_evidence(firmware, serial, limit, markers, accelerator)),
        ):
            (destination / name).write_bytes(_bounded_content(content, limit))
    except OSError as error:
        print("unable to export bounded boot logs: {}".format(error), file=sys.stderr)


def _diagnose(
    kind,
    message,
    serial_log,
    qemu_log,
    diagnostic_bytes,
    firmware_log=None,
):
    diagnostics.report("VM_FAILURE", "{}: {}".format(kind, message))
    logs = [("serial log", serial_log)]
    if firmware_log:
        logs.append(("firmware log", firmware_log))
    logs.append(("QEMU log", qemu_log))
    for title, path in logs:
        print("%s (%s):" % (title, path), file=sys.stderr)
        print(
            _read_log(path)[-diagnostic_bytes:].decode(errors="replace"),
            file=sys.stderr,
        )
    raise SystemExit(1)


def _read_qmp_message(reader, description):
    line = reader.readline()
    if not line:
        raise QmpHandshakeError("{} was empty".format(description))
    try:
        return json.loads(line)
    except json.JSONDecodeError as error:
        raise QmpHandshakeError("{} was not valid JSON".format(description)) from error


def _perform_qmp_handshake(connection, timeout):
    connection.settimeout(timeout)
    reader = connection.makefile("rb")
    try:
        greeting = _read_qmp_message(reader, "QMP greeting")
        if not isinstance(greeting, dict) or "QMP" not in greeting:
            raise QmpHandshakeError("QMP greeting was missing")

        connection.sendall(b'{"execute":"qmp_capabilities"}\r\n')
        response = _read_qmp_message(reader, "QMP capabilities response")
        if not isinstance(response, dict) or "return" not in response:
            raise QmpHandshakeError("QMP capabilities command failed")

        connection.sendall(b'{"execute":"query-kvm"}\r\n')
        while True:
            reply = _read_qmp_message(reader, "QMP query-kvm response")
            # Asynchronous QMP events may precede the command reply.
            if not isinstance(reply, dict) or "event" not in reply:
                return _accelerator_from_query_kvm(reply)
    except socket.timeout as error:
        raise QmpHandshakeError("QMP handshake timed out") from error
    finally:
        reader.close()


def _accelerator_from_query_kvm(reply):
    """Returns the accelerator QEMU selected, "kvm" or "tcg", from a QMP query-kvm reply."""
    result = reply.get("return") if isinstance(reply, dict) else None
    enabled = result.get("enabled") if isinstance(result, dict) else None
    if not isinstance(enabled, bool):
        raise QmpHandshakeError("QMP query-kvm command failed")
    return "kvm" if enabled else "tcg"


def _qmp_handshake(process, socket_path, timeout, monotonic=time.monotonic, sleep=time.sleep):
    """Completes the QMP handshake and returns the accelerator QEMU selected."""
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
            return _perform_qmp_handshake(connection, max(0.1, deadline - monotonic()))
        except (OSError, QmpHandshakeError) as error:
            last_error = str(error)
        finally:
            connection.close()
        sleep(0.05)
    raise QmpHandshakeError(last_error)


def _ordered_progress(serial, markers):
    """Returns the offset after the last ordered progress marker and the first missing marker index."""
    offset = 0
    for index, marker in enumerate(markers):
        found = serial.find(marker.encode(), offset)
        if found < 0:
            return offset, index
        offset = found + len(marker.encode())
    return offset, None


def _resolve_runfile_directory(path):
    """Returns a runfiles directory, or a mapping of its relative file names when only a manifest lists them."""
    manifest = os.environ.get("RUNFILES_MANIFEST_FILE")
    if manifest and os.path.isfile(manifest):
        files = {}
        prefixes = (path, "../" + path, "external/" + path)
        with open(manifest, encoding="utf-8") as entries:
            for line in entries:
                logical, physical = line.rstrip("\n").split(" ", 1)
                for prefix in prefixes:
                    if logical == prefix and os.path.isdir(physical):
                        return physical
                    if logical.startswith(prefix + "/"):
                        files[logical[len(prefix) + 1 :]] = physical
        if files:
            return files
    return _resolve_runfile(path)


def _link_or_copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copyfile(source, destination)


def _materialize_share(source, destination):
    """Recreates a share as regular files, hard-linking them where possible.

    Bazel may present tree artifacts as directories of symlinks into the output base, or only list their files
    in a runfiles manifest. QEMU's 9p server would expose host symlinks verbatim, so the guest needs a tree of
    regular files instead. source is a directory or a mapping from relative file names to files.
    """
    destination.mkdir(parents=True)
    if isinstance(source, dict):
        for relative, physical in sorted(source.items()):
            _link_or_copy(os.path.realpath(physical), destination / relative)
        return
    for entry in sorted(os.listdir(source)):
        path = os.path.realpath(os.path.join(source, entry))
        if os.path.isdir(path):
            _materialize_share(path, destination / entry)
        else:
            _link_or_copy(path, destination / entry)


def _virtfs_arguments(shares, scratch):
    """Returns QEMU arguments exposing each (directory, mount tag) pair as a read-only virtio-9p share."""
    arguments = []
    for directory, mount_tag in shares:
        materialized = scratch / "shares" / mount_tag
        shutil.rmtree(materialized, ignore_errors=True)
        _materialize_share(directory, materialized)
        arguments += [
            "-virtfs",
            "local,path={},mount_tag={},security_model=none,readonly=on".format(
                str(materialized).replace(",", ",,"),
                mount_tag,
            ),
        ]
    return arguments


def _guest_started(serial):
    return b"Linux version" in serial or b"systemd[" in serial


def _classify_pre_readiness_failure(serial, firmware, firmware_kind):
    combined = serial + b"\n" + firmware
    if _guest_started(serial):
        return "GUEST_FAILURE"
    if firmware_kind == "seabios":
        if any(
            marker in combined
            for marker in (
                b"Boot failed: not a bootable disk",
                b"No bootable device",
                b"Could not read from Boot Medium",
            )
        ):
            return "MISSING_BOOT_SECTOR"
        if b"GRUB" in combined:
            return "GRUB_FAILURE"
    return "FIRMWARE_FAILURE"


def _classify_process_exit(
    qemu_initialized,
    serial,
    returncode,
    firmware=b"",
    firmware_kind="",
):
    del returncode
    if not qemu_initialized:
        return "QEMU_INITIALIZATION_FAILURE"
    return _classify_pre_readiness_failure(serial, firmware, firmware_kind)


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


@dataclasses.dataclass(frozen=True)
class _BootFiles:
    """Scratch files of one boot and the bounded diagnostics that report them."""

    scratch: pathlib.Path
    diagnostic_bytes: int

    @property
    def vars_copy(self):
        return self.scratch / "firmware-vars.fd"

    @property
    def serial_log(self):
        return self.scratch / "guest-serial.log"

    @property
    def qemu_log(self):
        return self.scratch / "qemu.log"

    @property
    def firmware_log(self):
        return self.scratch / "firmware.log"

    def fail(self, kind, message, include_firmware_log=True):
        _diagnose(
            kind,
            message,
            self.serial_log,
            self.qemu_log,
            self.diagnostic_bytes,
            self.firmware_log if include_firmware_log else None,
        )


_QMP_SOCKET = "qmp.sock"


def _absolute_or_none(path):
    return os.path.abspath(path) if path else path


def _qemu_command(files, image, qemu, system_data, *, arguments, firmware_code, firmware, accelerator_args,
                  allow_reboot, share_arguments, disk_interface):
    expanded_arguments = [
        argument.replace("{firmware_code}", firmware_code or "")
        .replace("{firmware_vars}", str(files.vars_copy))
        .replace("{firmware}", firmware or "")
        .replace("{firmware_log}", str(files.firmware_log))
        for argument in arguments
    ]
    return [
        qemu,
        "-L",
        system_data,
    ] + expanded_arguments + list(accelerator_args) + [
        "-nodefaults",
        "-nographic",
    ] + ([] if allow_reboot else ["-no-reboot"]) + share_arguments + [
        "-serial",
        "none",
        "-chardev",
        "file,id=serial0,path=%s" % files.serial_log,
        "-device",
        "isa-serial,chardev=serial0",
        "-qmp",
        "unix:%s,server=on,wait=off" % _QMP_SOCKET,
        "-drive",
        "if=%s,format=raw,snapshot=on,file=%s" % (disk_interface, image),
    ]


def _share_arguments(files, read_only_shares):
    try:
        return _virtfs_arguments(read_only_shares, files.scratch)
    except OSError as error:
        files.fail("SHARE_FAILURE", "cannot prepare read-only share: {}".format(error), include_firmware_log=False)


def _start_qemu(files, process_factory, command, output):
    try:
        return process_factory(
            command,
            cwd=files.scratch,
            env=_qemu_environment(files.scratch),
            stdout=output,
            stderr=subprocess.STDOUT,
        )
    except OSError as error:
        files.fail("QEMU_EXEC_FAILURE", str(error))


def _initialize_qmp(files, process, qmp_handshake, timeout, monotonic, sleep):
    """Completes the QMP handshake from the scratch directory, keeping the socket path short."""
    original_cwd = os.open(".", os.O_RDONLY)
    try:
        os.chdir(files.scratch)
        try:
            return qmp_handshake(process, _QMP_SOCKET, timeout, monotonic, sleep)
        except QmpHandshakeError as error:
            files.fail("QEMU_INITIALIZATION_FAILURE", str(error))
    finally:
        os.fchdir(original_cwd)
        os.close(original_cwd)


@dataclasses.dataclass(frozen=True)
class _Readiness:
    """Serial markers that decide when a boot is ready, failed as expected, or timed out."""

    marker: str
    progress_markers: tuple
    expected_failure_marker: str
    stop_after_readiness: bool
    firmware_kind: str
    timeout_seconds: float


@dataclasses.dataclass(frozen=True)
class _SerialObservation:
    serial: bytes
    firmware: bytes
    missing_progress: int | None
    readiness_offset: int
    failure_offset: int


def _observe(files, readiness):
    serial = _read_log(files.serial_log)
    firmware_output = _read_log(files.firmware_log)
    progress_offset, missing_progress = _ordered_progress(serial, readiness.progress_markers)
    readiness_offset = (
        serial.find(readiness.marker.encode(), progress_offset)
        if missing_progress is None
        else -1
    )
    failure_offset = (
        serial.find(readiness.expected_failure_marker.encode())
        if readiness.expected_failure_marker else -1
    )
    return _SerialObservation(serial, firmware_output, missing_progress, readiness_offset, failure_offset)


def _print_expected_failure(observation, expected_failure_marker):
    serial = observation.serial
    excerpt_start = max(0, observation.failure_offset - 256)
    excerpt_end = min(len(serial), observation.failure_offset + len(expected_failure_marker) + 256)
    print(
        "Expected failure evidence:\n{}".format(
            serial[excerpt_start:excerpt_end].decode(errors="replace")
        )
    )


def _expected_failure_observed(files, observation, expected_failure_marker):
    """Returns whether the exact failure marker appeared first; readiness before it fails the test."""
    failure_offset = observation.failure_offset
    readiness_offset = observation.readiness_offset
    if failure_offset >= 0 and (readiness_offset < 0 or failure_offset < readiness_offset):
        _print_expected_failure(observation, expected_failure_marker)
        return True
    if readiness_offset >= 0:
        files.fail(
            "GUEST_FAILURE",
            "observed readiness before exact expected failure marker %r" % expected_failure_marker,
            include_firmware_log=False,
        )
    return False


def _fail_readiness_timeout(files, observation, readiness):
    firmware_output = _read_log(files.firmware_log)
    timeout_kind = "READINESS_TIMEOUT"
    if not readiness.expected_failure_marker:
        timeout_kind = _classify_pre_readiness_failure(observation.serial, firmware_output, readiness.firmware_kind)
        if timeout_kind == "FIRMWARE_FAILURE":
            timeout_kind = "READINESS_TIMEOUT"
    missing_marker = readiness.marker
    if observation.missing_progress is not None:
        missing_marker = readiness.progress_markers[observation.missing_progress]
    files.fail(timeout_kind, "did not observe exact serial marker %r" % missing_marker)


def _await_readiness(files, process, readiness, monotonic, sleep):
    """Polls the serial log until readiness; returns True when the test already finished and QEMU was stopped."""
    deadline = monotonic() + readiness.timeout_seconds
    while monotonic() < deadline:
        observation = _observe(files, readiness)
        if readiness.expected_failure_marker:
            if _expected_failure_observed(files, observation, readiness.expected_failure_marker):
                _stop_process(process)
                return True
        elif observation.readiness_offset >= 0:
            if readiness.stop_after_readiness:
                _stop_process(process)
                return True
            return False
        if process.poll() is not None:
            files.fail(
                _classify_process_exit(
                    True, observation.serial, process.returncode, observation.firmware, readiness.firmware_kind
                ),
                "QEMU exited before readiness",
            )
        sleep(0.1)
    _fail_readiness_timeout(files, observation, readiness)


def _await_clean_shutdown(files, process, shutdown_markers, shutdown_timeout_seconds):
    try:
        process.wait(timeout=shutdown_timeout_seconds)
    except subprocess.TimeoutExpired:
        _stop_process(process)
        files.fail("SHUTDOWN_FAILURE", "guest did not terminate before the shutdown deadline")
    if process.returncode != 0:
        files.fail("GUEST_FAILURE", "QEMU exited with status %d after readiness" % process.returncode)
    if not _has_clean_shutdown(files.serial_log, shutdown_markers):
        files.fail("SHUTDOWN_FAILURE", "guest exited without the exact shutdown markers")


def _print_boot_evidence(files, markers, accelerator):
    evidence = _actual_boot_evidence(
        _read_log(files.firmware_log),
        _read_log(files.serial_log),
        min(files.diagnostic_bytes, 256 * 1024),
        markers,
        accelerator,
    )
    print("actual observed boot evidence:")
    print(evidence.decode(errors="replace"), end="")
    print("guest readiness and clean shutdown verified")


def _ensure_stopped(files, process):
    if process.poll() is None:
        if not _stop_process(process):
            files.fail("SHUTDOWN_FAILURE", "QEMU did not exit after the kill deadline")


def _boot(
    image,
    qemu,
    system_data,
    *,
    qemu_args=(),
    machine_args=(),
    firmware_code=None,
    firmware_vars=None,
    firmware=None,
    firmware_kind="",
    disk_interface="virtio",
    accelerator_args=(),
    kernel_preflight=None,
    readiness_marker="",
    progress_markers=(),
    expected_failure_marker="",
    stop_after_readiness=False,
    allow_reboot=False,
    read_only_shares=(),
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
    files = _BootFiles(scratch, diagnostic_bytes)
    firmware_vars = _absolute_or_none(firmware_vars)
    markers = tuple(progress_markers) + (readiness_marker,)
    readiness = _Readiness(
        readiness_marker,
        tuple(progress_markers),
        expected_failure_marker,
        stop_after_readiness,
        firmware_kind,
        boot_timeout_seconds,
    )
    accelerator = None
    try:
        if kernel_preflight:
            diagnostics.run_kernel_preflight(kernel_preflight, "QEMU boot test")
        if firmware_vars:
            shutil.copyfile(firmware_vars, files.vars_copy)
            files.vars_copy.chmod(0o600)
        command = _qemu_command(
            files,
            os.path.abspath(image),
            os.path.abspath(qemu),
            os.path.abspath(system_data),
            arguments=qemu_args or machine_args,
            firmware_code=_absolute_or_none(firmware_code),
            firmware=_absolute_or_none(firmware),
            accelerator_args=accelerator_args,
            allow_reboot=allow_reboot,
            share_arguments=_share_arguments(files, read_only_shares),
            disk_interface=disk_interface,
        )
        with open(files.qemu_log, "wb") as output:
            process = _start_qemu(files, process_factory, command, output)
            try:
                accelerator = _initialize_qmp(
                    files, process, qmp_handshake, qmp_initialization_timeout_seconds, monotonic, sleep
                )
                print("QEMU accelerator: {}".format(accelerator or "unknown"), flush=True)
                if _await_readiness(files, process, readiness, monotonic, sleep):
                    return
                _await_clean_shutdown(files, process, shutdown_markers, shutdown_timeout_seconds)
                _print_boot_evidence(files, markers, accelerator)
            finally:
                _ensure_stopped(files, process)
    finally:
        _export_boot_logs(files.serial_log, files.firmware_log, files.qemu_log, diagnostic_bytes, markers, accelerator)
        try:
            (scratch / _QMP_SOCKET).unlink()
        except FileNotFoundError:
            pass


def _optional_runfile(config, key):
    return _resolve_runfile(config[key]) if config.get(key) else None


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: boot_test.py CONFIG")
    config = json.loads(pathlib.Path(_resolve_runfile(sys.argv[1])).read_text())
    _boot(
        _resolve_runfile(config["image"]),
        _resolve_runfile(config["qemu"]),
        _resolve_runfile(config["system_data"]),
        qemu_args=config["qemu_args"],
        firmware_code=_optional_runfile(config, "firmware_code"),
        firmware_vars=_optional_runfile(config, "firmware_vars"),
        firmware=_optional_runfile(config, "firmware"),
        firmware_kind=config.get("firmware_kind", "ovmf"),
        disk_interface=config.get("disk_interface", "virtio"),
        accelerator_args=config["accelerator_args"],
        kernel_preflight=_resolve_runfile(config["kernel_preflight"]),
        readiness_marker=config["readiness_marker"],
        progress_markers=config.get("progress_markers", ()),
        expected_failure_marker=config.get("expected_failure_marker", ""),
        stop_after_readiness=config.get("stop_after_readiness", False),
        allow_reboot=config.get("allow_reboot", False),
        read_only_shares=[
            (_resolve_runfile_directory(share["directory"]), share["mount_tag"])
            for share in config.get("read_only_shares", ())
        ],
        shutdown_markers=config["shutdown_markers"],
        boot_timeout_seconds=config["boot_timeout_seconds"],
        qmp_initialization_timeout_seconds=config["qmp_initialization_timeout_seconds"],
        shutdown_timeout_seconds=config["shutdown_timeout_seconds"],
        diagnostic_bytes=config["diagnostic_bytes"],
    )


if __name__ == "__main__":
    main()
