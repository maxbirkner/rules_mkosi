"""Checks that a consumer's arm64 image has the arm64 root partition that systemd-repart chose for its architecture."""

import pathlib
import struct
import sys
import uuid

from python.runfiles import runfiles

_ROOT_ARM64 = uuid.UUID("b921b045-1df0-41c3-af44-4c6f280d3fae").bytes_le


def partitions(image: pathlib.Path) -> list[tuple[bytes, str]]:
    """Returns the type GUID and name of every used GPT entry of image."""
    with image.open("rb") as source:
        source.seek(512)
        header = source.read(512)
        entries_lba = struct.unpack_from("<Q", header, 72)[0]
        count, size = struct.unpack_from("<II", header, 80)
        source.seek(entries_lba * 512)
        entries = [source.read(size) for _ in range(count)]
    return [(entry[:16], entry[56:128].decode("utf-16-le").rstrip("\0")) for entry in entries if any(entry[:16])]


def main() -> None:
    image = pathlib.Path(runfiles.Create().Rlocation(sys.argv[1]))
    found = partitions(image)
    assert (_ROOT_ARM64, "root-arm64") in found, found


if __name__ == "__main__":
    main()
