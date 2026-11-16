"""Actionable failure reporting at the image and virtual-machine boundary."""

import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from typing import NoReturn

_ACTIONS = {
    "KERNEL_CAPABILITY_FAILURE": "select a Linux runner that satisfies the kernel contract",
    "TOOLCHAIN_FAILURE": "register the required Bazel toolchain",
    "NETWORK_FAILURE": "allow the declared package network access",
    "PACKAGE_RESOLUTION_FAILURE": (
        "add the missing package or dependency to the Debian snapshot lock or to extra_packages"
    ),
    "EXTRA_PACKAGE_FAILURE": (
        "pass extra_packages only Debian binary packages with unique names for the snapshot's architecture or all"
    ),
    "ASSEMBLY_FAILURE": "inspect the preserved mkosi output",
    "IMAGE_LAYOUT_FAILURE": "enlarge the partition in the image's mkosi.repart definitions",
    "VM_FAILURE": "inspect the preserved serial, firmware, and QEMU logs",
}
_MIN_EXIT_STATUS = 1
_MAX_EXIT_STATUS = 255


def report(category: str, detail: str, original: bytes | str = b"") -> None:
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


def fail(category: str, detail: str, original: bytes | str = b"", exit_code: int = 1) -> NoReturn:
    """Report a failure and terminate with its validated action status."""
    if (
        isinstance(exit_code, bool)
        or not isinstance(exit_code, int)
        or not _MIN_EXIT_STATUS <= exit_code <= _MAX_EXIT_STATUS
    ):
        raise ValueError("diagnostic exit code must be an integer from 1 through 255")
    report(category, detail, original)
    raise SystemExit(exit_code)


def child_exit_code(returncode: int) -> int:
    """Return a nonzero one-byte status for a failed subprocess.

    subprocess uses negative return codes for signals. Preserve conventional
    128 + signal statuses through signal 127; statuses outside the one-byte
    process range use 1 rather than risking an OS-level success after truncation.
    """
    if isinstance(returncode, bool) or not isinstance(returncode, int) or returncode == 0:
        raise ValueError("child failure status must be a nonzero integer")
    if _MIN_EXIT_STATUS <= returncode <= _MAX_EXIT_STATUS:
        return returncode
    if returncode < 0 and -returncode <= _MAX_EXIT_STATUS - 128:
        return 128 - returncode
    return 1


def classify_mkosi_output(output: bytes) -> str:
    """Classify a failed mkosi child without hiding its original diagnostics."""
    text = output.decode(errors="replace").lower()
    # APT reports a package or dependency that neither the snapshot mirror nor extra_packages provide as unmet, and
    # one that the snapshot's Packages index lists but its lock does not as a missing file of the local mirror. Both
    # outputs also contain network signals, such as "fetch", so they are checked first.
    package_signals = (
        "unmet dependencies",
        "is not installable",
        "has no installation candidate",
        "unable to locate package",
        "failed to fetch file:/repository/",
    )
    if any(signal in text for signal in package_signals):
        return "PACKAGE_RESOLUTION_FAILURE"
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


_UNMET_DEPENDENCIES = "the following packages have unmet dependencies:"
# Errors that name a package which neither the snapshot mirror nor extra_packages provide.
_APT_PACKAGE_ERRORS = ("unable to locate package", "has no installation candidate", "failed to fetch file:/repository/")
# A line of APT's unmet dependencies that starts with a relation field, optionally after the name of the package that
# has it, such as "vendor-kernel : Depends: kmod but it is not installable".
_UNMET_RELATION = re.compile(r"(?:(?P<package>\S+) : )?(?P<relation>[A-Za-z-]+: .*)")


def extract_apt_explanation(output: bytes) -> list[str]:
    """Returns APT's explanation of why it cannot install the packages of a failed mkosi child, in output order.

    That is each unmet dependency, with the package that has it, and each error about a package that the repositories
    lack, but not the generic errors that follow them. The list is empty if output has no such explanation.
    """
    explanation: list[str] = []
    unmet: list[str] | None = None
    for line in output.decode(errors="replace").splitlines():
        if unmet is not None and line[:1].isspace() and line.strip():
            _add_unmet_dependency(unmet, line.strip())
            continue
        explanation.extend(unmet or ())
        unmet = [] if line.strip().lower() == _UNMET_DEPENDENCIES else None
        if line.startswith("E: ") and any(error in line.lower() for error in _APT_PACKAGE_ERRORS):
            explanation.append(line.strip())
    explanation.extend(unmet or ())
    return list(dict.fromkeys(explanation))


def _add_unmet_dependency(unmet: list[str], line: str) -> None:
    """Adds an indented line of APT's unmet dependencies to the entries in unmet.

    A line without a relation field continues the previous entry with an alternative, and a relation without a package
    belongs to the package of the previous entry.
    """
    match = _UNMET_RELATION.fullmatch(line)
    if match is None and unmet:
        unmet[-1] += " " + line
    elif match is not None and (match["package"] or unmet):
        package = match["package"] or unmet[-1].partition(" : ")[0]
        unmet.append("{} : {}".format(package, match["relation"]))
    else:
        unmet.append(line)


def run_kernel_preflight(
    path: str | os.PathLike[str],
    action: str,
    runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
    arguments: Sequence[str] = (),
) -> bytes:
    """Run the proven kernel probe, with its arguments, before an action needs namespace support."""
    try:
        completed = runner(
            [path, *arguments],
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
