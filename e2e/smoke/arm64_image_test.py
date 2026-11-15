"""Checks that a consumer's arm64 release image has the arm64 root and verity partitions of its architecture, and a
UKI with the device trees that Devicetrees= selects from the kernel package.
"""

import json
import pathlib
import struct
import sys
import uuid

from python.runfiles import runfiles

_ROOT_ARM64 = "b921b045-1df0-41c3-af44-4c6f280d3fae"
_ROOT_ARM64_VERITY = "df3300ce-d69f-4c92-978c-9bfb0f38d820"


def partitions(image: pathlib.Path) -> list[tuple[str, str]]:
    """Returns the type GUID and name of every used GPT entry of image."""
    with image.open("rb") as source:
        source.seek(512)
        header = source.read(512)
        entries_lba = struct.unpack_from("<Q", header, 72)[0]
        count, size = struct.unpack_from("<II", header, 80)
        source.seek(entries_lba * 512)
        entries = [source.read(size) for _ in range(count)]
    return [
        (str(uuid.UUID(bytes_le=entry[:16])), entry[56:128].decode("utf-16-le").rstrip("\0"))
        for entry in entries
        if any(entry[:16])
    ]


def main() -> None:
    resolver = runfiles.Create()
    image, partition_metadata, uki_metadata = (pathlib.Path(resolver.Rlocation(path)) for path in sys.argv[1:4])
    found = partitions(image)
    assert (_ROOT_ARM64, "root-arm64") in found, found
    assert (_ROOT_ARM64_VERITY, "root-arm64-verity") in found, found
    metadata = json.loads(partition_metadata.read_text())
    assert metadata["architecture"] == "arm64", metadata
    assert {partition["type_guid"] for partition in metadata["partitions"]} >= {_ROOT_ARM64, _ROOT_ARM64_VERITY}
    devicetrees = json.loads(uki_metadata.read_text())["devicetrees"]
    assert [(tree["section"], tree["compatible"][0]) for tree in devicetrees] == [
        (".dtbauto", "arm,corstone1000-fvp"),
        (".dtbauto", "arm,corstone1000-mps3"),
    ], devicetrees


if __name__ == "__main__":
    main()
