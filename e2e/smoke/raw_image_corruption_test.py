import pathlib
import struct
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import raw_image_validator

IMAGE_PATH = None


def _corrupt_third_directory_record(path):
    image = bytearray(path.read_bytes())
    sector_size = raw_image_validator.SECTOR_SIZE
    partition_array = image[2 * sector_size : 2 * sector_size + 128 * 128]
    root_entry = None
    for offset in range(0, len(partition_array), 128):
        entry = partition_array[offset : offset + 128]
        if entry[:16] == raw_image_validator.LINUX_ROOT_X86_64:
            root_entry = entry
            break
    if root_entry is None:
        raise AssertionError("real image has no Linux root partition")
    partition_start = struct.unpack_from("<Q", root_entry, 32)[0]
    partition_offset = partition_start * sector_size
    superblock = image[partition_offset + 1024 : partition_offset + 2048]
    block_size = 1024 << struct.unpack_from("<I", superblock, 24)[0]
    descriptor_offset = partition_offset + (2 if block_size == 1024 else 1) * block_size
    inode_table = struct.unpack_from("<I", image[descriptor_offset + 8 :], 0)[0]
    inode_size = struct.unpack_from("<H", superblock, 88)[0]
    inode_offset = partition_offset + inode_table * block_size + inode_size
    inode = image[inode_offset : inode_offset + inode_size]
    extent_start = struct.unpack_from("<IHHI", inode, 52)[3]
    directory_offset = partition_offset + extent_start * block_size
    first_length = struct.unpack_from("<H", image[directory_offset + 4 :], 0)[0]
    second_offset = directory_offset + first_length
    second_length = struct.unpack_from("<H", image[second_offset + 4 :], 0)[0]
    third_offset = second_offset + second_length
    original_length = struct.unpack_from("<H", image[third_offset + 4 :], 0)[0]
    if original_length == 0:
        raise AssertionError("real root directory has no third record")
    struct.pack_into("<H", image, third_offset + 4, 0)

    if struct.unpack_from("<I", superblock, 100)[0] & raw_image_validator.EXT4_RO_COMPAT_METADATA_CSUM:
        directory = bytearray(image[directory_offset : directory_offset + block_size])
        seed = struct.unpack_from("<I", superblock, 624)[0]
        generation = struct.unpack_from("<I", inode, 100)[0]
        struct.pack_into(
            "<I",
            directory,
            block_size - 4,
            raw_image_validator._directory_checksum(seed, 2, generation, directory),
        )
        image[directory_offset : directory_offset + block_size] = directory
    return image


class RawImageCorruptionTest(unittest.TestCase):
    def test_real_root_directory_rec_len_corruption_is_rejected(self):
        image = _corrupt_third_directory_record(raw_image_validator.image_path(IMAGE_PATH))
        with self.assertRaisesRegex(AssertionError, "record length"):
            raw_image_validator.validate_bytes(image, physical_ranges=[(0, len(image))])


if __name__ == "__main__":
    IMAGE_PATH = sys.argv[1]
    unittest.main(argv=[sys.argv[0]])
