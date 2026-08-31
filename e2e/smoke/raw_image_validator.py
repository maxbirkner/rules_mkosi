import errno
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
EXT4_INCOMPAT_64BIT = 0x00000080
EXT4_INCOMPAT_CSUM_SEED = 0x00002000
EXT4_RO_COMPAT_METADATA_CSUM = 0x00000400
EXT4_DIR_CSUM = 0xDE


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


def _physical_data_ranges(image, start, end):
    try:
        fd = image.fileno()
    except (AttributeError, io.UnsupportedOperation):
        raise AssertionError("physical data extents are unavailable for this image")
    seek_data = getattr(os, "SEEK_DATA", 3)
    seek_hole = getattr(os, "SEEK_HOLE", 4)
    ranges = []
    cursor = start
    while cursor < end:
        try:
            data = os.lseek(fd, cursor, seek_data)
        except OSError as error:
            if error.errno == errno.ENXIO:
                break
            if error.errno in (errno.EINVAL, errno.ENOTSUP):
                raise AssertionError("filesystem does not report physical data extents")
            raise
        if data >= end:
            break
        try:
            hole = os.lseek(fd, data, seek_hole)
        except OSError as error:
            if error.errno in (errno.EINVAL, errno.ENOTSUP):
                raise AssertionError("filesystem does not report physical data extents")
            raise
        if hole <= data:
            raise AssertionError("filesystem returned an invalid physical data extent")
        ranges.append((data, min(hole, end)))
        cursor = hole
    return ranges


def _range_fully_allocated(ranges, start, end):
    cursor = start
    for data, hole in sorted(ranges):
        if hole <= cursor:
            continue
        if data > cursor:
            return False
        cursor = max(cursor, hole)
        if cursor >= end:
            return True
    return False


def _crc32c(crc, data):
    for byte in data:
        for _ in range(8):
            crc = (crc >> 1) ^ 0x82F63B78 if (crc ^ byte) & 1 else crc >> 1
            byte >>= 1
    return crc & 0xFFFFFFFF


def _directory_checksum(seed, inode_number, generation, block):
    checksum = _crc32c(seed, struct.pack("<I", inode_number))
    checksum = _crc32c(checksum, struct.pack("<I", generation))
    return _crc32c(checksum, block[:-12])


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


