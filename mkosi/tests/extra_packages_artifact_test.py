"""Proves that a release image installs its extra packages with dpkg, preferring them to snapshot packages."""

import os
import pathlib
import sys

import rules_mkosi_disk_image as disk_image

from mkosi.tests.runfile_paths import resolve_runfile


def _read(launcher: pathlib.Path, root: pathlib.Path, path: str) -> str:
    return disk_image.read_file(launcher, root, path).decode()


def _installed_versions(status: str) -> dict[str, tuple[str, str]]:
    """Returns the Status and Version of each package in a dpkg status file, keyed by package name."""
    installed = {}
    for paragraph in status.split("\n\n"):
        fields = dict(line.split(": ", 1) for line in paragraph.splitlines() if ": " in line and not line[0].isspace())
        if "Package" in fields:
            installed[fields["Package"]] = (fields.get("Status", ""), fields.get("Version", ""))
    return installed


def main() -> None:
    image = resolve_runfile(sys.argv[1])
    launcher = resolve_runfile(sys.argv[2])
    root = pathlib.Path(os.environ["TEST_TMPDIR"]) / "extra-packages-root.ext4"
    disk_image.extract_root_partition(image, root)

    assert _read(launcher, root, "/usr/share/rules-mkosi-hello/hello.txt") == "hello from an extra package\n"
    # The postinst script of the package ran, as it does only when dpkg installs a package.
    assert _read(launcher, root, "/var/lib/rules-mkosi-hello/configured") == "configured\n"
    assert _read(launcher, root, "/usr/share/rules-mkosi-netbase/replaced") == "netbase replaced by an extra package\n"

    installed = _installed_versions(_read(launcher, root, "/var/lib/dpkg/status"))
    assert installed["rules-mkosi-hello"] == ("install ok installed", "1.0"), installed["rules-mkosi-hello"]
    # The extra netbase replaces the snapshot's netbase 6.5 although its version is lower.
    assert installed["netbase"] == ("install ok installed", "0~rules.mkosi1"), installed["netbase"]

    # The repository and its APT preferences exist only during the build.
    try:
        leftover = _read(launcher, root, "/etc/apt/preferences.d/rules-mkosi-extra-packages.pref")
    except FileNotFoundError:
        return
    raise AssertionError("the APT preferences of the extra packages are left: {!r}".format(leftover))


if __name__ == "__main__":
    main()
