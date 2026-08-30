import io
import pathlib
import struct
import sys
import unittest
import uuid
import zlib

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import raw_image_validator


def _gpt_image():
    total_sectors = 4096
    first_usable = 34
    last_usable = total_sectors - 1 - raw_image_validator.GPT_ENTRY_COUNT // 4 - 1
    data = bytearray(total_sectors * raw_image_validator.SECTOR_SIZE)
    data[510:512] = b"\x55\xaa"
    data[446 + 4] = 0xEE
    struct.pack_into("<II", data, 446 + 8, 1, total_sectors - 1)

    partition_array = bytearray(
        raw_image_validator.GPT_ENTRY_COUNT * raw_image_validator.GPT_ENTRY_SIZE
    )
    partition_array[:16] = raw_image_validator.LINUX_ROOT_X86_64
    partition_array[16:32] = uuid.UUID(int=1).bytes_le
    struct.pack_into("<QQ", partition_array, 32, first_usable, last_usable)
    array_crc = zlib.crc32(partition_array) & 0xFFFFFFFF
    primary_array_lba = 2
    backup_array_lba = total_sectors - 1 - len(partition_array) // 512
    data[
        primary_array_lba * 512 : primary_array_lba * 512 + len(partition_array)
    ] = partition_array
    data[
        backup_array_lba * 512 : backup_array_lba * 512 + len(partition_array)
    ] = partition_array
    disk_guid = uuid.UUID(int=2).bytes_le

    def write_header(lba, backup_lba, array_lba):
        header = bytearray(512)
        header[:8] = b"EFI PART"
        struct.pack_into("<II", header, 8, raw_image_validator.GPT_REVISION, 92)
        struct.pack_into(
            "<QQQQ",
            header,
            24,
            lba,
            backup_lba,
            first_usable,
            last_usable,
        )
        header[56:72] = disk_guid
        struct.pack_into(
            "<QIII",
            header,
            72,
            array_lba,
            raw_image_validator.GPT_ENTRY_COUNT,
            raw_image_validator.GPT_ENTRY_SIZE,
            array_crc,
        )
        struct.pack_into("<I", header, 16, zlib.crc32(header[:92]) & 0xFFFFFFFF)
        data[lba * 512 : (lba + 1) * 512] = header

    write_header(1, total_sectors - 1, primary_array_lba)
    write_header(total_sectors - 1, 1, backup_array_lba)
    return data


class RawImageValidatorTest(unittest.TestCase):
    def test_protective_mbr_is_required(self):
        image = _gpt_image()
        image[510:512] = b"\0\0"
        with self.assertRaisesRegex(AssertionError, "protective MBR signature"):
            raw_image_validator.validate_bytes(image)

    def test_crc_valid_metadata_is_required(self):
        image = _gpt_image()
        image[512 + 24] ^= 1
        with self.assertRaisesRegex(AssertionError, "header CRC"):
            raw_image_validator.validate_bytes(image)

    def test_fabricated_sparse_pseudo_gpt_has_no_allocated_root(self):
        image = _gpt_image()
        with self.assertRaisesRegex(AssertionError, "not materially allocated"):
            raw_image_validator._validate(io.BytesIO(image), len(image), 0)

    def test_pseudo_gpt_requires_a_usable_ext4_root(self):
        image = _gpt_image()
        with self.assertRaisesRegex(AssertionError, "recognizable ext4"):
            raw_image_validator.validate_bytes(image)


if __name__ == "__main__":
    unittest.main()
