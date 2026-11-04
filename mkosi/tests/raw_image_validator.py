import dataclasses
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
    except (AttributeError, io.UnsupportedOperation) as error:
        raise AssertionError("physical data extents are unavailable for this image") from error
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
                raise AssertionError("filesystem does not report physical data extents") from error
            raise
        if data >= end:
            break
        try:
            hole = os.lseek(fd, data, seek_hole)
        except OSError as error:
            if error.errno in (errno.EINVAL, errno.ENOTSUP):
                raise AssertionError("filesystem does not report physical data extents") from error
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


def _check_header_integrity(raw, lba):
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


def _check_header_geometry(header, lba, total_sectors):
    if header["current_lba"] != lba or header["backup_lba"] >= total_sectors:
        raise AssertionError("GPT header LBA relationship is invalid")
    first_usable = header["first_usable"]
    if first_usable < 2 or first_usable > header["last_usable"] or header["last_usable"] >= total_sectors:
        raise AssertionError("GPT usable LBA range is invalid")
    if header["entry_count"] == 0 or header["entry_size"] < GPT_ENTRY_SIZE or header["entry_size"] % 8:
        raise AssertionError("GPT partition entry geometry is invalid")
    if header["array_lba"] < 2 or header["array_lba"] + header["array_sectors"] > total_sectors:
        raise AssertionError("GPT partition array is outside the image")


def _parse_header(image, lba, total_sectors):
    raw = _read(image, lba * SECTOR_SIZE, SECTOR_SIZE, "GPT header is truncated")
    _check_header_integrity(raw, lba)
    current_lba, backup_lba, first_usable, last_usable = struct.unpack_from("<QQQQ", raw, 24)
    array_lba, entry_count, entry_size, array_crc = struct.unpack_from("<QIII", raw, 72)
    array_size = entry_count * entry_size
    header = {
        "current_lba": current_lba,
        "backup_lba": backup_lba,
        "first_usable": first_usable,
        "last_usable": last_usable,
        "disk_guid": raw[56:72],
        "array_lba": array_lba,
        "array_sectors": (array_size + SECTOR_SIZE - 1) // SECTOR_SIZE,
        "entry_count": entry_count,
        "entry_size": entry_size,
    }
    _check_header_geometry(header, lba, total_sectors)
    array = _read(image, array_lba * SECTOR_SIZE, array_size, "GPT partition array is truncated")
    if zlib.crc32(array) & 0xFFFFFFFF != array_crc:
        raise AssertionError("GPT partition array CRC is invalid")
    header["array"] = array
    return header


def _u16(data, offset):
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


@dataclasses.dataclass(frozen=True)
class _Ext4:
    """Validated ext4 superblock geometry of the Linux root partition."""

    partition_offset: int
    partition_size: int
    superblock: bytes
    block_size: int
    blocks: int
    blocks_per_group: int
    inodes_per_group: int
    incompat_features: int
    inode_size: int
    descriptor_size: int

    def block_offset(self, block):
        return self.partition_offset + block * self.block_size


def _read_ext4_superblock(image, partition_offset):
    superblock = _read(
        image,
        partition_offset + 1024,
        1024,
        "Linux root filesystem superblock is truncated",
    )
    if superblock[56:58] != EXT4_MAGIC:
        raise AssertionError("Linux root partition is not a recognizable ext4 filesystem")
    if _u32(superblock, 76) != 1:
        raise AssertionError("Linux root filesystem revision is unsupported")
    return superblock


def _ext4_block_size(superblock):
    block_size_log = _u32(superblock, 24)
    if block_size_log > 6:
        raise AssertionError("Linux root filesystem block size is invalid")
    block_size = 1024 << block_size_log
    if block_size > 65536:
        raise AssertionError("Linux root filesystem block size is unsupported")
    return block_size


def _read_ext4_geometry(image, partition_offset, partition_size):
    superblock = _read_ext4_superblock(image, partition_offset)
    block_size = _ext4_block_size(superblock)
    blocks = _u32(superblock, 4) | _u32(superblock, 336) << 32
    if blocks == 0 or blocks * block_size > partition_size:
        raise AssertionError("Linux root filesystem geometry exceeds its partition")
    blocks_per_group = _u32(superblock, 32)
    inodes_per_group = _u32(superblock, 40)
    if blocks_per_group == 0 or inodes_per_group == 0:
        raise AssertionError("Linux root filesystem has no block groups or inodes")
    incompat_features = _u32(superblock, 96)
    if incompat_features & EXT4_INCOMPAT_EXTENTS == 0:
        raise AssertionError("Linux root filesystem does not advertise extents")
    inode_size = _u16(superblock, 88)
    descriptor_size = _u16(superblock, 254) or 32
    if inode_size < 128 or inode_size > block_size or descriptor_size not in (32, 64):
        raise AssertionError("Linux root filesystem inode geometry is invalid")
    if incompat_features & EXT4_INCOMPAT_64BIT and descriptor_size != 64:
        raise AssertionError("Linux root filesystem descriptor geometry is invalid")
    return _Ext4(
        partition_offset,
        partition_size,
        superblock,
        block_size,
        blocks,
        blocks_per_group,
        inodes_per_group,
        incompat_features,
        inode_size,
        descriptor_size,
    )


def _read_first_group_metadata(image, fs):
    """Returns the (start, length) block ranges of group 0's block bitmap, inode bitmap, and inode table."""
    descriptor_block = 2 if fs.block_size == 1024 else 1
    descriptor = _read(
        image,
        fs.block_offset(descriptor_block),
        fs.descriptor_size,
        "Linux root filesystem group descriptor is truncated",
    )
    block_bitmap = _u32(descriptor, 0)
    inode_bitmap = _u32(descriptor, 4)
    inode_table = _u32(descriptor, 8)
    if fs.descriptor_size == 64:
        block_bitmap |= _u32(descriptor, 32) << 32
        inode_bitmap |= _u32(descriptor, 36) << 32
        inode_table |= _u32(descriptor, 40) << 32
    inode_table_blocks = (fs.inodes_per_group * fs.inode_size + fs.block_size - 1) // fs.block_size
    return [(block_bitmap, 1), (inode_bitmap, 1), (inode_table, inode_table_blocks)]


def _require_disjoint_group_metadata(metadata_blocks, group_end):
    for metadata_index, (metadata_start, metadata_length) in enumerate(metadata_blocks):
        if (
            metadata_start == 0
            or metadata_start + metadata_length > group_end
            or any(
                metadata_start < other_start + other_length and other_start < metadata_start + metadata_length
                for other_index, (other_start, other_length) in enumerate(metadata_blocks)
                if other_index != metadata_index
            )
        ):
            raise AssertionError("Linux root filesystem allocation metadata overlaps")


def _require_allocated_metadata(fs, metadata_blocks, data_ranges):
    for metadata_start, metadata_length in metadata_blocks:
        metadata_offset = fs.block_offset(metadata_start)
        if not _range_fully_allocated(
            data_ranges,
            metadata_offset,
            metadata_offset + metadata_length * fs.block_size,
        ):
            raise AssertionError("Linux root filesystem metadata is not allocated")


def _read_bitmaps(image, fs, block_bitmap, inode_bitmap):
    """Returns group 0's block bitmap after requiring that its inode bitmap allocates the root inode."""
    block_bitmap_data = _read(
        image,
        fs.block_offset(block_bitmap),
        fs.block_size,
        "Linux root filesystem block bitmap is truncated",
    )
    inode_bitmap_data = _read(
        image,
        fs.block_offset(inode_bitmap),
        fs.block_size,
        "Linux root filesystem inode bitmap is truncated",
    )
    if not (inode_bitmap_data[0] & (1 << 1)):
        raise AssertionError("Linux root inode is not marked allocated")
    return block_bitmap_data


def _read_root_inode(image, fs, inode_table):
    inode_offset = fs.block_offset(inode_table) + fs.inode_size
    if inode_offset + fs.inode_size > fs.partition_offset + fs.partition_size:
        raise AssertionError("Linux root inode is outside the root partition")
    inode = _read(image, inode_offset, fs.inode_size, "Linux root inode is truncated")
    if _u16(inode, 0) & 0xF000 != 0x4000 or _u32(inode, 4) == 0:
        raise AssertionError("Linux root inode is not a usable directory")
    if _u32(inode, 32) & EXT4_EXTENTS == 0:
        raise AssertionError("Linux root inode does not contain extents")
    return inode


