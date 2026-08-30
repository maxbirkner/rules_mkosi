import io
import os
import pathlib
import struct
import sys
import uuid
import zlib


SECTOR_SIZE = 512
GPT_HEADER_SIZE = 92
GPT_REVISION = 0x00010000
GPT_ENTRY_SIZE = 128
GPT_ENTRY_COUNT = 128
LINUX_ROOT_X86_64 = uuid.UUID("4f68bce3-e8cd-4db1-96e7-fbcaf984b709").bytes_le
EXT4_MAGIC = b"\x53\xef"
EXT4_EXTENTS = 0x00080000
EXT4_INCOMPAT_EXTENTS = 0x00000040


def image_path(argument):
    path = pathlib.Path(argument)
    if path.is_absolute():
        return path
    return pathlib.Path(os.environ["TEST_SRCDIR"]) / os.environ["TEST_WORKSPACE"] / path


def _read(image, offset, size, message):
    image.seek(offset)
    value = image.read(size)
    if len(value) != size:
        raise AssertionError(message)
    return value


def _parse_header(image, lba, total_sectors):
    raw = _read(image, lba * SECTOR_SIZE, SECTOR_SIZE, "GPT header is truncated")
    if raw[:8] != b"EFI PART":
        raise AssertionError("GPT header signature is missing at LBA %d" % lba)
    revision, header_size, stored_crc = struct.unpack_from("<III", raw, 8)
    if revision != GPT_REVISION:
        raise AssertionError("GPT header revision is unsupported")
    if header_size < GPT_HEADER_SIZE or header_size > SECTOR_SIZE:
        raise AssertionError("GPT header size is invalid")
    header = bytearray(raw[:header_size])
    struct.pack_into("<I", header, 16, 0)
    if zlib.crc32(header) & 0xFFFFFFFF != stored_crc:
        raise AssertionError("GPT header CRC is invalid at LBA %d" % lba)

    current_lba, backup_lba, first_usable, last_usable = struct.unpack_from(
        "<QQQQ", raw, 24
    )
    array_lba, entry_count, entry_size, array_crc = struct.unpack_from("<QIII", raw, 72)
    if current_lba != lba or backup_lba >= total_sectors:
        raise AssertionError("GPT header LBA relationship is invalid")
    if first_usable < 2 or first_usable > last_usable or last_usable >= total_sectors:
        raise AssertionError("GPT usable LBA range is invalid")
    if entry_count == 0 or entry_size < GPT_ENTRY_SIZE or entry_size % 8:
        raise AssertionError("GPT partition entry geometry is invalid")
    array_size = entry_count * entry_size
    array_sectors = (array_size + SECTOR_SIZE - 1) // SECTOR_SIZE
    if array_lba < 2 or array_lba + array_sectors > total_sectors:
        raise AssertionError("GPT partition array is outside the image")
    array = _read(
        image,
        array_lba * SECTOR_SIZE,
        array_size,
        "GPT partition array is truncated",
    )
    if zlib.crc32(array) & 0xFFFFFFFF != array_crc:
        raise AssertionError("GPT partition array CRC is invalid")
    return {
        "current_lba": current_lba,
        "backup_lba": backup_lba,
        "first_usable": first_usable,
        "last_usable": last_usable,
        "disk_guid": raw[56:72],
        "array_lba": array_lba,
        "array_sectors": array_sectors,
        "entry_count": entry_count,
        "entry_size": entry_size,
        "array": array,
    }


