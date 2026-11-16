"""Proves that the device trees of mkosi_image(devicetrees = ...) are in the UKI and nowhere else in the image.

The image has no dm-verity partitions, so mkosi does not need the root hash before it builds the UKI.
"""

import hashlib
import json
import os
import pathlib
import sys

import rules_mkosi_disk_image as disk_image
import rules_mkosi_esp_manifest as esp_manifest

from mkosi.tests.runfile_paths import resolve_runfile

_CHUNK = 1024 * 1024


def partition_contains(partition: pathlib.Path, needles: list[bytes]) -> set[bytes]:
    """Returns the needles that occur anywhere in the bytes of partition."""
    found: set[bytes] = set()
    overlap = max(len(needle) for needle in needles) - 1
    tail = b""
    with partition.open("rb") as source:
        while chunk := source.read(_CHUNK):
            window = tail + chunk
            found.update(needle for needle in needles if needle in window)
            tail = window[-overlap:]
    return found


def main() -> None:
    image, uki_metadata = (resolve_runfile(path) for path in sys.argv[1:3])
    labels = [resolve_runfile(path) for path in sys.argv[3:]]

    devicetrees = json.loads(uki_metadata.read_text())["devicetrees"]
    expected = [(".dtbauto", hashlib.sha256(label.read_bytes()).hexdigest()) for label in labels]
    assert [(tree["section"], tree["sha256"]) for tree in devicetrees] == expected, devicetrees

    esp_paths = [file.path for file in esp_manifest.list_esp_files(image)]
    assert not [path for path in esp_paths if path.endswith(".dtb")], esp_paths

    root = pathlib.Path(os.environ["TEST_TMPDIR"]) / "devicetrees-root.raw"
    disk_image.extract_root_partition(image, root)
    # os-release proves that the search reads the root file system's names and contents.
    needles = [b"os-release", *(label.name.encode() for label in labels), *(label.read_bytes() for label in labels)]
    assert partition_contains(root, needles) == {b"os-release"}, partition_contains(root, needles)


if __name__ == "__main__":
    main()
