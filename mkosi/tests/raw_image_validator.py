import os
import pathlib
import struct
import sys
import uuid


SECTOR_SIZE = 512
LINUX_ROOT_X86_64 = uuid.UUID("4f68bce3-e8cd-4db1-96e7-fbcaf984b709").bytes_le


def image_path(argument):
    path = pathlib.Path(argument)
    if path.is_absolute():
        return path
    return pathlib.Path(os.environ["TEST_SRCDIR"]) / os.environ["TEST_WORKSPACE"] / path


def validate(path):
    stat = path.stat()
    if stat.st_size == 0 or stat.st_blocks * 512 < SECTOR_SIZE:
        raise AssertionError("raw image is empty or has no allocated blocks: %s" % path)

    with path.open("rb") as image:
        image.seek(SECTOR_SIZE)
        header = image.read(92)
        if len(header) < 92 or header[:8] != b"EFI PART":
            raise AssertionError("raw image is missing the GPT signature: %s" % path)
        header_size = struct.unpack_from("<I", header, 12)[0]
        if header_size < 92 or header_size > SECTOR_SIZE:
            raise AssertionError("raw image has an invalid GPT header size")
        entries_lba = struct.unpack_from("<Q", header, 72)[0]
        entry_count = struct.unpack_from("<I", header, 80)[0]
        entry_size = struct.unpack_from("<I", header, 84)[0]
        if entry_count == 0 or entry_size < 128 or entry_size > 4096:
            raise AssertionError("raw image has an invalid GPT partition table")
        entries_end = (entries_lba * SECTOR_SIZE) + (entry_count * entry_size)
        if entries_end > stat.st_size:
            raise AssertionError("raw image GPT partition table exceeds the file")

        roots = []
        image.seek(entries_lba * SECTOR_SIZE)
        for _ in range(entry_count):
            entry = image.read(entry_size)
            if len(entry) < entry_size:
                raise AssertionError("raw image GPT partition table is truncated")
            if entry[:16] == b"\0" * 16:
                continue
            start_lba, end_lba = struct.unpack_from("<QQ", entry, 32)
            if end_lba <= start_lba or (end_lba + 1) * SECTOR_SIZE > stat.st_size:
                raise AssertionError("raw image contains an invalid GPT partition range")
            if entry[:16] == LINUX_ROOT_X86_64:
                roots.append((start_lba, end_lba))

        if not roots:
            raise AssertionError("raw image has no Linux x86-64 root partition")

        start_lba, end_lba = roots[0]
        partition_size = (end_lba - start_lba + 1) * SECTOR_SIZE
        if partition_size < 1024 * 1024:
            raise AssertionError("Linux root partition is unexpectedly small")
        image.seek(start_lba * SECTOR_SIZE)
        content = image.read(min(partition_size, 4 * 1024 * 1024))
        if content.count(b"\0") == len(content) or sum(byte != 0 for byte in content) < 4096:
            raise AssertionError("Linux root partition has no nontrivial allocated content")

    print(
        "validated raw image: GPT, Linux root partition, allocated content (%d bytes)"
        % stat.st_size
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: raw_image_validator.py IMAGE")
    validate(image_path(sys.argv[1]))
