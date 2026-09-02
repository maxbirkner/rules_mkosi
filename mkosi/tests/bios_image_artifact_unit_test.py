"""Focused negative fixtures for GRUB BIOS installation evidence."""

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
        self.boot = bytearray((index * 37 + 11) & 255 for index in range(512))
        self.boot[0x1BE:0x1FE] = bytes(64)
        self.boot[510:512] = b"\x55\xaa"
        struct.pack_into("<B3sB3sII", self.boot, 0x1BE, 0, b"\0\2\0", 0xEE, b"\xff\xff\xff", 1, 4095)
        self.diskboot = bytearray((index * 29 + 7) & 255 for index in range(512))
        self.raw = bytearray(2 * 1048576)
        self.raw[:512] = self.boot
        self.raw[1048576:1049088] = self.diskboot
        self.raw[1049088] = 1
        self.image.write_bytes(self.raw)

    def tearDown(self):
        self.directory.cleanup()

    def check(self, pattern):
        with self.assertRaisesRegex(AssertionError, pattern):
            validator.validate_boot_regions(
                self.image, self.metadata, bytes(self.boot), bytes(self.diskboot)
            )

    def test_valid_installation_evidence(self):
        validator.validate_boot_regions(
            self.image, self.metadata, bytes(self.boot), bytes(self.diskboot)
        )

    def test_mbr_signature(self):
        self.raw[510] ^= 1
        self.image.write_bytes(self.raw)
        self.check("MBR signature")

    def test_non_grub_bootstrap(self):
        self.raw[0x70] ^= 1
        self.image.write_bytes(self.raw)
        self.check("installation MBR invariant")

    def test_missing_protective_mbr(self):
        self.raw[0x1BE:0x1CE] = bytes(16)
        self.image.write_bytes(self.raw)
        self.check("exactly one protective")

    def test_wrong_protective_type(self):
        self.raw[0x1BE + 4] = 0x83
        self.image.write_bytes(self.raw)
        self.check("exactly one protective")

    def test_wrong_protective_start(self):
        struct.pack_into("<I", self.raw, 0x1BE + 8, 2)
        self.image.write_bytes(self.raw)
        self.check("start at LBA 1")

    def test_undersized_protective_coverage(self):
        struct.pack_into("<I", self.raw, 0x1BE + 12, 4094)
        self.image.write_bytes(self.raw)
        self.check("cover the disk")

    def test_active_protective_entry(self):
        self.raw[0x1BE] = 0x80
        self.image.write_bytes(self.raw)
        self.check("must not be active")

    def test_hybrid_mbr_entry(self):
        struct.pack_into("<B3sB3sII", self.raw, 0x1CE, 0x80, bytes(3), 0x83, bytes(3), 2, 4)
        self.image.write_bytes(self.raw)
        self.check("hybrid MBR")

    def test_diskboot_invariant(self):
        self.raw[1048576 + 20] ^= 1
        self.image.write_bytes(self.raw)
        self.check("installation diskboot invariant")

    def test_empty_bios_payload(self):
        self.raw[1049088:2097152] = bytes(2097152 - 1049088)
        self.image.write_bytes(self.raw)
        self.check("installation payload.*empty")

    def files(self):
        entries = {
            "/boot/vmlinuz-6.12.0": "regular",
            "/boot/initrd.img-6.12.0": "regular",
        }
        modules = {name: "regular" for name in validator.REQUIRED_MODULES}
        config = """menuentry 'Debian' {
 insmod part_gpt
 linux /boot/vmlinuz-6.12.0 root=/dev/sda2
 initrd /boot/initrd.img-6.12.0
}
"""
        return entries, modules, config

    def test_valid_boot_files(self):
        validator.validate_boot_files(*self.files())

    def test_kernel_initrd_mismatch(self):
        entries, modules, config = self.files()
        config = config.replace("initrd.img-6.12.0", "initrd.img-6.11.0")
        with self.assertRaisesRegex(AssertionError, "versions do not match"):
            validator.validate_boot_files(entries, modules, config)

    def test_missing_boot_reference(self):
        entries, modules, config = self.files()
        del entries["/boot/vmlinuz-6.12.0"]
        with self.assertRaisesRegex(AssertionError, "missing non-regular"):
            validator.validate_boot_files(entries, modules, config)

    def test_malformed_comment_only_menuentry(self):
        entries, modules, _ = self.files()
        with self.assertRaisesRegex(AssertionError, "genuine menuentry"):
            validator.validate_boot_files(entries, modules, "# menuentry linux initrd")

    def test_each_required_module(self):
        for name in validator.REQUIRED_MODULES:
            entries, modules, config = self.files()
            del modules[name]
            with self.subTest(name=name), self.assertRaisesRegex(
                AssertionError, "module is missing: " + name
            ):
                validator.validate_boot_files(entries, modules, config)


if __name__ == "__main__":
    unittest.main()
