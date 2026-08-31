import os
import pathlib
import shutil
import subprocess
import sys
import time


MARKER = b"systemd[1]: Hostname set to <rules-mkosi-tracer>."
CLEAN_SHUTDOWN_MARKER = b"systemd-shutdown[1]: Powering off."
POWER_DOWN_MARKER = b"reboot: Power down"
BOOT_TIMEOUT_SECONDS = 180
SHUTDOWN_TIMEOUT_SECONDS = 30


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
    runfiles_root = os.environ.get("RUNFILES_DIR", sys.argv[0] + ".runfiles")
    for candidate in (
        os.path.join(runfiles_root, path),
        os.path.join(runfiles_root, "_main", path),
        os.path.join(runfiles_root, path.removeprefix("external/")),
        os.path.join(runfiles_root, "_main", path.removeprefix("external/")),
    ):
        if os.path.exists(candidate):
            return candidate
    raise RuntimeError("runfile is missing: %s" % path)


def _read_log(path):
    try:
        return pathlib.Path(path).read_bytes()
    except OSError:
        return b"<log unavailable>\n"


def _diagnose(kind, message, serial_log, qemu_log):
    print("%s: %s" % (kind, message), file=sys.stderr)
    print("serial log (%s):" % serial_log, file=sys.stderr)
    print(_read_log(serial_log)[-65536:].decode(errors="replace"), file=sys.stderr)
    print("QEMU log (%s):" % qemu_log, file=sys.stderr)
    print(_read_log(qemu_log)[-65536:].decode(errors="replace"), file=sys.stderr)
    raise SystemExit(1)


def _has_clean_shutdown(serial_log):
    serial = _read_log(serial_log)
    return CLEAN_SHUTDOWN_MARKER in serial and POWER_DOWN_MARKER in serial


def _boot(image, qemu, system_data, ovmf_code, ovmf_vars):
    scratch = pathlib.Path(os.environ.get("TEST_TMPDIR", "boot-test-state"))
    scratch.mkdir(parents=True, exist_ok=True)
    vars_copy = scratch / "OVMF_VARS.fd"
    serial_log = scratch / "guest-serial.log"
    qemu_log = scratch / "qemu.log"
    previous_cwd = os.getcwd()
    os.chdir(scratch)
    try:
        shutil.copyfile(ovmf_vars, vars_copy)
        vars_copy.chmod(0o600)
        command = [
            qemu,
            "-L",
            system_data,
            "-machine",
            "q35",
            "-accel",
            "tcg",
            "-m",
            "512M",
            "-nodefaults",
            "-nographic",
            "-no-reboot",
            "-serial",
            "none",
            "-chardev",
            "file,id=serial0,path=%s" % serial_log,
            "-device",
            "isa-serial,chardev=serial0",
            "-drive",
            "if=pflash,format=raw,readonly=on,file=%s" % ovmf_code,
            "-drive",
            "if=pflash,format=raw,file=%s" % vars_copy,
            "-drive",
            "if=virtio,format=raw,snapshot=on,file=%s" % image,
        ]
        environment = {
            "HOME": str(scratch),
            "LANG": "C.UTF-8",
            "PATH": "",
            "TMPDIR": str(scratch),
        }
        with open(qemu_log, "wb") as output:
            try:
                process = subprocess.Popen(
                    command,
                    cwd=scratch,
                    env=environment,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                )
            except OSError as error:
                _diagnose("QEMU_STARTUP_FAILURE", str(error), serial_log, qemu_log)

            try:
                deadline = time.monotonic() + BOOT_TIMEOUT_SECONDS
                while time.monotonic() < deadline:
                    serial = _read_log(serial_log)
                    if MARKER in serial:
                        break
                    if process.poll() is not None:
                        if b"Linux version" not in serial and b"systemd[" not in serial:
                            _diagnose("FIRMWARE_FAILURE", "guest never reached Linux", serial_log, qemu_log)
                        _diagnose("GUEST_FAILURE", "guest exited before readiness", serial_log, qemu_log)
                    time.sleep(0.1)
                else:
                    _diagnose(
                        "BOOT_TIMEOUT",
                        "did not observe exact serial marker %r" % MARKER.decode(),
                        serial_log,
                        qemu_log,
                    )

                try:
                    process.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    _diagnose(
                        "SHUTDOWN_FAILURE",
                        "guest did not reach systemd Powering off shutdown",
                        serial_log,
                        qemu_log,
                    )
                if process.returncode != 0:
                    _diagnose(
                        "GUEST_FAILURE",
                        "QEMU exited with status %d after readiness" % process.returncode,
                        serial_log,
                        qemu_log,
                    )
                if not _has_clean_shutdown(serial_log):
                    _diagnose(
                        "SHUTDOWN_FAILURE",
                        "guest exited without exact systemd Powering off and kernel power-down markers",
                        serial_log,
                        qemu_log,
                    )
                print("guest readiness marker and clean systemd shutdown verified")
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
    finally:
        os.chdir(previous_cwd)


def main():
    if len(sys.argv) != 6:
        raise SystemExit("usage: boot_test.py IMAGE QEMU QEMU_DATA OVMF_CODE OVMF_VARS")
    _boot(*[_resolve_runfile(argument) for argument in sys.argv[1:]])


if __name__ == "__main__":
    main()
