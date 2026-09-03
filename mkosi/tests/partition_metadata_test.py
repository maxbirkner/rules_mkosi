"""Focused tests for raw GPT validation and normalized projection."""

import os
import ast
import inspect
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


def _rewrite_arrays(raw, mutate):
    for array_offset in (2 * SECTOR, (SECTORS - 3) * SECTOR):
        array = bytearray(raw[array_offset:array_offset + COUNT * ENTRY_SIZE])
        mutate(array)
        raw[array_offset:array_offset + len(array)] = array
        header_offset = SECTOR if array_offset == 2 * SECTOR else (SECTORS - 1) * SECTOR
        struct.pack_into("<I", raw, header_offset + 88, zlib.crc32(array))
        _recrc_header(raw, header_offset)


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

    def digest(self, raw):
        with open(self.path, "wb") as output:
            output.write(raw)
        return partition_metadata.canonical_image_sha256(self.path)

    def test_canonical_digest_covers_partition_payload(self):
        original = image()
        changed = bytearray(original)
        changed[2048 * SECTOR + 123] ^= 1
        self.assertNotEqual(self.digest(original), self.digest(changed))

    def test_canonical_digest_normalizes_only_gpt_identity_and_crcs(self):
        original = image()
        changed = bytearray(original)
        replacement_disk_guid = uuid.uuid4().bytes_le
        for header_offset in (SECTOR, (SECTORS - 1) * SECTOR):
            changed[header_offset + 56:header_offset + 72] = replacement_disk_guid
            _recrc_header(changed, header_offset)
        replacement_partition_guid = uuid.uuid4().bytes_le
        _rewrite_arrays(
            changed,
            lambda array: array.__setitem__(
                slice(ENTRY_SIZE + 16, ENTRY_SIZE + 32),
                replacement_partition_guid,
            ),
        )
        self.assertEqual(self.digest(original), self.digest(changed))

    def test_canonical_digest_preserves_partition_semantics(self):
        original = image()
        mutations = {
            "attributes": lambda array: struct.pack_into(
                "<Q", array, ENTRY_SIZE + 48, 1
            ),
            "lba": lambda array: struct.pack_into(
                "<QQ", array, ENTRY_SIZE + 32, 4096, 6143
            ),
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name):
                changed = bytearray(original)
                _rewrite_arrays(changed, mutation)
                self.assertNotEqual(self.digest(original), self.digest(changed))

        invalid_mutations = {
            "type_guid": lambda array: array.__setitem__(
                slice(ENTRY_SIZE, ENTRY_SIZE + 16),
                uuid.UUID("0fc63daf-8483-4772-8e79-3d69d8477de4").bytes_le,
            ),
            "label": lambda array: array.__setitem__(
                slice(ENTRY_SIZE + 56, ENTRY_SIZE + 80),
                "not-the-root".encode("utf-16-le"),
            ),
        }
        for name, mutation in invalid_mutations.items():
            with self.subTest(name=name):
                changed = bytearray(original)
                _rewrite_arrays(changed, mutation)
                with self.assertRaises(ValueError):
                    self.digest(changed)

    def write_dense_image(self, count):
        sectors = 2048 * (count + 2)
        array = bytearray(count * ENTRY_SIZE)
        for slot in range(count):
            offset = slot * ENTRY_SIZE
            array[offset : offset + 16] = uuid.UUID(
                partition_metadata.ROOT_X86_64
                if slot == 0
                else "0fc63daf-8483-4772-8e79-3d69d8477de4"
            ).bytes_le
            first = 2048 * (slot + 1)
            struct.pack_into("<QQ", array, offset + 32, first, first + 2047)
            label = ("root-x86-64" if slot == 0 else "data-{}".format(slot)).encode(
                "utf-16-le"
            )
            array[offset + 56 : offset + 56 + len(label)] = label
        array_sectors = (len(array) + SECTOR - 1) // SECTOR
        backup_array_lba = sectors - 1 - array_sectors
        primary = _header(
            1,
            sectors - 1,
            2,
            array,
            count=count,
            first_usable=2048,
            last_usable=sectors - 2049,
        )
        backup = _header(
            sectors - 1,
            1,
            backup_array_lba,
            array,
            count=count,
            first_usable=2048,
            last_usable=sectors - 2049,
        )
        with open(self.path, "wb") as output:
            output.truncate(sectors * SECTOR)
            output.seek(SECTOR)
            output.write(primary)
            output.seek(2 * SECTOR)
            output.write(array)
            output.seek(backup_array_lba * SECTOR)
            output.write(array)
            output.seek((sectors - 1) * SECTOR)
            output.write(backup)

    def test_sparse_slots_and_identifier_normalization(self):
        projected = self.project(image())
        self.assertEqual(2, projected["partitions"][0]["number"])
        self.assertNotIn("disk_guid", projected)
        self.assertNotIn("unique_guid", projected["partitions"][0])

    def test_bios_firmware_requires_bios_boot_partition(self):
        entries = [
            (1, 2048, 4095, partition_metadata.BIOS_BOOT, "BIOS Boot"),
            (2, 4096, 6143, partition_metadata.ROOT_X86_64, "root-x86-64"),
        ]
        with open(self.path, "wb") as output:
            output.write(image(entries=entries))
        projected = partition_metadata.project_image(self.path, "bios")
        self.assertEqual("bios", projected["firmware"])
        self.assertEqual(partition_metadata.BIOS_BOOT, projected["partitions"][0]["type_guid"])

        with open(self.path, "wb") as output:
            output.write(image())
        with self.assertRaisesRegex(ValueError, "BIOS boot partition"):
            partition_metadata.project_image(self.path, "bios")

    def test_dense_table_uses_one_linear_entry_scan(self):
        self.write_dense_image(512)
        projected = partition_metadata.project_image(self.path)
        self.assertEqual(512, len(projected["partitions"]))

        tree = ast.parse(inspect.getsource(partition_metadata.project_image))
        slot_loop = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.For)
            and isinstance(node.target, ast.Name)
            and node.target.id == "slot"
        )
        nested_loops = [
            node
            for statement in slot_loop.body
            for node in ast.walk(statement)
            if isinstance(node, (ast.For, ast.While))
        ]
        self.assertEqual([], nested_loops)

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
