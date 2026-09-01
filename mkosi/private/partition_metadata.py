#!/usr/bin/python3
"""Validate both GPT copies and emit normalized partition metadata."""

import argparse
import hashlib
import json
import os
import struct
import uuid
import zlib
from pathlib import Path

ROOT_X86_64 = "4f68bce3-e8cd-4db1-96e7-fbcaf984b709"
ALIGNMENT = 1024 * 1024
_HEADER_MIN = 92
_MAX_ARRAY_BYTES = 64 * 1024 * 1024
_MAX_ENTRIES = 1024 * 1024


def _read_exact(image, offset, size, image_size, description):
    if offset < 0 or size < 0 or offset > image_size or size > image_size - offset:
        raise ValueError("{} is outside the image".format(description))
    image.seek(offset)
    value = image.read(size)
    if len(value) != size:
        raise ValueError("{} is truncated".format(description))
    return value


def _header(image, image_size, sector_size, lba, expected_backup, description):
    raw = _read_exact(
        image, lba * sector_size, sector_size, image_size, description
    )
    if raw[:8] != b"EFI PART":
        raise ValueError("{} has an invalid signature".format(description))
    revision, header_size, header_crc = struct.unpack_from("<III", raw, 8)
    if revision != 0x00010000:
        raise ValueError("{} has unsupported revision".format(description))
    if header_size < _HEADER_MIN or header_size > sector_size:
        raise ValueError("{} has invalid header size".format(description))
    checked = bytearray(raw[:header_size])
    checked[16:20] = b"\0" * 4
    if zlib.crc32(checked) != header_crc:
        raise ValueError("{} header CRC mismatch".format(description))
    if raw[20:24] != b"\0" * 4:
        raise ValueError("{} has nonzero reserved header bytes".format(description))
    current, backup, first_usable, last_usable = struct.unpack_from("<QQQQ", raw, 24)
    entries_lba, count, entry_size, array_crc = struct.unpack_from("<QIII", raw, 72)
    last_lba = image_size // sector_size - 1
    if current != lba or backup != expected_backup:
        raise ValueError("{} has invalid reciprocal header LBAs".format(description))
    if lba not in (1, last_lba):
        raise ValueError("{} is not at an expected disk location".format(description))
    if first_usable > last_usable or last_usable >= last_lba:
        raise ValueError("{} has invalid usable range".format(description))
    if not count or count > _MAX_ENTRIES:
        raise ValueError("{} has hostile partition count".format(description))
    if entry_size < 128 or entry_size > 4096 or entry_size % 8:
        raise ValueError("{} has hostile partition entry size".format(description))
    array_size = count * entry_size
    if array_size > _MAX_ARRAY_BYTES:
        raise ValueError("{} partition array is oversized".format(description))
    array_offset = entries_lba * sector_size
    array = _read_exact(
        image, array_offset, array_size, image_size, description + " partition array"
    )
    array_last_lba = entries_lba + (array_size + sector_size - 1) // sector_size - 1
    if entries_lba < 2 or array_last_lba >= last_lba:
        raise ValueError("{} has invalid partition-array location".format(description))
    if lba == 1 and array_last_lba >= first_usable:
        raise ValueError("primary GPT partition array is not before the usable range")
    if lba == last_lba and entries_lba <= last_usable:
        raise ValueError("backup GPT partition array is not after the usable range")
    if zlib.crc32(array) != array_crc:
        raise ValueError("{} partition-array CRC mismatch".format(description))
    return {
        "array": array,
        "array_offset": array_offset,
        "count": count,
        "disk_guid": raw[56:72],
        "entry_size": entry_size,
        "entries_lba": entries_lba,
        "first_usable": first_usable,
        "header_offset": lba * sector_size,
        "header_size": header_size,
        "last_usable": last_usable,
        "raw_header": raw,
    }


def _sector_size(image, image_size):
    candidates = []
    for size in (512, 4096):
        if image_size % size == 0 and image_size >= size * 3:
            image.seek(size)
            if image.read(8) == b"EFI PART":
                candidates.append(size)
    if len(candidates) != 1:
        raise ValueError("image must contain one unambiguous 512- or 4096-byte GPT")
    return candidates[0]


