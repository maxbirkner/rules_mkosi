"""Proves a consumer-owned snapshot installed a package from a non-main component."""

import hashlib
import json
import os
import pathlib
import sys

import rules_mkosi_disk_image as disk_image

_PACKAGE = "amd64-microcode"
_COMPONENT = "non-free-firmware"


def installed_version(status: str, package: str) -> str | None:
    for stanza in status.split("\n\n"):
        fields = dict(line.split(": ", 1) for line in stanza.splitlines() if ": " in line and not line.startswith(" "))
        if fields.get("Package") == package:
            if fields.get("Status") != "install ok installed":
                raise AssertionError("{} is not installed: {!r}".format(package, fields.get("Status")))
            return fields.get("Version")
    raise AssertionError("{} is absent from the dpkg database".format(package))


def main() -> None:
    image_path, build_metadata_path, launcher, lock_path = sys.argv[1:]
    lock_bytes = pathlib.Path(lock_path).read_bytes()
    lock = json.loads(lock_bytes)
    components = lock["repository"]["components"]
    if components != ["main", _COMPONENT]:
        raise AssertionError("unexpected locked components: {}".format(components))
    locked = [package for package in lock["packages"] if package["name"] == _PACKAGE]
    if len(locked) != 1:
        raise AssertionError("{} must be locked exactly once".format(_PACKAGE))
    locked = locked[0]
    if locked["component"] != _COMPONENT or not locked["filename"].startswith("pool/{}/".format(_COMPONENT)):
        raise AssertionError("{} is not locked from {}: {}".format(_PACKAGE, _COMPONENT, locked))

    build_metadata = json.loads(pathlib.Path(build_metadata_path).read_text())
    snapshot = build_metadata["debian_snapshot"]
    if snapshot["components"] != components:
        raise AssertionError("image metadata components differ: {}".format(snapshot))
    if snapshot["lock_sha256"] != hashlib.sha256(lock_bytes).hexdigest():
        raise AssertionError("image metadata does not record the consumer lock digest")

    filesystem = pathlib.Path(os.environ["TEST_TMPDIR"]) / "rootfs.ext4"
    disk_image.extract_root_partition(image_path, filesystem)
    status = disk_image.read_file(launcher, filesystem, "/var/lib/dpkg/status").decode()
    version = installed_version(status, _PACKAGE)
    if version != locked["version"]:
        raise AssertionError("installed {} {} differs from lock {}".format(_PACKAGE, version, locked["version"]))
    files = disk_image.read_file(launcher, filesystem, "/var/lib/dpkg/info/{}.list".format(_PACKAGE)).decode()
    firmware = sorted(line for line in files.splitlines() if line.endswith(".bin"))
    if not firmware:
        raise AssertionError("{} installed no microcode files: {}".format(_PACKAGE, files))
    # dpkg records the package's /lib paths; the merged-/usr image stores them below /usr.
    path = "/usr" + firmware[0] if firmware[0].startswith("/lib/") else firmware[0]
    details = disk_image.run_debugfs(launcher, filesystem, "stat " + path)
    if "Type: regular" not in details:
        raise AssertionError("{} is not a regular file: {}".format(path, details))


if __name__ == "__main__":
    main()
