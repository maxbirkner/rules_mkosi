"""Tests reading device tree blobs and recording the device tree sections of a UKI."""

import hashlib
import unittest

from mkosi.private import devicetree, uki_metadata
from mkosi.tests.devicetree_fixture import encode_device_tree


class DeviceTreeTest(unittest.TestCase):
    def test_reads_the_root_compatible_strings_and_size(self) -> None:
        blob = encode_device_tree(["vendor,board-b", "vendor,board"], {"model": b"Board B\0"})
        self.assertEqual(
            devicetree.DeviceTree(size=len(blob), compatible=("vendor,board-b", "vendor,board")),
            devicetree.parse_device_tree(blob + bytes(512)),
        )

    def test_root_without_compatible_has_no_compatible_strings(self) -> None:
        self.assertEqual((), devicetree.parse_device_tree(encode_device_tree([])).compatible)

    def test_rejects_blobs_that_are_not_device_trees(self) -> None:
        blob = encode_device_tree(["vendor,board"])
        cases = {
            "magic 0x4d5a9000 instead of 0xd00dfeed": b"MZ\x90\0" + blob[4:],
            "truncated": blob[:-1],
            "shorter than its header": blob[:39],
            "compatible property is not a list of strings": encode_device_tree([], {"compatible": b"vendor"}),
        }
        for message, case in cases.items():
            with self.subTest(message=message), self.assertRaisesRegex(devicetree.DeviceTreeError, message):
                devicetree.parse_device_tree(case)


class DeviceTreeSectionTest(unittest.TestCase):
    def test_records_the_device_tree_without_section_padding(self) -> None:
        blob = encode_device_tree(["vendor,board"])
        description = uki_metadata.describe_devicetree_section(".dtbauto", blob + bytes(64))
        self.assertEqual(
            {
                "compatible": ["vendor,board"],
                "section": ".dtbauto",
                "sha256": hashlib.sha256(blob).hexdigest(),
                "size": len(blob),
            },
            description,
        )

    def test_rejects_a_dtbauto_section_that_systemd_stub_cannot_select(self) -> None:
        blob = encode_device_tree([])
        self.assertEqual([], uki_metadata.describe_devicetree_section(".dtb", blob)["compatible"])
        with self.assertRaisesRegex(ValueError, "UKI .dtbauto section has no root compatible string"):
            uki_metadata.describe_devicetree_section(".dtbauto", blob)

    def test_rejects_a_section_that_is_not_a_device_tree(self) -> None:
        with self.assertRaisesRegex(ValueError, r"UKI \.dtb section: not a flattened device tree"):
            uki_metadata.describe_devicetree_section(".dtb", b"not a device tree, but long enough for its header")


if __name__ == "__main__":
    unittest.main()
