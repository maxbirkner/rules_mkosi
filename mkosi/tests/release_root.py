"""Reads files of the ext4 root partition of a release image with debugfs from the pinned Debian tools."""

import os
import pathlib
import struct
import subprocess
import uuid

# GPT partition type of the root partition of each architecture, from the UAPI Discoverable Partitions Specification.
ROOT_TYPES = {
    "x86-64": "4f68bce3-e8cd-4db1-96e7-fbcaf984b709",
    "arm64": "b921b045-1df0-41c3-af44-4c6f280d3fae",
}


def extract_root_partition(image: pathlib.Path, destination: pathlib.Path, architecture: str = "x86-64") -> None:
    """Copies the root partition of the architecture, as mkosi names it, of the GPT disk image to destination."""
    root_type = uuid.UUID(ROOT_TYPES[architecture]).bytes_le
    with image.open("rb") as source:
        source.seek(512)
        header = source.read(512)
        entries_lba = struct.unpack_from("<Q", header, 72)[0]
        entry_count, entry_size = struct.unpack_from("<II", header, 80)
        source.seek(entries_lba * 512)
        for _ in range(entry_count):
            entry = source.read(entry_size)
            if entry[:16] != root_type:
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
    raise AssertionError("Linux {} root partition is missing".format(architecture))


def _debugfs_environment(scratch: str) -> dict[str, str]:
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
    return environment


def _debugfs_command(launcher: pathlib.Path, root: pathlib.Path, request: str) -> list[str | os.PathLike[str]]:
    return [
        launcher,
        "--ro-bind",
        "{}:/inputs/{}".format(root, root.name),
        "/usr/sbin/debugfs",
        "-R",
        request,
        "/inputs/{}".format(root.name),
    ]


def run_debugfs_request(
    launcher: pathlib.Path, root: pathlib.Path, request: str, scratch: str
) -> subprocess.CompletedProcess[str]:
    """Runs one debugfs request on the extracted ext4 root, which the launcher sees as /inputs/<its name>."""
    return subprocess.run(
        _debugfs_command(launcher, root, request),
        env=_debugfs_environment(scratch),
        capture_output=True,
        check=False,
        text=True,
    )


def read_root_file(launcher: pathlib.Path, root: pathlib.Path, path: str, scratch: str) -> bytes:
    """Returns the bytes of a regular file of the extracted ext4 root."""
    result = subprocess.run(
        _debugfs_command(launcher, root, "cat " + path),
        env=_debugfs_environment(scratch),
        capture_output=True,
        check=False,
    )
    if result.returncode or b"File not found" in result.stderr:
        raise AssertionError("cannot read {}: {!r}".format(path, result.stderr))
    return result.stdout
