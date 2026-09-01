"""Prove a release image retaining apt has no persistent network source."""

import os
import pathlib
import struct
import subprocess
import sys
import uuid

from python.runfiles import runfiles


_ROOT_TYPE_GUID = uuid.UUID("4f68bce3-e8cd-4db1-96e7-fbcaf984b709").bytes_le


def _runfile(path: str) -> pathlib.Path:
    if path.startswith("../"):
        path = path[3:]
    elif not path.startswith("external/"):
        path = os.path.join(os.environ["TEST_WORKSPACE"], path)
    return pathlib.Path(
        runfiles.Create().Rlocation(path)
    )


def _root_partition(image: pathlib.Path, destination: pathlib.Path) -> None:
    with image.open("rb") as source:
        source.seek(512)
        header = source.read(512)
        entries_lba = struct.unpack_from("<Q", header, 72)[0]
        entry_count, entry_size = struct.unpack_from("<II", header, 80)
        source.seek(entries_lba * 512)
        for _ in range(entry_count):
            entry = source.read(entry_size)
            if entry[:16] != _ROOT_TYPE_GUID:
                continue
            first_lba, last_lba = struct.unpack_from("<QQ", entry, 32)
            source.seek(first_lba * 512)
            remaining = (last_lba - first_lba + 1) * 512
            with destination.open("wb") as output:
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise AssertionError("root partition is truncated")
                    output.write(chunk)
                    remaining -= len(chunk)
            return
    raise AssertionError("Linux root partition is missing")


def main() -> None:
    image = _runfile(sys.argv[1])
    launcher = _runfile(sys.argv[2])
    root = pathlib.Path(os.environ["TEST_TMPDIR"]) / "release-root.ext4"
    _root_partition(image, root)
    environment = {
        name: os.environ[name]
        for name in ("RUNFILES_DIR", "RUNFILES_MANIFEST_FILE", "RUNFILES_MANIFEST_ONLY")
        if name in os.environ
    }
    environment.update(
        {
            "MKOSI_DEBIAN_TOOLS_SCRATCH": os.path.join(
                os.environ["TEST_TMPDIR"], "release-apt-sources"
            ),
            "PATH": "",
        }
    )
    result = subprocess.run(
        [
            launcher,
            "--ro-bind",
            "{}:/inputs/release-root.ext4".format(root),
            "/usr/sbin/debugfs",
            "-R",
            "cat /etc/apt/sources.list.d/debian.sources",
            "/inputs/release-root.ext4",
        ],
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )
    assert "File not found" in result.stdout + result.stderr, result.stdout + result.stderr


if __name__ == "__main__":
    main()
