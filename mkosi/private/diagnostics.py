"""Actionable failure reporting at the image and virtual-machine boundary."""

import subprocess
import sys


_ACTIONS = {
    "KERNEL_CAPABILITY_FAILURE": "select a Linux runner that satisfies the kernel contract",
    "TOOLCHAIN_FAILURE": "register the required Bazel toolchain",
    "NETWORK_FAILURE": "allow the declared package network access",
    "ASSEMBLY_FAILURE": "inspect the preserved mkosi output",
    "VM_FAILURE": "inspect the preserved serial and QEMU logs",
}


def report(category, detail, original=b""):
    """Print one classified actionable failure while retaining original output."""
    if category not in _ACTIONS:
        raise ValueError("unknown diagnostic category: {}".format(category))
    print("{}: {}".format(category, detail), file=sys.stderr)
    print("Action: {}".format(_ACTIONS[category]), file=sys.stderr)
    if original:
        if isinstance(original, bytes):
            original = original.decode(errors="replace")
        print("Original output:", file=sys.stderr)
        print(original.rstrip(), file=sys.stderr)


def fail(category, detail, original=b"", exit_code=1):
    """Report a failure and terminate with its validated action status."""
    if isinstance(exit_code, bool) or not isinstance(exit_code, int) or exit_code <= 0:
        raise ValueError("diagnostic exit code must be a positive integer")
    report(category, detail, original)
    raise SystemExit(exit_code)


def child_exit_code(returncode):
    """Preserve ordinary child exits and normalize subprocess signal statuses."""
    if isinstance(returncode, bool) or not isinstance(returncode, int) or returncode == 0:
        raise ValueError("child failure status must be a nonzero integer")
    return returncode if returncode > 0 else 128 - returncode


def classify_mkosi_output(output):
    """Classify a failed mkosi child without hiding its original diagnostics."""
    text = output.decode(errors="replace").lower()
    network_signals = (
        "network",
        "connection",
        "download",
        "fetch",
        "temporary failure resolving",
        "name or service not known",
        "timed out",
        "http://",
        "https://",
    )
    toolchain_signals = (
        "not found",
        "not executable",
        "tools tree",
        "debian-tools",
        "systemd-repart",
    )
    if any(signal in text for signal in network_signals):
        return "NETWORK_FAILURE"
    if any(signal in text for signal in toolchain_signals):
        return "TOOLCHAIN_FAILURE"
    return "ASSEMBLY_FAILURE"


def run_kernel_preflight(path, action, runner=subprocess.run):
    """Run the proven kernel probe before an action needs namespace support."""
    try:
        completed = runner(
            [path],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as error:
        fail(
            "TOOLCHAIN_FAILURE",
            "{} cannot start the Bazel-built kernel preflight {}: {}".format(
                action,
                path,
                error,
            ),
        )
    output = completed.stdout + completed.stderr
    if completed.returncode:
        fail(
            "KERNEL_CAPABILITY_FAILURE",
            "{} was rejected before it started (kernel preflight exited {})".format(
                action,
                completed.returncode,
            ),
            output,
        )
    return output
