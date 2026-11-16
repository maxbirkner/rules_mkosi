"""Tests the GPT reader of the shared disk image test helper on synthetic images."""

import pathlib
import tempfile
import unittest

import rules_mkosi_disk_image as disk_image

from mkosi.tests.partition_metadata_test import SECTOR, image

_ROOT = disk_image.gpt_partitions.ROOT_X86_64


class DiskImageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = pathlib.Path(self.directory.name) / "image.raw"

    def write(self, raw: bytes | bytearray) -> pathlib.Path:
        self.path.write_bytes(raw)
        return self.path

    def test_lists_used_partitions_in_table_order(self) -> None:
        raw = image([(1, 2048, 4095, disk_image.gpt_partitions.ESP, "esp"), (3, 4096, 8191, _ROOT, "root-x86-64")])
        self.assertEqual(
            disk_image.list_partitions(self.write(raw)),
            [
                disk_image.Partition(1, disk_image.gpt_partitions.ESP, "esp", 2048 * SECTOR, 2048 * SECTOR),
                disk_image.Partition(3, _ROOT, "root-x86-64", 4096 * SECTOR, 4096 * SECTOR),
            ],
        )

    def test_rejects_an_image_without_a_valid_gpt(self) -> None:
        raw = image()
        raw[SECTOR : SECTOR + 8] = b"NOT GPT!"
        with self.assertRaises(ValueError):
            disk_image.list_partitions(self.write(raw))

    def test_finds_the_populated_root_and_skips_inactive_slots(self) -> None:
        raw = image([(1, 2048, 4095, _ROOT, "image_1"), (2, 4096, 6143, _ROOT, "_empty")])
        self.assertEqual(disk_image.find_root_partition(self.write(raw)).label, "image_1")

    def test_requires_one_root_of_the_architecture(self) -> None:
        path = self.write(image())
        with self.assertRaisesRegex(AssertionError, "arm64"):
            disk_image.find_root_partition(path, "arm64")

    def test_extracts_partition_bytes_and_holes(self) -> None:
        raw = image()
        start = 2048 * SECTOR
        raw[start : start + 5] = b"first"
        raw[start + 2048 * SECTOR - 4 : start + 2048 * SECTOR] = b"last"
        # A sparse copy of raw, whose holes extract_partition skips.
        with self.path.open("wb") as sparse:
            sparse.truncate(len(raw))
            for offset in range(0, len(raw), 4096):
                if any(raw[offset : offset + 4096]):
                    sparse.seek(offset)
                    sparse.write(raw[offset : offset + 4096])
        destination = pathlib.Path(self.directory.name) / "root.ext4"
        root = disk_image.extract_root_partition(self.path, destination)
        self.assertEqual(destination.read_bytes(), bytes(raw[start : start + root.size_bytes]))

    def test_rejects_a_truncated_partition(self) -> None:
        path = self.write(image())
        beyond = disk_image.Partition(9, _ROOT, "root-x86-64", path.stat().st_size - SECTOR, 2 * SECTOR)
        with self.assertRaisesRegex(AssertionError, "truncated"):
            disk_image.extract_partition(path, beyond, pathlib.Path(self.directory.name) / "partition")


if __name__ == "__main__":
    unittest.main()
