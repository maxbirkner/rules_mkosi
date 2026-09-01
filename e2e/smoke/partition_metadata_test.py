"""Validate the public release-image GPT projection as a consumer."""

import json
import pathlib
import sys

ROOT_X86_64 = "4f68bce3-e8cd-4db1-96e7-fbcaf984b709"

metadata = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
assert metadata["format_version"] == "mkosi-partition-metadata-v1"
assert metadata["sector_size"] > 0
assert metadata["partitions"] == sorted(
    metadata["partitions"], key=lambda partition: partition["number"]
)
roots = [
    partition
    for partition in metadata["partitions"]
    if partition["type_guid"] == ROOT_X86_64
]
assert len(roots) == 1
assert roots[0]["label"] == "root-x86-64"
assert all(
    partition["start_bytes"] % (1024 * 1024) == 0
    for partition in metadata["partitions"]
)
