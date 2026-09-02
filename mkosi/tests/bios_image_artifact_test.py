"""Checks the GRUB BIOS GPT layout in an executed release image."""

import pathlib
import sys

from mkosi.private import partition_metadata


metadata = partition_metadata.project_image(pathlib.Path(sys.argv[1]), "bios")
bios = [
    entry
    for entry in metadata["partitions"]
    if entry["type_guid"] == partition_metadata.BIOS_BOOT
]
assert len(bios) == 1
assert bios[0]["size_bytes"] >= partition_metadata.ALIGNMENT
