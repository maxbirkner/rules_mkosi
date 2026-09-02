"""Negative tests for rules_mkosi BIOS artifact diagnostics."""

import pathlib
import tempfile
import unittest
import importlib.util

spec = importlib.util.spec_from_file_location("validator", pathlib.Path(__file__).with_name("bios_image_artifact_test.py"))
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


class BiosArtifactTest(unittest.TestCase):
    def test_corrupt_mbr_and_core_have_distinct_diagnostics(self):
        metadata = {"partitions": [{"type_guid": "21686148-6449-6e6f-744e-656564454649", "start_bytes": 1048576, "size_bytes": 1048576}]}
        with tempfile.TemporaryDirectory() as directory:
            image = pathlib.Path(directory) / "image.raw"
            raw = bytearray(2 * 1048576)
            raw[510:512] = b"\x55\xaa"
            image.write_bytes(raw)
            with self.assertRaisesRegex(AssertionError, "MBR bootstrap"):
                validator.validate_boot_regions(image, metadata)
            raw[:440] = bytes(range(256)) + bytes(range(184))
            image.write_bytes(raw)
            with self.assertRaisesRegex(AssertionError, "core image diskboot"):
                validator.validate_boot_regions(image, metadata)

    def test_missing_boot_payloads_have_distinct_diagnostics(self):
        with self.assertRaisesRegex(AssertionError, "kernel or matching initrd"):
            validator.validate_boot_files("", "/normal.mod\n/linux.mod", "menuentry linux initrd")
        with self.assertRaisesRegex(AssertionError, "i386-pc modules"):
            validator.validate_boot_files("/vmlinuz-x\n/initrd.img-x", "", "menuentry linux initrd")
        with self.assertRaisesRegex(AssertionError, "viable kernel menu"):
            validator.validate_boot_files("/vmlinuz-x\n/initrd.img-x", "/normal.mod\n/linux.mod", "")


if __name__ == "__main__":
    unittest.main()
