"""Proves that an arm64 release image boots through arm64 EFI binaries, has arm64 A/B root slots, and that its UKI
carries the device trees of its devicetrees label and those that Devicetrees= selects from the kernel package.
"""

import hashlib
import json
import os
import pathlib
import struct
import sys

import rules_mkosi_disk_image as disk_image
import rules_mkosi_esp_manifest as esp_manifest

from mkosi.private import gpt_partitions
from mkosi.tests.runfile_paths import resolve_runfile

_MACHINE_ARM64 = 0xAA64
_FDT_MAGIC = b"\xd0\x0d\xfe\xed"


def pe_machine(executable: bytes) -> int:
    """Returns the COFF machine type of a PE executable."""
    header = struct.unpack_from("<I", executable, 0x3C)[0]
    assert executable[:2] == b"MZ" and executable[header : header + 4] == b"PE\0\0", "not a PE executable"
    return int(struct.unpack_from("<H", executable, header + 4)[0])


def pe_sections(executable: bytes) -> list[tuple[str, bytes]]:
    """Returns the name and the virtual-size bytes of each section of a PE executable, in section table order."""
    header = struct.unpack_from("<I", executable, 0x3C)[0]
    count = struct.unpack_from("<H", executable, header + 6)[0]
    table = header + 24 + struct.unpack_from("<H", executable, header + 20)[0]
    sections = []
    for index in range(count):
        name, virtual_size, _, raw_size, raw_offset = struct.unpack_from("<8sIIII", executable, table + 40 * index)
        content = executable[raw_offset : raw_offset + min(virtual_size, raw_size)]
        sections.append((name.rstrip(b"\0").decode("ascii"), content))
    return sections


def check_devicetrees(uki: bytes, uki_metadata: pathlib.Path, virt_label: pathlib.Path) -> None:
    devicetrees = json.loads(uki_metadata.read_text())["devicetrees"]
    # The label's device tree comes first, ahead of the two that Devicetrees=arm/corstone1000-*.dtb selects below
    # /usr/lib/linux-image-<kver>/ in sorted order.
    assert [(tree["section"], tree["compatible"]) for tree in devicetrees] == [
        (".dtbauto", ["linux,dummy-virt", "rules-mkosi,uki-devicetree"]),
        (".dtbauto", ["arm,corstone1000-fvp"]),
        (".dtbauto", ["arm,corstone1000-mps3"]),
    ], devicetrees
    sections = [content for name, content in pe_sections(uki) if name in (".dtb", ".dtbauto")]
    for tree, content in zip(devicetrees, sections, strict=True):
        assert content[:4] == _FDT_MAGIC, content[:4]
        size = struct.unpack_from(">I", content, 4)[0]
        assert tree["size"] == size, (tree, size)
        assert tree["sha256"] == hashlib.sha256(content[:size]).hexdigest(), tree
    assert devicetrees[0]["sha256"] == hashlib.sha256(virt_label.read_bytes()).hexdigest(), devicetrees[0]


def main() -> None:
    image, partition_metadata, uki, payload, uki_metadata, virt_label, launcher = (
        resolve_runfile(path) for path in sys.argv[1:8]
    )

    esp_paths = {file.path for file in esp_manifest.list_esp_files(image)}
    for path in ("EFI/BOOT/BOOTAA64.EFI", "EFI/systemd/systemd-bootaa64.efi", "EFI/Linux/rules-mkosi-arm64_1.efi"):
        assert path in esp_paths, sorted(esp_paths)
        assert pe_machine(esp_manifest.read_esp_file(image, path)) == _MACHINE_ARM64, path
    assert pe_machine(uki.read_bytes()) == _MACHINE_ARM64
    check_devicetrees(uki.read_bytes(), uki_metadata, virt_label)

    metadata = json.loads(partition_metadata.read_text())
    assert metadata["architecture"] == "arm64", metadata
    slots = [(partition["label"], partition["type_guid"]) for partition in metadata["partitions"][1:]]
    assert slots == [
        ("rules-mkosi-arm64_1", gpt_partitions.ROOT_ARM64),
        ("rules-mkosi-arm64_1_verity", gpt_partitions.ROOT_ARM64_VERITY),
        (gpt_partitions.EMPTY_SLOT_LABEL, gpt_partitions.ROOT_ARM64),
        (gpt_partitions.EMPTY_SLOT_LABEL, gpt_partitions.ROOT_ARM64_VERITY),
    ], slots
    # Partition types and labels do not show whether the root partition holds the image's tree.
    root = pathlib.Path(os.environ["TEST_TMPDIR"]) / "root.erofs"
    disk_image.extract_root_partition(image, root, "arm64")
    disk_image.require_populated_root(launcher, root)

    files = sorted(path.name for path in pathlib.Path(payload).iterdir())
    assert len(files) == 4 and "SHA256SUMS" in files and "rules-mkosi-arm64_1.efi" in files, files


if __name__ == "__main__":
    main()
