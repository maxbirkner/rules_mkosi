"""Checks that a consumer's arm64 release image has the arm64 root and verity partitions of its architecture, a root
file system with the image's tree, and a UKI with the device tree of its devicetrees label and those that Devicetrees=
selects from the kernel package.
"""

import json
import os
import pathlib
import sys

import rules_mkosi_disk_image as disk_image
from python.runfiles import runfiles


def main() -> None:
    resolver = runfiles.Create()
    image, partition_metadata, uki_metadata, launcher = (
        pathlib.Path(resolver.Rlocation(path)) for path in sys.argv[1:5]
    )
    types = disk_image.gpt_partitions.root_types("arm64")
    found = [(partition.type_guid, partition.label) for partition in disk_image.list_partitions(image)]
    assert (types.root, types.name) in found, found
    assert (types.verity, types.name + "-verity") in found, found
    root = pathlib.Path(os.environ["TEST_TMPDIR"]) / "root.ext4"
    disk_image.extract_root_partition(image, root, "arm64")
    disk_image.require_populated_root(launcher, root)
    metadata = json.loads(partition_metadata.read_text())
    assert metadata["architecture"] == "arm64", metadata
    assert {partition["type_guid"] for partition in metadata["partitions"]} >= {types.root, types.verity}
    devicetrees = json.loads(uki_metadata.read_text())["devicetrees"]
    assert [(tree["section"], tree["compatible"][0]) for tree in devicetrees] == [
        (".dtbauto", "consumer,board"),
        (".dtbauto", "arm,corstone1000-fvp"),
        (".dtbauto", "arm,corstone1000-mps3"),
    ], devicetrees


if __name__ == "__main__":
    main()