def _validate_ext4_root(image, partition_start, partition_end, allocated_bytes):
    partition_offset = partition_start * SECTOR_SIZE
    partition_size = (partition_end - partition_start + 1) * SECTOR_SIZE
    if partition_size < 1024 * 1024:
        raise AssertionError("Linux root partition is unexpectedly small")
    if allocated_bytes < partition_offset + SECTOR_SIZE:
        raise AssertionError("raw image root partition is not materially allocated")

    superblock = _read(
        image,
        partition_offset + 1024,
        1024,
        "Linux root filesystem superblock is truncated",
    )
    if superblock[56:58] != EXT4_MAGIC:
        raise AssertionError("Linux root partition is not a recognizable ext4 filesystem")
    if struct.unpack_from("<I", superblock, 76)[0] != 1:
        raise AssertionError("Linux root filesystem revision is unsupported")
    block_size_log = struct.unpack_from("<I", superblock, 24)[0]
    if block_size_log > 6:
        raise AssertionError("Linux root filesystem block size is invalid")
    block_size = 1024 << block_size_log
    if block_size > 65536:
        raise AssertionError("Linux root filesystem block size is unsupported")
    blocks = struct.unpack_from("<I", superblock, 4)[0]
    blocks |= struct.unpack_from("<I", superblock, 336)[0] << 32
    if blocks == 0 or blocks * block_size > partition_size:
        raise AssertionError("Linux root filesystem geometry exceeds its partition")
    if struct.unpack_from("<I", superblock, 32)[0] == 0:
        raise AssertionError("Linux root filesystem has no block groups")
    if struct.unpack_from("<I", superblock, 40)[0] == 0:
        raise AssertionError("Linux root filesystem has no inodes")
    incompat_features = struct.unpack_from("<I", superblock, 96)[0]
    if incompat_features & EXT4_INCOMPAT_EXTENTS == 0:
        raise AssertionError("Linux root filesystem does not advertise extents")

    inode_size = struct.unpack_from("<H", superblock, 88)[0]
    descriptor_size = struct.unpack_from("<H", superblock, 254)[0] or 32
    if inode_size < 128 or inode_size > block_size or descriptor_size not in (32, 64):
        raise AssertionError("Linux root filesystem inode geometry is invalid")
    if incompat_features & 0x80 and descriptor_size != 64:
        raise AssertionError("Linux root filesystem descriptor geometry is invalid")

    descriptor_block = 2 if block_size == 1024 else 1
    descriptor = _read(
        image,
        partition_offset + descriptor_block * block_size,
        descriptor_size,
        "Linux root filesystem group descriptor is truncated",
    )
    inode_table = struct.unpack_from("<I", descriptor, 8)[0]
    if descriptor_size == 64:
        inode_table |= struct.unpack_from("<I", descriptor, 40)[0] << 32
    inode_offset = partition_offset + inode_table * block_size + inode_size
    if inode_offset + inode_size > partition_offset + partition_size:
        raise AssertionError("Linux root inode is outside the root partition")
    inode = _read(image, inode_offset, inode_size, "Linux root inode is truncated")
    mode = struct.unpack_from("<H", inode, 0)[0]
    if mode & 0xF000 != 0x4000 or struct.unpack_from("<I", inode, 4)[0] == 0:
        raise AssertionError("Linux root inode is not a usable directory")
    if struct.unpack_from("<I", inode, 32)[0] & EXT4_EXTENTS == 0:
        raise AssertionError("Linux root inode does not contain extents")

    extent = inode[40:100]
    magic, entries, maximum, depth = struct.unpack_from("<HHHH", extent, 0)
    if magic != 0xF30A or entries == 0 or entries > maximum or depth != 0:
        raise AssertionError("Linux root inode extent tree is invalid")
    logical, length, start_high, start_low = struct.unpack_from("<IHHI", extent, 12)
    length &= 0x7FFF
    physical = start_low | (start_high << 32)
    if logical != 0 or length == 0 or physical + length > blocks:
        raise AssertionError("Linux root inode extent is outside the filesystem")
    root_data = _read(
        image,
        partition_offset + physical * block_size,
        min(block_size, 4 * 1024 * 1024),
        "Linux root inode extent is truncated",
    )
    if sum(byte != 0 for byte in root_data) < 64:
        raise AssertionError("Linux root inode extent has no allocated content")
    first_inode, first_length, first_name_length, first_type = struct.unpack_from(
        "<IHBB", root_data, 0
    )
    first_name = root_data[8 : 8 + first_name_length]
    second_inode, second_length, second_name_length, second_type = struct.unpack_from(
        "<IHBB", root_data, first_length
    )
    second_name = root_data[first_length + 8 : first_length + 8 + second_name_length]
    if (
        first_inode != 2
        or first_length != 12
        or first_name_length != 1
        or first_type != 2
        or first_name != b"."
        or second_inode != 2
        or second_length < 12
        or second_name_length != 2
        or second_type != 2
        or second_name != b".."
    ):
        raise AssertionError("Linux root directory entries are not usable")


