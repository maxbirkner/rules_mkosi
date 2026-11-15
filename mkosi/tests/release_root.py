"""Reads files of the ext4 root partition of a release image with debugfs from the pinned Debian tools."""

import os
import pathlib
import struct
import subprocess
import uuid

_ROOT_TYPE_GUID = uuid.UUID("4f68bce3-e8cd-4db1-96e7-fbcaf984b709").bytes_le


def extract_root_partition(image: pathlib.Path, destination: pathlib.Path) -> None:
    """Copies the x86-64 root partition of the GPT disk image to destination."""
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


def run_debugfs_request(
    launcher: pathlib.Path, root: pathlib.Path, request: str, scratch: str
) -> subprocess.CompletedProcess[str]:
    """Runs one debugfs request on the extracted ext4 root, which the launcher sees as /inputs/<its name>."""
    environment = {
        name: os.environ[name]
        for name in ("RUNFILES_DIR", "RUNFILES_MANIFEST_FILE", "RUNFILES_MANIFEST_ONLY")
        if name in os.environ
    }
    environment.update(
        {
            "MKOSI_DEBIAN_TOOLS_SCRATCH": os.path.join(os.environ["TEST_TMPDIR"], scratch),
            "PATH": "",
        }
    )
    return subprocess.run(
        [
            launcher,
            "--ro-bind",
            "{}:/inputs/{}".format(root, root.name),
            "/usr/sbin/debugfs",
            "-R",
            request,
            "/inputs/{}".format(root.name),
        ],
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )
