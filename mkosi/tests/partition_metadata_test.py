"""Focused tests for raw GPT validation and normalized projection."""

import os
import struct
import tempfile
import unittest
import uuid
import zlib

from mkosi.private import partition_metadata

SECTOR = 512
SECTORS = 32768
COUNT = 8
ENTRY_SIZE = 128


def _header(current, backup, entries_lba, array, **overrides):
    values = {
        "revision": 0x10000,
        "header_size": 92,
        "first_usable": 2048,
        "last_usable": SECTORS - 2049,
        "count": COUNT,
        "entry_size": ENTRY_SIZE,
    }
    values.update(overrides)
    result = bytearray(SECTOR)
    result[:8] = b"EFI PART"
    struct.pack_into(
        "<IIIIQQQQ16sQIII",
        result,
        8,
        values["revision"],
        values["header_size"],
        0,
        0,
        current,
        backup,
        values["first_usable"],
        values["last_usable"],
        uuid.UUID("12345678-1234-5678-9abc-def012345678").bytes_le,
        entries_lba,
        values["count"],
        values["entry_size"],
        zlib.crc32(array),
    )
    struct.pack_into("<I", result, 16, zlib.crc32(result[: values["header_size"]]))
    return result


def image(entries=None, primary_overrides=None, backup_overrides=None):
    array = bytearray(COUNT * ENTRY_SIZE)
    if entries is None:
        entries = [(2, 2048, 4095, partition_metadata.ROOT_X86_64, "root-x86-64")]
    for slot, first, last, type_guid, label in entries:
        offset = (slot - 1) * ENTRY_SIZE
        array[offset : offset + 16] = uuid.UUID(type_guid).bytes_le
        array[offset + 16 : offset + 32] = uuid.uuid4().bytes_le
        struct.pack_into("<QQQ", array, offset + 32, first, last, 0)
        encoded = label.encode("utf-16-le")
        array[offset + 56 : offset + 56 + len(encoded)] = encoded
    raw = bytearray(SECTORS * SECTOR)
    primary_lba = 2
    backup_lba = SECTORS - 3
    raw[primary_lba * SECTOR : primary_lba * SECTOR + len(array)] = array
    raw[backup_lba * SECTOR : backup_lba * SECTOR + len(array)] = array
    raw[SECTOR : 2 * SECTOR] = _header(
        1, SECTORS - 1, primary_lba, array, **(primary_overrides or {})
    )
    raw[-SECTOR:] = _header(
        SECTORS - 1, 1, backup_lba, array, **(backup_overrides or {})
    )
    return raw


def _recrc_header(raw, offset):
    header = bytearray(raw[offset : offset + SECTOR])
    header[16:20] = b"\0" * 4
    struct.pack_into("<I", raw, offset + 16, zlib.crc32(header[:92]))


class ProjectionTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.directory.name, "image.raw")

    def tearDown(self):
        self.directory.cleanup()

    def project(self, raw):
        with open(self.path, "wb") as output:
            output.write(raw)
        return partition_metadata.project_image(self.path)

    def test_sparse_slots_and_identifier_normalization(self):
        projected = self.project(image())
        self.assertEqual(2, projected["partitions"][0]["number"])
        self.assertNotIn("disk_guid", projected)
        self.assertNotIn("unique_guid", projected["partitions"][0])

    def test_each_header_and_array_copy_is_checked(self):
        for offset in (SECTOR + 24, (SECTORS - 1) * SECTOR + 24, 2 * SECTOR, (SECTORS - 3) * SECTOR):
            with self.subTest(offset=offset):
                raw = image()
                raw[offset] ^= 1
                with self.assertRaisesRegex(ValueError, "CRC"):
                    self.project(raw)

    def test_consistent_crc_protected_copies_are_required(self):
        raw = image()
        backup_array = (SECTORS - 3) * SECTOR
        raw[backup_array + 56] ^= 1
        struct.pack_into(
            "<I",
            raw,
            (SECTORS - 1) * SECTOR + 88,
            zlib.crc32(raw[backup_array : backup_array + COUNT * ENTRY_SIZE]),
        )
        _recrc_header(raw, (SECTORS - 1) * SECTOR)
        with self.assertRaisesRegex(ValueError, "arrays disagree"):
            self.project(raw)

        raw = image()
        raw[(SECTORS - 1) * SECTOR + 56] ^= 1
        _recrc_header(raw, (SECTORS - 1) * SECTOR)
        with self.assertRaisesRegex(ValueError, "disk_guid"):
            self.project(raw)

    def test_truncation_and_non_divisible_size(self):
        for raw in (image()[:-SECTOR], image()[:-1]):
            with self.subTest(size=len(raw)):
                with self.assertRaises(ValueError):
                    self.project(raw)

    def test_hostile_count_entry_size_and_array_location(self):
        cases = [
            {"count": partition_metadata._MAX_ENTRIES + 1},
            {"entry_size": 8192},
        ]
        for overrides in cases:
            with self.subTest(overrides=overrides):
                with self.assertRaisesRegex(ValueError, "hostile|oversized"):
                    self.project(image(primary_overrides=overrides))
        raw = image()
        struct.pack_into("<Q", raw, SECTOR + 72, SECTORS - 1)
        _recrc_header(raw, SECTOR)
        with self.assertRaisesRegex(ValueError, "outside|location"):
            self.project(raw)

    def test_reciprocal_and_usable_bounds(self):
        for overrides in (
            {"first_usable": SECTORS},
            {"last_usable": SECTORS - 1},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaisesRegex(ValueError, "usable"):
                    self.project(image(primary_overrides=overrides))
        raw = image()
        struct.pack_into("<Q", raw, SECTOR + 32, 7)
        _recrc_header(raw, SECTOR)
        with self.assertRaisesRegex(ValueError, "reciprocal"):
            self.project(raw)

    def test_partition_rules(self):
        wrong = "0fc63daf-8483-4772-8e79-3d69d8477de4"
        cases = [
            ([], "exactly one"),
            ([(2, 2049, 4095, partition_metadata.ROOT_X86_64, "root-x86-64")], "aligned"),
            ([(2, 1024, 4095, partition_metadata.ROOT_X86_64, "root-x86-64")], "usable"),
            ([(2, 2048, 4095, wrong, "root-x86-64")], "exactly one"),
            ([(2, 2048, 4095, partition_metadata.ROOT_X86_64, "wrong")], "label"),
            (
                [
                    (2, 2048, 4095, partition_metadata.ROOT_X86_64, "root-x86-64"),
                    (5, 3072, 5119, wrong, "data"),
                ],
                "overlaps",
            ),
            (
                [
                    (2, 4096, 6143, partition_metadata.ROOT_X86_64, "root-x86-64"),
                    (5, 2048, 4095, wrong, "data"),
                ],
                "out of order",
            ),
        ]
        for entries, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    self.project(image(entries=entries))


if __name__ == "__main__":
    unittest.main()