def _validate(image, size, allocated_bytes):
    if size == 0 or size % SECTOR_SIZE:
        raise AssertionError("raw image size is empty or not sector aligned")
    total_sectors = size // SECTOR_SIZE
    if total_sectors < 34:
        raise AssertionError("raw image is too small for GPT metadata")

    mbr = _read(image, 0, SECTOR_SIZE, "protective MBR is truncated")
    if mbr[510:512] != b"\x55\xaa":
        raise AssertionError("protective MBR signature is missing")
    protective = mbr[446:462]
    if protective[4] != 0xEE:
        raise AssertionError("protective MBR partition is missing")
    first_lba, sector_count = struct.unpack_from("<II", protective, 8)
    if first_lba != 1 or sector_count != total_sectors - 1:
        raise AssertionError("protective MBR does not cover the disk")
    if mbr[462:510] != b"\0" * 48:
        raise AssertionError("protective MBR contains unexpected partitions")

    primary = _parse_header(image, 1, total_sectors)
    backup = _parse_header(image, total_sectors - 1, total_sectors)
    if primary["backup_lba"] != backup["current_lba"] or backup["backup_lba"] != 1:
        raise AssertionError("primary and backup GPT headers disagree")
    if primary["disk_guid"] == b"\0" * 16 or primary["disk_guid"] != backup["disk_guid"]:
        raise AssertionError("primary and backup GPT disk GUIDs disagree")
    if (
        primary["first_usable"] != backup["first_usable"]
        or primary["last_usable"] != backup["last_usable"]
        or primary["entry_count"] != backup["entry_count"]
        or primary["entry_size"] != backup["entry_size"]
    ):
        raise AssertionError("primary and backup GPT geometry disagrees")
    if primary["array"] != backup["array"]:
        raise AssertionError("primary and backup GPT partition arrays differ")
    if primary["array_lba"] + primary["array_sectors"] > primary["first_usable"]:
        raise AssertionError("primary GPT metadata overlaps usable LBAs")
    if backup["array_lba"] <= backup["last_usable"]:
        raise AssertionError("backup GPT metadata overlaps usable LBAs")
    if backup["array_lba"] + backup["array_sectors"] > backup["current_lba"]:
        raise AssertionError("backup GPT partition array overlaps its header")

    partitions = []
    partition_guids = set()
    for index in range(primary["entry_count"]):
        entry = primary["array"][
            index * primary["entry_size"] : (index + 1) * primary["entry_size"]
        ]
        if entry[:16] == b"\0" * 16:
            continue
        if entry[16:32] == b"\0" * 16 or entry[16:32] in partition_guids:
            raise AssertionError("GPT partition GUIDs are missing or duplicated")
        partition_guids.add(entry[16:32])
        start, end = struct.unpack_from("<QQ", entry, 32)
        if start < primary["first_usable"] or end > primary["last_usable"] or end < start:
            raise AssertionError("GPT partition %d has an invalid usable range" % index)
        partitions.append((start, end, entry[:16]))
    for index, (start, end, _) in enumerate(partitions):
        for prior_start, prior_end, _ in partitions[:index]:
            if prior_start <= end and start <= prior_end:
                raise AssertionError("GPT partitions overlap")
    roots = [(start, end) for start, end, kind in partitions if kind == LINUX_ROOT_X86_64]
    if not roots:
        raise AssertionError("raw image has no Linux x86-64 root partition")
    _validate_ext4_root(image, roots[0][0], roots[0][1], allocated_bytes)


def validate_bytes(data):
    _validate(io.BytesIO(data), len(data), len(data))


def validate(path):
    stat = path.stat()
    with path.open("rb") as image:
        _validate(image, stat.st_size, stat.st_blocks * 512)
    print(
        "validated raw image: protective MBR, CRC-valid GPT, Linux root ext4 "
        "extent, allocated content (%d bytes)" % stat.st_size
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: raw_image_validator.py IMAGE")
    validate(image_path(sys.argv[1]))