def _root_directory_extents(fs, inode):
    """Returns the root directory's (logical, length, physical) extents after checking that they cover it."""
    directory_blocks = (_u32(inode, 4) + fs.block_size - 1) // fs.block_size
    extent = inode[40:100]
    magic, entries, maximum, depth = struct.unpack_from("<HHHH", extent, 0)
    if magic != 0xF30A or entries == 0 or entries > maximum or depth != 0:
        raise AssertionError("Linux root inode extent tree is invalid")
    extents = []
    for index in range(entries):
        logical, length, start_high, start_low = struct.unpack_from("<IHHI", extent, 12 + index * 12)
        length &= 0x7FFF
        physical = start_low | (start_high << 32)
        if length == 0 or physical + length > fs.blocks:
            raise AssertionError("Linux root inode extent is outside the filesystem")
        if extents and logical < extents[-1][0] + extents[-1][1]:
            raise AssertionError("Linux root inode extents overlap")
        extents.append((logical, length, physical))
    if extents[0][0] != 0 or extents[-1][0] + extents[-1][1] < directory_blocks:
        raise AssertionError("Linux root inode extents do not cover its directory")
    return extents


def _require_allocated_extent(fs, physical, length, block_bitmap_data, data_ranges):
    if physical + length > fs.blocks_per_group:
        raise AssertionError("Linux root directory extent leaves its allocation group")
    if any(not (block_bitmap_data[block // 8] & (1 << (block % 8))) for block in range(physical, physical + length)):
        raise AssertionError("Linux root inode extent is not marked allocated")
    extent_offset = fs.block_offset(physical)
    if not _range_fully_allocated(data_ranges, extent_offset, extent_offset + length * fs.block_size):
        raise AssertionError("Linux root inode extent is not physically allocated")


def _directory_checksum_key(fs, inode):
    """Returns the (seed, generation) pair for root directory block checksums, or None if they are disabled."""
    if _u32(fs.superblock, 100) & EXT4_RO_COMPAT_METADATA_CSUM == 0:
        return None
    if fs.incompat_features & EXT4_INCOMPAT_CSUM_SEED:
        seed = _u32(fs.superblock, 624)
    else:
        seed = _crc32c(0xFFFFFFFF, fs.superblock[104:120])
    return seed, _u32(inode, 100)


def _directory_data_limit(directory_block, checksum_key):
    """Returns the size of the record area in directory_block after validating its checksum tail."""
    if checksum_key is None:
        return len(directory_block)
    tail = directory_block[-12:]
    tail_inode, tail_length, tail_name_length, tail_type = struct.unpack("<IHBB", tail[:8])
    stored_checksum = _u32(tail, 8)
    if (
        tail_inode != 0
        or tail_length != 12
        or tail_name_length != 0
        or tail_type != EXT4_DIR_CSUM
        or stored_checksum == 0
        or stored_checksum != _directory_checksum(checksum_key[0], 2, checksum_key[1], directory_block)
    ):
        raise AssertionError("Linux root directory checksum tail is invalid")
    return len(directory_block) - 12


def _validate_directory_entry(fs, entry_inode, name, file_type, seen_names, position):
    """Validates one used record; position is the (logical block, byte offset) of the record."""
    if (
        entry_inode > _u32(fs.superblock, 0)
        or len(name) == 0
        or b"\0" in name
        or b"/" in name
        or file_type > 7
        or name in seen_names
    ):
        raise AssertionError("Linux root directory entry is invalid")
    seen_names.add(name)
    if position == (0, 0) and (entry_inode, name) != (2, b"."):
        raise AssertionError("Linux root directory lacks '.'")
    if position == (0, 12) and (entry_inode, name) != (2, b".."):
        raise AssertionError("Linux root directory lacks '..'")


def _validate_directory_records(fs, directory_block, data_limit, logical_block, seen_names):
    cursor = 0
    while cursor < data_limit:
        if cursor + 8 > data_limit:
            raise AssertionError("Linux root directory record is truncated")
        entry_inode, record_length, name_length, file_type = struct.unpack_from("<IHBB", directory_block, cursor)
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
            _validate_directory_entry(fs, entry_inode, name, file_type, seen_names, (logical_block, cursor))
        cursor += record_length
    if cursor != data_limit:
        raise AssertionError("Linux root directory records leave a gap")


def _validate_root_directory(image, fs, inode, block_bitmap_data, data_ranges):
    checksum_key = _directory_checksum_key(fs, inode)
    seen_names = set()
    logical_block = 0
    for logical, length, physical in _root_directory_extents(fs, inode):
        if logical != logical_block:
            raise AssertionError("Linux root directory extents contain a gap")
        _require_allocated_extent(fs, physical, length, block_bitmap_data, data_ranges)
        for block_index in range(length):
            directory_block = _read(
                image,
                fs.block_offset(physical + block_index),
                fs.block_size,
                "Linux root directory extent is truncated",
            )
            data_limit = _directory_data_limit(directory_block, checksum_key)
            _validate_directory_records(fs, directory_block, data_limit, logical_block, seen_names)
            logical_block += 1


def _validate_ext4_root(image, partition_start, partition_end, physical_ranges=None):
    partition_offset = partition_start * SECTOR_SIZE
    partition_size = (partition_end - partition_start + 1) * SECTOR_SIZE
    if partition_size < 1024 * 1024:
        raise AssertionError("Linux root partition is unexpectedly small")
    fs = _read_ext4_geometry(image, partition_offset, partition_size)
    metadata_blocks = _read_first_group_metadata(image, fs)
    _require_disjoint_group_metadata(metadata_blocks, min(fs.blocks, fs.blocks_per_group))
    data_ranges = physical_ranges or _physical_data_ranges(
        image,
        partition_offset,
        partition_offset + partition_size,
    )
    _require_allocated_metadata(fs, metadata_blocks, data_ranges)
    (block_bitmap, _), (inode_bitmap, _), (inode_table, _) = metadata_blocks
    block_bitmap_data = _read_bitmaps(image, fs, block_bitmap, inode_bitmap)
    inode = _read_root_inode(image, fs, inode_table)
    _validate_root_directory(image, fs, inode, block_bitmap_data, data_ranges)


def _total_sectors(size):
    if size == 0 or size % SECTOR_SIZE:
        raise AssertionError("raw image size is empty or not sector aligned")
    total_sectors = size // SECTOR_SIZE
    if total_sectors < 34:
        raise AssertionError("raw image is too small for GPT metadata")
    return total_sectors


def _validate_protective_mbr(image, total_sectors):
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


def _read_gpt(image, total_sectors):
    """Returns the primary GPT header after requiring that the backup header mirrors it."""
    primary = _parse_header(image, 1, total_sectors)
    backup = _parse_header(image, total_sectors - 1, total_sectors)
    if primary["backup_lba"] != backup["current_lba"] or backup["backup_lba"] != 1:
        raise AssertionError("primary and backup GPT headers disagree")
    if primary["disk_guid"] == b"\0" * 16 or primary["disk_guid"] != backup["disk_guid"]:
        raise AssertionError("primary and backup GPT disk GUIDs disagree")
    if any(primary[key] != backup[key] for key in ("first_usable", "last_usable", "entry_count", "entry_size")):
        raise AssertionError("primary and backup GPT geometry disagrees")
    if primary["array"] != backup["array"]:
        raise AssertionError("primary and backup GPT partition arrays differ")
    if primary["array_lba"] + primary["array_sectors"] > primary["first_usable"]:
        raise AssertionError("primary GPT metadata overlaps usable LBAs")
    if backup["array_lba"] <= backup["last_usable"]:
        raise AssertionError("backup GPT metadata overlaps usable LBAs")
    if backup["array_lba"] + backup["array_sectors"] > backup["current_lba"]:
        raise AssertionError("backup GPT partition array overlaps its header")
    return primary


def _gpt_partitions(header):
    """Returns the (start, end, type GUID) of every used, disjoint GPT partition entry."""
    partitions = []
    partition_guids = set()
    entry_size = header["entry_size"]
    for index in range(header["entry_count"]):
        entry = header["array"][index * entry_size : (index + 1) * entry_size]
        if entry[:16] == b"\0" * 16:
            continue
        if entry[16:32] == b"\0" * 16 or entry[16:32] in partition_guids:
            raise AssertionError("GPT partition GUIDs are missing or duplicated")
        partition_guids.add(entry[16:32])
        start, end = struct.unpack_from("<QQ", entry, 32)
        if start < header["first_usable"] or end > header["last_usable"] or end < start:
            raise AssertionError("GPT partition %d has an invalid usable range" % index)
        partitions.append((start, end, entry[:16]))
    for index, (start, end, _) in enumerate(partitions):
        for prior_start, prior_end, _ in partitions[:index]:
            if prior_start <= end and start <= prior_end:
                raise AssertionError("GPT partitions overlap")
    return partitions


def _validate(image, size, physical_ranges=None):
    total_sectors = _total_sectors(size)
    _validate_protective_mbr(image, total_sectors)
    partitions = _gpt_partitions(_read_gpt(image, total_sectors))
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


def main():
    """Validates the image named by the only command-line argument; exits with a usage message otherwise."""
    if len(sys.argv) != 2:
        raise SystemExit("usage: %s IMAGE" % os.path.basename(sys.argv[0]))
    validate(image_path(sys.argv[1]))


if __name__ == "__main__":
    main()
