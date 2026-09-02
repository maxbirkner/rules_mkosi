"""Structured negative fixtures for the BIOS artifact validator."""

import importlib.util
import pathlib
import struct
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("validator", pathlib.Path(__file__).with_name("bios_image_artifact_test.py"))
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


class BiosArtifactTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.image = pathlib.Path(self.directory.name) / "image.raw"
        self.metadata = {"partitions": [{"type_guid": validator.partition_metadata.BIOS_BOOT, "start_bytes": 1048576, "size_bytes": 1048576}]}
        self.boot = bytearray((i * 37 + 11) & 255 for i in range(512))
        self.boot[510:512] = b"\x55\xaa"
        self.diskboot = bytearray((i * 29 + 7) & 255 for i in range(512))
        self.raw = bytearray(2 * 1048576)
        self.raw[:512] = self.boot
        self.raw[1048576:1049088] = self.diskboot
        struct.pack_into("<QHH", self.raw, 1048576 + validator.BLOCKLIST_OFFSET, 2049, 2, 0x800)
        struct.pack_into("<QHH", self.raw, 1048576 + validator.BLOCKLIST_OFFSET + 12, 0, 0, 0)
        self.raw[2049 * 512:2051 * 512] = bytes((i * 17 + 3) & 255 for i in range(1024))
        self.decompressor = bytes(self.raw[2049 * 512:2051 * 512])
        self.image.write_bytes(self.raw)

    def tearDown(self):
        self.directory.cleanup()

    def check(self, pattern):
        with self.assertRaisesRegex(AssertionError, pattern):
            validator.validate_boot_regions(self.image, self.metadata, bytes(self.boot), bytes(self.diskboot), self.decompressor)

    def test_mbr_signature(self):
        self.raw[510] ^= 1; self.image.write_bytes(self.raw); self.check("MBR signature")

    def test_random_bootstrap(self):
        self.raw[0x70] ^= 1; self.image.write_bytes(self.raw); self.check("MBR invariant")

    def test_invariant_patch_corruption(self):
        self.raw[1048576 + 20] ^= 1; self.image.write_bytes(self.raw); self.check("diskboot invariant")

    def test_out_of_bounds_blocklist(self):
        struct.pack_into("<Q", self.raw, 1048576 + validator.BLOCKLIST_OFFSET, 4096)
        self.image.write_bytes(self.raw); self.check("leaves BIOS")

    def test_deeper_core_corruption(self):
        self.raw[2049 * 512 + 40] ^= 1
        self.image.write_bytes(self.raw); self.check("decompressor invariant")

    def files(self):
        version = "6.12.0"
        return ({"/boot/vmlinuz-" + version: "regular", "/boot/initrd.img-" + version: "regular"},
                {name: "regular" for name in validator.REQUIRED_MODULES},
                """menuentry 'Debian' {
 insmod part_gpt
 linux /boot/vmlinuz-6.12.0 root=/dev/sda2
 initrd /boot/initrd.img-6.12.0
}
""")

    def test_valid_fixture(self):
        validator.validate_boot_regions(self.image, self.metadata, bytes(self.boot), bytes(self.diskboot), self.decompressor)
        validator.validate_boot_files(*self.files())

    def test_kernel_initrd_mismatch(self):
        e, m, c = self.files(); c = c.replace("initrd.img-6.12.0", "initrd.img-6.11.0")
        with self.assertRaisesRegex(AssertionError, "versions do not match"): validator.validate_boot_files(e, m, c)

    def test_missing_reference(self):
        e, m, c = self.files(); del e["/boot/vmlinuz-6.12.0"]
        with self.assertRaisesRegex(AssertionError, "missing non-regular"): validator.validate_boot_files(e, m, c)

    def test_malformed_comment_only_menuentry(self):
        e, m, _ = self.files()
        with self.assertRaisesRegex(AssertionError, "genuine menuentry"): validator.validate_boot_files(e, m, "# menuentry linux initrd")

    def test_each_required_module(self):
        for name in validator.REQUIRED_MODULES:
            e, m, c = self.files(); del m[name]
            with self.subTest(name=name), self.assertRaisesRegex(AssertionError, "module is missing: " + name):
                validator.validate_boot_files(e, m, c)


if __name__ == "__main__":
    unittest.main()
