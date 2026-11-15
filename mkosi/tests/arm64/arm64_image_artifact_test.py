"""Proves that an arm64 image was assembled from arm64 packages whose maintainer scripts ran."""

import os
import pathlib
import sys

from mkosi.tests.release_root import extract_root_partition, read_root_file
from mkosi.tests.runfile_paths import resolve_runfile

_ELF_MACHINE_AARCH64 = 183


def _packages(status: str) -> dict[str, dict[str, str]]:
    """Returns the fields of each package in a dpkg status file, keyed by package name."""
    packages = {}
    for paragraph in status.split("\n\n"):
        fields = dict(line.split(": ", 1) for line in paragraph.splitlines() if ": " in line and not line[0].isspace())
        if "Package" in fields:
            packages[fields["Package"]] = fields
    return packages


def main() -> None:
    image = resolve_runfile(sys.argv[1])
    launcher = resolve_runfile(sys.argv[2])
    root = pathlib.Path(os.environ["TEST_TMPDIR"]) / "arm64-root.ext4"
    # The root partition has the arm64 root type, which systemd-repart chose for the image's architecture.
    extract_root_partition(image, root, "arm64")

    dpkg = read_root_file(launcher, root, "/usr/bin/dpkg", "arm64-dpkg")
    assert dpkg[:4] == b"\x7fELF", dpkg[:4]
    assert int.from_bytes(dpkg[18:20], "little") == _ELF_MACHINE_AARCH64, dpkg[18:20]

    packages = _packages(read_root_file(launcher, root, "/var/lib/dpkg/status", "arm64-status").decode())
    assert "apt" in packages, sorted(packages)
    not_configured = {
        name: fields.get("Status")
        for name, fields in packages.items()
        if fields.get("Status") != "install ok installed"
    }
    # dpkg configures a package only after its postinst script succeeded, which ran arm64 programs.
    assert not not_configured, not_configured
    architectures = {fields.get("Architecture") for fields in packages.values()}
    assert architectures == {"arm64", "all"}, architectures
    # base-passwd's maintainer script, an arm64 program, created the user database.
    passwd = read_root_file(launcher, root, "/etc/passwd", "arm64-passwd")
    assert passwd.startswith(b"root:*:0:0:"), passwd


if __name__ == "__main__":
    main()