def _validate_ext4_root(image, partition_start, partition_end, physical_ranges=None):
    partition_offset = partition_start * SECTOR_SIZE
    partition_size = (partition_end - partition_start + 1) * SECTOR_SIZE
    if partition_size < 1024 * 1024:
        raise AssertionError("Linux root partition is unexpectedly small")
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
    blocks_per_group = struct.unpack_from("<I", superblock, 32)[0]
    inodes_per_group = struct.unpack_from("<I", superblock, 40)[0]
    if blocks_per_group == 0 or inodes_per_group == 0:
        raise AssertionError("Linux root filesystem has no block groups or inodes")
    incompat_features = struct.unpack_from("<I", superblock, 96)[0]
    if incompat_features & EXT4_INCOMPAT_EXTENTS == 0:
        raise AssertionError("Linux root filesystem does not advertise extents")

    inode_size = struct.unpack_from("<H", superblock, 88)[0]
    descriptor_size = struct.unpack_from("<H", superblock, 254)[0] or 32
    if inode_size < 128 or inode_size > block_size or descriptor_size not in (32, 64):
        raise AssertionError("Linux root filesystem inode geometry is invalid")
    if incompat_features & EXT4_INCOMPAT_64BIT and descriptor_size != 64:
        raise AssertionError("Linux root filesystem descriptor geometry is invalid")

    descriptor_block = 2 if block_size == 1024 else 1
    descriptor_offset = partition_offset + descriptor_block * block_size
    descriptor = _read(
        image,
        descriptor_offset,
        descriptor_size,
        "Linux root filesystem group descriptor is truncated",
    )
    block_bitmap = struct.unpack_from("<I", descriptor, 0)[0]
    inode_bitmap = struct.unpack_from("<I", descriptor, 4)[0]
    inode_table = struct.unpack_from("<I", descriptor, 8)[0]
    if descriptor_size == 64:
        block_bitmap |= struct.unpack_from("<I", descriptor, 32)[0] << 32
        inode_bitmap |= struct.unpack_from("<I", descriptor, 36)[0] << 32
        inode_table |= struct.unpack_from("<I", descriptor, 40)[0] << 32
    group_end = min(blocks, blocks_per_group)
    inode_table_blocks = (
        inodes_per_group * inode_size + block_size - 1
    ) // block_size
    metadata_blocks = [
        (block_bitmap, 1),
        (inode_bitmap, 1),
        (inode_table, inode_table_blocks),
    ]
    for metadata_index, (metadata_start, metadata_length) in enumerate(metadata_blocks):
        if (
            metadata_start == 0
            or metadata_start + metadata_length > group_end
            or any(
                metadata_start < other_start + other_length
                and other_start < metadata_start + metadata_length
                for other_index, (other_start, other_length) in enumerate(metadata_blocks)
                if other_index != metadata_index
            )
        ):
            raise AssertionError("Linux root filesystem allocation metadata overlaps")

    data_ranges = physical_ranges or _physical_data_ranges(
        image,
        partition_offset,
        partition_offset + partition_size,
    )
    for metadata_start, metadata_length in metadata_blocks:
        metadata_offset = partition_offset + metadata_start * block_size
        if not _range_fully_allocated(
            data_ranges,
            metadata_offset,
            metadata_offset + metadata_length * block_size,
        ):
            raise AssertionError("Linux root filesystem metadata is not allocated")
    block_bitmap_data = _read(
        image,
        partition_offset + block_bitmap * block_size,
        block_size,
        "Linux root filesystem block bitmap is truncated",
    )
    inode_bitmap_data = _read(
        image,
        partition_offset + inode_bitmap * block_size,
        block_size,
        "Linux root filesystem inode bitmap is truncated",
    )
    if not (inode_bitmap_data[0] & (1 << 1)):
        raise AssertionError("Linux root inode is not marked allocated")
    inode_offset = partition_offset + inode_table * block_size + inode_size
    if inode_offset + inode_size > partition_offset + partition_size:
        raise AssertionError("Linux root inode is outside the root partition")
    inode = _read(image, inode_offset, inode_size, "Linux root inode is truncated")
    mode = struct.unpack_from("<H", inode, 0)[0]
    directory_size = struct.unpack_from("<I", inode, 4)[0]
    if mode & 0xF000 != 0x4000 or directory_size == 0:
        raise AssertionError("Linux root inode is not a usable directory")
    if struct.unpack_from("<I", inode, 32)[0] & EXT4_EXTENTS == 0:
        raise AssertionError("Linux root inode does not contain extents")
    directory_blocks = (directory_size + block_size - 1) // block_size

    extent = inode[40:100]
    magic, entries, maximum, depth = struct.unpack_from("<HHHH", extent, 0)
    if magic != 0xF30A or entries == 0 or entries > maximum or depth != 0:
        raise AssertionError("Linux root inode extent tree is invalid")
    extents = []
    for index in range(entries):
        offset = 12 + index * 12
        logical, length, start_high, start_low = struct.unpack_from(
            "<IHHI", extent, offset
        )
        length &= 0x7FFF
        physical = start_low | (start_high << 32)
        if length == 0 or physical + length > blocks:
            raise AssertionError("Linux root inode extent is outside the filesystem")
        if extents and logical < extents[-1][0] + extents[-1][1]:
            raise AssertionError("Linux root inode extents overlap")
        extents.append((logical, length, physical))
    if extents[0][0] != 0 or extents[-1][0] + extents[-1][1] < directory_blocks:
        raise AssertionError("Linux root inode extents do not cover its directory")

    checksum_required = (
        struct.unpack_from("<I", superblock, 100)[0] & EXT4_RO_COMPAT_METADATA_CSUM
    )
    inode_generation = struct.unpack_from("<I", inode, 100)[0]
    if incompat_features & EXT4_INCOMPAT_CSUM_SEED:
        checksum_seed = struct.unpack_from("<I", superblock, 624)[0]
    else:
        checksum_seed = _crc32c(0xFFFFFFFF, superblock[104:120])
    inode_bitmap_data = bytes(inode_bitmap_data)
    seen_names = set()
    logical_block = 0
    for logical, length, physical in extents:
        if logical != logical_block:
            raise AssertionError("Linux root directory extents contain a gap")
        if physical + length > blocks_per_group:
            raise AssertionError("Linux root directory extent leaves its allocation group")
        if any(
            not (block_bitmap_data[block // 8] & (1 << (block % 8)))
            for block in range(physical, physical + length)
        ):
            raise AssertionError("Linux root inode extent is not marked allocated")
        extent_offset = partition_offset + physical * block_size
        if not _range_fully_allocated(
            data_ranges,
            extent_offset,
            extent_offset + length * block_size,
        ):
            raise AssertionError("Linux root inode extent is not physically allocated")
        for block_index in range(length):
            directory_block = _read(
                image,
                extent_offset + block_index * block_size,
                block_size,
                "Linux root directory extent is truncated",
            )
            data_limit = block_size
            if checksum_required:
                tail = directory_block[-12:]
                tail_inode, tail_length, tail_name_length, tail_type = struct.unpack(
                    "<IHBB", tail[:8]
                )
                if (
                    tail_inode != 0
                    or tail_length != 12
                    or tail_name_length != 0
                    or tail_type != EXT4_DIR_CSUM
                    or struct.unpack_from("<I", tail, 8)[0] == 0
                    or struct.unpack_from("<I", tail, 8)[0]
                    != _directory_checksum(
                        checksum_seed,
                        2,
                        inode_generation,
                        directory_block,
                    )
                ):
                    raise AssertionError("Linux root directory checksum tail is invalid")
                data_limit -= 12
            cursor = 0
            while cursor < data_limit:
                if cursor + 8 > data_limit:
                    raise AssertionError("Linux root directory record is truncated")
                entry_inode, record_length, name_length, file_type = struct.unpack_from(
                    "<IHBB", directory_block, cursor
                )
                minimum_length = (8 + name_length + 3) & ~3
                if (
                    record_length < 8
                    or record_length % 4
                    or record_length < minimum_length
                    or cursor + record_length > data_limit
                ):
                    raise AssertionError("Linux root directory record length is invalid")
                name = directory_block[cursor + 8 : cursor + 8 + name_length]
                if entry_inode == 0:
                    if name_length != 0 or file_type != 0:
                        raise AssertionError("Linux root directory unused record is invalid")
                else:
                    if (
                        entry_inode > struct.unpack_from("<I", superblock, 0)[0]
                        or name_length == 0
                        or b"\0" in name
                        or b"/" in name
                        or file_type > 7
                        or name in seen_names
                    ):
                        raise AssertionError("Linux root directory entry is invalid")
                    seen_names.add(name)
                    if logical_block == 0 and cursor == 0 and (entry_inode, name) != (2, b"."):
                        raise AssertionError("Linux root directory lacks '.'")
                    if logical_block == 0 and cursor == 12 and (entry_inode, name) != (2, b".."):
                        raise AssertionError("Linux root directory lacks '..'")
                cursor += record_length
            if cursor != data_limit:
                raise AssertionError("Linux root directory records leave a gap")
            logical_block += 1


def _validate(image, size, physical_ranges=None):
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
    _validate_ext4_root(image, roots[0][0], roots[0][1], physical_ranges)


def validate_bytes(data, physical_ranges=None):
    _validate(io.BytesIO(data), len(data), physical_ranges)


def validate(path):
    stat = path.stat()
    with path.open("rb") as image:
        _validate(image, stat.st_size)
    print(
        "validated raw image: protective MBR, CRC-valid GPT, Linux root ext4 "
        "extent, allocated content (%d bytes)" % stat.st_size
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: raw_image_validator.py IMAGE")
    validate(image_path(sys.argv[1]))
