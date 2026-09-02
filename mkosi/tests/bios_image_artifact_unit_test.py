"""Structured negative fixtures for the BIOS artifact validator."""

import importlib.util
import lzma
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
        self.boot[0x1BE:0x1FE] = bytes(64)
        self.boot[510:512] = b"\x55\xaa"
        struct.pack_into("<B3sB3sII", self.boot, 0x1BE, 0, b"\0\2\0", 0xEE, b"\xff\xff\xff", 1, 4095)
        self.diskboot = bytearray((i * 29 + 7) & 255 for i in range(512))
        self.raw = bytearray(2 * 1048576)
        self.raw[:512] = self.boot
        self.raw[1048576:1049088] = self.diskboot
        decompressor = bytearray((i * 17 + 3) & 255 for i in range(64))
        struct.pack_into("<H", decompressor, 0x14, 32)
        self.decompressor = bytes(decompressor)
        self.kernel = bytes((i * 13 + 5) & 255 for i in range(96))
        self.modules = {
            name: bytes(((i + index) * 11 + 7) & 255 for i in range(31 + index))
            for index, name in enumerate(validator.REQUIRED_MODULES)
        }
        records = bytearray()
        for reference in self.modules.values():
            size = 8 + len(reference)
            records.extend(struct.pack("<II", 0, size) + reference)
            records.extend(bytes((-size) % 4))
        config = b"search --no-floppy --set=root --file /grub/grub.cfg\0"
        size = 8 + len(config)
        records.extend(struct.pack("<II", 2, size) + config)
        records.extend(bytes((-size) % 4))
        expanded = self.kernel + struct.pack("<III", 0x676D696D, 12, 12 + len(records)) + records
        compressed = lzma.compress(
            expanded,
            format=lzma.FORMAT_RAW,
            filters=[{"id": lzma.FILTER_LZMA1, "dict_size": 1 << 16, "lc": 3, "lp": 0, "pb": 2}],
        )
        linked_size = ((len(self.decompressor) + len(compressed) + 511) // 512) * 512
        redundancy = linked_size - len(self.decompressor) - len(compressed)
        linked = bytearray(self.decompressor)
        struct.pack_into("<III", linked, 8, len(compressed), len(expanded), redundancy)
        linked.extend(compressed)
        linked.extend(bytes(redundancy))
        count = len(linked) // 512
        struct.pack_into("<QHH", self.raw, 1048576 + validator.BLOCKLIST_LAST, 2049, count, 0x800)
        struct.pack_into("<QHH", self.raw, 1048576 + validator.BLOCKLIST_LAST - 12, 0, 0, 0)
        self.raw[2049 * 512:(2049 + count) * 512] = linked
        self.image.write_bytes(self.raw)

    def tearDown(self):
        self.directory.cleanup()

    def check(self, pattern):
        with self.assertRaisesRegex(AssertionError, pattern):
            validator.validate_boot_regions(
                self.image, self.metadata, bytes(self.boot), bytes(self.diskboot),
                self.decompressor, self.kernel, self.modules,
            )

    def test_mbr_signature(self):
        self.raw[510] ^= 1; self.image.write_bytes(self.raw); self.check("MBR signature")

    def test_protective_mbr_wrong_type(self):
        self.raw[0x1BE + 4] = 0x83; self.image.write_bytes(self.raw); self.check("exactly one protective")

    def test_protective_mbr_missing(self):
        self.raw[0x1BE:0x1CE] = bytes(16); self.image.write_bytes(self.raw); self.check("exactly one protective")

    def test_protective_mbr_active(self):
        self.raw[0x1BE] = 0x80; self.image.write_bytes(self.raw); self.check("must not be active")

    def test_protective_mbr_start(self):
        struct.pack_into("<I", self.raw, 0x1BE + 8, 2); self.image.write_bytes(self.raw); self.check("start at LBA 1")

    def test_protective_mbr_coverage(self):
        struct.pack_into("<I", self.raw, 0x1BE + 12, 4094); self.image.write_bytes(self.raw); self.check("cover the disk")

    def test_hybrid_mbr_entry(self):
        struct.pack_into("<B3sB3sII", self.raw, 0x1CE, 0x80, b"\0\0\0", 0x83, b"\0\0\0", 2, 4)
        self.image.write_bytes(self.raw); self.check("hybrid MBR")

    def test_random_bootstrap(self):
        self.raw[0x70] ^= 1; self.image.write_bytes(self.raw); self.check("MBR invariant")

    def test_invariant_patch_corruption(self):
        self.raw[1048576 + 20] ^= 1; self.image.write_bytes(self.raw); self.check("diskboot invariant")

    def test_out_of_bounds_blocklist(self):
        struct.pack_into("<Q", self.raw, 1048576 + validator.BLOCKLIST_LAST, 4096)
        self.image.write_bytes(self.raw); self.check("leaves BIOS")

    def test_deeper_core_corruption(self):
        self.raw[2049 * 512 + len(self.decompressor) + 10] ^= 1
        self.image.write_bytes(self.raw); self.check("compressed stream")

    def test_truncated_compressed_stream(self):
        struct.pack_into("<I", self.raw, 2049 * 512 + 8, 4096)
        self.image.write_bytes(self.raw); self.check("compressed stream is truncated")

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
        validator.validate_boot_regions(
            self.image, self.metadata, bytes(self.boot), bytes(self.diskboot),
            self.decompressor, self.kernel, self.modules,
        )
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
