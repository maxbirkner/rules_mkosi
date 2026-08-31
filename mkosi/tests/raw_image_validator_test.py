import ctypes
import io
import os
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


def _fake_ext4_root(image, include_data=True, junk=False):
    partition_offset = 34 * 512
    block_size = 4096
    superblock = bytearray(1024)
    struct.pack_into("<I", superblock, 0, 16)
    struct.pack_into("<I", superblock, 4, 400)
    struct.pack_into("<I", superblock, 24, 2)
    struct.pack_into("<I", superblock, 32, 400)
    struct.pack_into("<I", superblock, 40, 16)
    superblock[56:58] = raw_image_validator.EXT4_MAGIC
    struct.pack_into("<I", superblock, 76, 1)
    struct.pack_into("<H", superblock, 88, 256)
    struct.pack_into(
        "<I",
        superblock,
        96,
        raw_image_validator.EXT4_INCOMPAT_EXTENTS | 0x80,
    )
    struct.pack_into("<H", superblock, 254, 64)
    image[partition_offset + 1024 : partition_offset + 2048] = superblock

    descriptor = bytearray(64)
    struct.pack_into("<III", descriptor, 0, 2, 3, 4)
    descriptor_offset = partition_offset + block_size
    image[descriptor_offset : descriptor_offset + len(descriptor)] = descriptor

    block_bitmap = bytearray(block_size)
    for block in (2, 3, 4, 5):
        block_bitmap[block // 8] |= 1 << (block % 8)
    inode_bitmap = bytearray(block_size)
    inode_bitmap[0] = 1 << 1
    image[
        partition_offset + 2 * block_size : partition_offset + 3 * block_size
    ] = block_bitmap
    image[
        partition_offset + 3 * block_size : partition_offset + 4 * block_size
    ] = inode_bitmap

    inode = bytearray(256)
    struct.pack_into("<H", inode, 0, 0x41ED)
    struct.pack_into("<I", inode, 4, block_size)
    struct.pack_into("<I", inode, 32, raw_image_validator.EXT4_EXTENTS)
    struct.pack_into("<HHHH", inode, 40, 0xF30A, 1, 4, 0)
    struct.pack_into("<IHHI", inode, 52, 0, 1, 0, 5)
    inode_offset = partition_offset + 4 * block_size + 256
    image[inode_offset : inode_offset + len(inode)] = inode

    if include_data:
        root_data = bytearray(block_size)
        struct.pack_into("<IHBB", root_data, 0, 2, 12, 1, 2)
        root_data[8:9] = b"."
        struct.pack_into("<IHBB", root_data, 12, 2, 12, 2, 2)
        root_data[20:22] = b".."
        if junk:
            struct.pack_into("<IHBB", root_data, 24, 3, block_size - 24, 4, 8)
            root_data[32:36] = b"junk"
        image[
            partition_offset + 5 * block_size : partition_offset + 6 * block_size
        ] = root_data
    return image


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
        image = _fake_ext4_root(_gpt_image(), include_data=False)
        libc = ctypes.CDLL(None, use_errno=True)
        libc.memfd_create.argtypes = [ctypes.c_char_p, ctypes.c_uint]
        libc.memfd_create.restype = ctypes.c_int
        fd = libc.memfd_create(b"rules-mkosi-sparse-gpt", 0)
        if fd < 0:
            raise OSError(ctypes.get_errno(), "memfd_create")
        try:
            os.ftruncate(fd, len(image))
            partition_offset = 34 * 512
            block_size = 4096
            ranges = [
                (0, 34 * 512),
                ((4096 - 33) * 512, len(image)),
                (partition_offset + 1024, partition_offset + 2048),
                (partition_offset + block_size, partition_offset + 5 * block_size),
                (partition_offset + 4 * block_size + 256, partition_offset + 4 * block_size + 512),
            ]
            for start, end in ranges:
                os.pwrite(fd, image[start:end], start)
            with os.fdopen(fd, "r+b") as sparse:
                fd = -1
                with self.assertRaisesRegex(AssertionError, "not physically allocated"):
                    raw_image_validator._validate(
                        sparse,
                        len(image),
                    )
        finally:
            if fd >= 0:
                os.close(fd)

    def test_fully_allocated_fabricated_root_directory_junk_is_rejected(self):
        image = _fake_ext4_root(_gpt_image(), junk=True)
        with self.assertRaisesRegex(AssertionError, "directory entry is invalid"):
            raw_image_validator.validate_bytes(image, physical_ranges=[(0, len(image))])

    def test_pseudo_gpt_requires_a_usable_ext4_root(self):
        image = _gpt_image()
        with self.assertRaisesRegex(AssertionError, "recognizable ext4"):
            raw_image_validator.validate_bytes(image)


if __name__ == "__main__":
    unittest.main()