def _validated_gpt(path):
    image_size = os.path.getsize(path)
    with open(path, "rb") as image:
        sector_size = _sector_size(image, image_size)
        last_lba = image_size // sector_size - 1
        primary = _header(image, image_size, sector_size, 1, last_lba, "primary GPT")
        backup = _header(image, image_size, sector_size, last_lba, 1, "backup GPT")
    for field in (
        "disk_guid",
        "first_usable",
        "last_usable",
        "count",
        "entry_size",
    ):
        if primary[field] != backup[field]:
            raise ValueError("GPT copies disagree on {}".format(field))
    if primary["array"] != backup["array"]:
        raise ValueError("GPT partition arrays disagree")
    return image_size, sector_size, primary, backup


def project_image(path):
    _, sector_size, primary, _ = _validated_gpt(path)

    partitions = []
    previous_first = None
    previous_last = None
    previous_number = None
    for slot in range(primary["count"]):
        entry = primary["array"][
            slot * primary["entry_size"] : (slot + 1) * primary["entry_size"]
        ]
        if entry[:16] == b"\0" * 16:
            continue
        first, last = struct.unpack_from("<QQ", entry, 32)
        number = slot + 1
        if first > last:
            raise ValueError("partition {} has an invalid range".format(number))
        if first < primary["first_usable"] or last > primary["last_usable"]:
            raise ValueError("partition {} is outside the usable range".format(number))
        if previous_first is not None and first < previous_first:
            raise ValueError("partition {} is out of order".format(number))
        if previous_last is not None and first <= previous_last:
            raise ValueError(
                "partition {} overlaps partition {}".format(number, previous_number)
            )
        previous_first = first
        previous_last = last
        previous_number = number
        start_bytes = first * sector_size
        if start_bytes % ALIGNMENT:
            raise ValueError("partition {} is not 1 MiB aligned".format(number))
        try:
            label = entry[56:128].decode("utf-16-le").split("\0", 1)[0]
        except UnicodeDecodeError as error:
            raise ValueError("partition {} has an invalid label".format(number)) from error
        partitions.append(
            {
                "label": label,
                "number": number,
                "size_bytes": (last - first + 1) * sector_size,
                "start_bytes": start_bytes,
                "type_guid": str(uuid.UUID(bytes_le=entry[:16])),
            }
        )
    roots = [entry for entry in partitions if entry["type_guid"] == ROOT_X86_64]
    if len(roots) != 1:
        raise ValueError("exactly one Linux x86-64 root partition is required")
    if roots[0]["label"] != "root-x86-64":
        raise ValueError("Linux x86-64 root partition label must be root-x86-64")
    return {
        "format_version": "mkosi-partition-metadata-v1",
        "partitions": partitions,
        "sector_size": sector_size,
    }


def _canonical_header(header, array_crc):
    result = bytearray(header["raw_header"])
    result[16:20] = b"\0" * 4
    result[56:72] = b"\0" * 16
    struct.pack_into("<I", result, 88, array_crc)
    struct.pack_into("<I", result, 16, zlib.crc32(result[:header["header_size"]]))
    return bytes(result)


def _hash_with_patches(path, image_size, patches):
    digest = hashlib.sha256()
    cursor = 0
    with open(path, "rb") as image:
        for offset, replacement in sorted(patches):
            if offset < cursor:
                raise ValueError("canonical GPT patches overlap")
            remaining = offset - cursor
            while remaining:
                chunk = image.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("raw image is truncated while hashing")
                digest.update(chunk)
                remaining -= len(chunk)
            image.seek(len(replacement), os.SEEK_CUR)
            digest.update(replacement)
            cursor = offset + len(replacement)
        remaining = image_size - cursor
        while remaining:
            chunk = image.read(min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("raw image is truncated while hashing")
            digest.update(chunk)
            remaining -= len(chunk)
    return digest.hexdigest()


def canonical_image_sha256(path):
    """Hashes every image byte after normalizing only GPT identity and CRC fields."""
    project_image(path)
    image_size, _, primary, backup = _validated_gpt(path)
    array = bytearray(primary["array"])
    for slot in range(primary["count"]):
        offset = slot * primary["entry_size"]
        array[offset + 16:offset + 32] = b"\0" * 16
    array = bytes(array)
    array_crc = zlib.crc32(array)
    patches = [
        (primary["header_offset"], _canonical_header(primary, array_crc)),
        (primary["array_offset"], array),
        (backup["array_offset"], array),
        (backup["header_offset"], _canonical_header(backup, array_crc)),
    ]
    return _hash_with_patches(path, image_size, patches)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    metadata = project_image(args.image)
    Path(args.output).write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
