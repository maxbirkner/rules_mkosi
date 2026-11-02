"""Proves a consumer-owned snapshot installed a package from a non-main component."""

import hashlib
import itertools
import json
import os
import pathlib
import subprocess
import sys

_PACKAGE = "amd64-microcode"
_COMPONENT = "non-free-firmware"
_REQUESTS = itertools.count()


def debugfs(launcher, directory, request):
    environment = dict(os.environ)
    environment["MKOSI_DEBIAN_TOOLS_SCRATCH"] = str(
        directory / "launcher-{}".format(next(_REQUESTS))
    )
    result = subprocess.run(
        [
            launcher,
            "--ro-bind",
            "{}:/inputs/consumer-snapshot".format(directory),
            "/usr/sbin/debugfs",
            "-R",
            request,
            "/inputs/consumer-snapshot/rootfs.ext4",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=environment,
    )
    if result.returncode:
        raise AssertionError(
            "debugfs request {!r} failed with {}: {}".format(request, result.returncode, result.stdout)
        )
    return result.stdout


def extract_root(image_path, partition_metadata, destination):
    roots = [
        partition
        for partition in partition_metadata["partitions"]
        if partition["label"] == "root-x86-64"
    ]
    if len(roots) != 1:
        raise AssertionError("expected one root-x86-64 partition")
    with open(image_path, "rb") as image, destination.open("wb") as output:
        image.seek(roots[0]["start_bytes"])
        remaining = roots[0]["size_bytes"]
        while remaining:
            chunk = image.read(min(remaining, 1024 * 1024))
            if not chunk:
                raise AssertionError("root partition is truncated")
            output.write(chunk)
            remaining -= len(chunk)


def installed_version(status, package):
    for stanza in status.split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in stanza.splitlines() if ": " in line and not line.startswith(" ")
        )
        if fields.get("Package") == package:
            if fields.get("Status") != "install ok installed":
                raise AssertionError("{} is not installed: {!r}".format(package, fields.get("Status")))
            return fields.get("Version")
    raise AssertionError("{} is absent from the dpkg database".format(package))


def main():
    image_path, partition_metadata_path, build_metadata_path, launcher, lock_path = sys.argv[1:]
    lock_bytes = pathlib.Path(lock_path).read_bytes()
    lock = json.loads(lock_bytes)
    components = lock["repository"]["components"]
    if components != ["main", _COMPONENT]:
        raise AssertionError("unexpected locked components: {}".format(components))
    locked = [package for package in lock["packages"] if package["name"] == _PACKAGE]
    if len(locked) != 1:
        raise AssertionError("{} must be locked exactly once".format(_PACKAGE))
    locked = locked[0]
    if locked["component"] != _COMPONENT or not locked["filename"].startswith(
        "pool/{}/".format(_COMPONENT)
    ):
        raise AssertionError("{} is not locked from {}: {}".format(_PACKAGE, _COMPONENT, locked))

    build_metadata = json.loads(pathlib.Path(build_metadata_path).read_text())
    snapshot = build_metadata["debian_snapshot"]
    if snapshot["components"] != components:
        raise AssertionError("image metadata components differ: {}".format(snapshot))
    if snapshot["lock_sha256"] != hashlib.sha256(lock_bytes).hexdigest():
        raise AssertionError("image metadata does not record the consumer lock digest")

    directory = pathlib.Path(os.environ["TEST_TMPDIR"])
    extract_root(
        image_path,
        json.loads(pathlib.Path(partition_metadata_path).read_text()),
        directory / "rootfs.ext4",
    )
    status = debugfs(launcher, directory, "cat /var/lib/dpkg/status")
    version = installed_version(status, _PACKAGE)
    if version != locked["version"]:
        raise AssertionError("installed {} {} differs from lock {}".format(_PACKAGE, version, locked["version"]))
    files = debugfs(launcher, directory, "cat /var/lib/dpkg/info/{}.list".format(_PACKAGE))
    firmware = sorted(line for line in files.splitlines() if line.endswith(".bin"))
    if not firmware:
        raise AssertionError("{} installed no microcode files: {}".format(_PACKAGE, files))
    # dpkg records the package's /lib paths; the merged-/usr image stores them below /usr.
    path = "/usr" + firmware[0] if firmware[0].startswith("/lib/") else firmware[0]
    details = debugfs(launcher, directory, "stat {}".format(path))
    if "Type: regular" not in details:
        raise AssertionError("{} is not a regular file: {}".format(path, details))


if __name__ == "__main__":
    main()
