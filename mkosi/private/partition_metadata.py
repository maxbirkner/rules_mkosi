#!/usr/bin/python3
"""Validate both GPT copies and emit normalized partition metadata."""

import argparse
import hashlib
import json
import os
import runpy
import struct
import uuid
import zlib
from pathlib import Path

_load_sibling = runpy.run_path(str(Path(__file__).with_name("sibling_loader.py")))["load_sibling"]
gpt = _load_sibling(__file__, "gpt_partitions")

ALIGNMENT = 1024 * 1024
_HEADER_MIN = 92
_MAX_ARRAY_BYTES = 64 * 1024 * 1024
_MAX_ENTRIES = 1024 * 1024
_HASH_CHUNK_BYTES = 1024 * 1024


def _read_exact(image, offset, size, image_size, description):
    if offset < 0 or size < 0 or offset > image_size or size > image_size - offset:
        raise ValueError("{} is outside the image".format(description))
    image.seek(offset)
    value = image.read(size)
    if len(value) != size:
        raise ValueError("{} is truncated".format(description))
    return value


def _require(checks):
    """Raises ValueError with the message of the first failed (passed, message) check."""
    for passed, message in checks:
        if not passed:
            raise ValueError(message)


def _check_header_bytes(raw, sector_size, description):
    """Validates the signature, revision, size, CRC and reserved bytes of one GPT header sector."""
    revision, header_size, header_crc = struct.unpack_from("<III", raw, 8)
    checked = bytearray(raw[:header_size])
    checked[16:20] = b"\0" * 4
    _require(
        (
            (raw[:8] == b"EFI PART", "{} has an invalid signature".format(description)),
            (revision == 0x00010000, "{} has unsupported revision".format(description)),
            (_HEADER_MIN <= header_size <= sector_size, "{} has invalid header size".format(description)),
            (zlib.crc32(checked) == header_crc, "{} header CRC mismatch".format(description)),
            (raw[20:24] == b"\0" * 4, "{} has nonzero reserved header bytes".format(description)),
        )
    )
    return header_size


def _check_header_geometry(fields, lba, expected_backup, last_lba, description):
    """Validates header locations, the usable range and partition-array bounds before the array is read."""
    _require(
        (
            (
                fields["current"] == lba and fields["backup"] == expected_backup,
                "{} has invalid reciprocal header LBAs".format(description),
            ),
            (lba in (1, last_lba), "{} is not at an expected disk location".format(description)),
            (
                fields["first_usable"] <= fields["last_usable"] < last_lba,
                "{} has invalid usable range".format(description),
            ),
            (0 < fields["count"] <= _MAX_ENTRIES, "{} has hostile partition count".format(description)),
            (
                128 <= fields["entry_size"] <= 4096 and not fields["entry_size"] % 8,
                "{} has hostile partition entry size".format(description),
            ),
            (
                fields["count"] * fields["entry_size"] <= _MAX_ARRAY_BYTES,
                "{} partition array is oversized".format(description),
            ),
        )
    )


def _check_array_location(fields, lba, last_lba, array_last_lba, description):
    entries_lba = fields["entries_lba"]
    _require(
        (
            (
                entries_lba >= 2 and array_last_lba < last_lba,
                "{} has invalid partition-array location".format(description),
            ),
            (
                lba != 1 or array_last_lba < fields["first_usable"],
                "primary GPT partition array is not before the usable range",
            ),
            (
                lba != last_lba or entries_lba > fields["last_usable"],
                "backup GPT partition array is not after the usable range",
            ),
        )
    )


def _header_fields(raw):
    current, backup, first_usable, last_usable = struct.unpack_from("<QQQQ", raw, 24)
    entries_lba, count, entry_size, array_crc = struct.unpack_from("<QIII", raw, 72)
    return {
        "array_crc": array_crc,
        "backup": backup,
        "count": count,
        "current": current,
        "entries_lba": entries_lba,
        "entry_size": entry_size,
        "first_usable": first_usable,
        "last_usable": last_usable,
    }


def _header(image, image_size, sector_size, lba, expected_backup, description):
    raw = _read_exact(image, lba * sector_size, sector_size, image_size, description)
    header_size = _check_header_bytes(raw, sector_size, description)
    fields = _header_fields(raw)
    last_lba = image_size // sector_size - 1
    _check_header_geometry(fields, lba, expected_backup, last_lba, description)
    array_size = fields["count"] * fields["entry_size"]
    array_offset = fields["entries_lba"] * sector_size
    array = _read_exact(image, array_offset, array_size, image_size, description + " partition array")
    array_last_lba = fields["entries_lba"] + (array_size + sector_size - 1) // sector_size - 1
    _check_array_location(fields, lba, last_lba, array_last_lba, description)
    if zlib.crc32(array) != fields["array_crc"]:
        raise ValueError("{} partition-array CRC mismatch".format(description))
    return {
        "array": array,
        "array_offset": array_offset,
        "count": fields["count"],
        "disk_guid": raw[56:72],
        "entry_size": fields["entry_size"],
        "entries_lba": fields["entries_lba"],
        "first_usable": fields["first_usable"],
        "header_offset": lba * sector_size,
        "header_size": header_size,
        "last_usable": fields["last_usable"],
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


def _validate_ab_slots(partitions, slot_label):
    """Requires one populated, versioned slot; other root/verity slots must be inactive."""
    expected = {gpt.ROOT_X86_64: slot_label, gpt.ROOT_X86_64_VERITY: slot_label + "_verity"}
    for type_guid, label in expected.items():
        candidates = [entry for entry in partitions if entry["type_guid"] == type_guid]
        populated = [entry for entry in candidates if entry["label"] != gpt.EMPTY_SLOT_LABEL]
        if len(populated) != 1 or populated[0]["label"] != label:
            raise ValueError(
                "A/B image requires exactly one populated {} partition labelled {!r}; found {!r}".format(
                    "root" if type_guid == gpt.ROOT_X86_64 else "verity",
                    label,
                    sorted(entry["label"] for entry in candidates),
                )
            )
        inactive = [entry for entry in candidates if entry["label"] == gpt.EMPTY_SLOT_LABEL]
        if any(entry["size_bytes"] < populated[0]["size_bytes"] for entry in inactive):
            raise ValueError(
                "inactive {} slots must be at least as large as the populated slot".format(
                    "root" if type_guid == gpt.ROOT_X86_64 else "verity"
                )
            )


def _check_entry_range(number, first, last, primary, previous):
    """Validates one partition extent against the usable range and the previous populated entry."""
    if first > last:
        raise ValueError("partition {} has an invalid range".format(number))
    if first < primary["first_usable"] or last > primary["last_usable"]:
        raise ValueError("partition {} is outside the usable range".format(number))
    if previous is None:
        return
    previous_first, previous_last, previous_number = previous
    if first < previous_first:
        raise ValueError("partition {} is out of order".format(number))
    if first <= previous_last:
        raise ValueError("partition {} overlaps partition {}".format(number, previous_number))


def _project_entry(entry, number, first, last, sector_size):
    start_bytes = first * sector_size
    if start_bytes % ALIGNMENT:
        raise ValueError("partition {} is not 1 MiB aligned".format(number))
    try:
        label = entry[56:128].decode("utf-16-le").split("\0", 1)[0]
    except UnicodeDecodeError as error:
        raise ValueError("partition {} has an invalid label".format(number)) from error
    return {
        "label": label,
        "number": number,
        "size_bytes": (last - first + 1) * sector_size,
        "start_bytes": start_bytes,
        "type_guid": str(uuid.UUID(bytes_le=entry[:16])),
    }


def _validate_roots(partitions, slot_label):
    if slot_label is not None:
        _validate_ab_slots(partitions, slot_label)
        return
    roots = [entry for entry in partitions if entry["type_guid"] == gpt.ROOT_X86_64]
    if len(roots) != 1:
        raise ValueError("exactly one Linux x86-64 root partition is required")
    if roots[0]["label"] != "root-x86-64":
        raise ValueError("Linux x86-64 root partition label must be root-x86-64")


def _validate_firmware(partitions, firmware):
    if firmware == "uefi":
        return
    if firmware != "bios":
        raise ValueError("firmware must be either uefi or bios")
    bios_boot = [entry for entry in partitions if entry["type_guid"] == gpt.BIOS_BOOT]
    if len(bios_boot) != 1:
        raise ValueError("BIOS firmware requires exactly one GPT BIOS boot partition")
    if bios_boot[0]["size_bytes"] < ALIGNMENT:
        raise ValueError("GPT BIOS boot partition must be at least 1 MiB")


def project_image(path, firmware="uefi", slot_label=None):
    _, sector_size, primary, _ = _validated_gpt(path)
    entry_size = primary["entry_size"]
    partitions = []
    previous = None
    # One linear scan over the entry array; hostile tables can declare up to _MAX_ENTRIES entries.
    for slot in range(primary["count"]):
        entry = primary["array"][slot * entry_size : (slot + 1) * entry_size]
        if entry[:16] == b"\0" * 16:
            continue
        number = slot + 1
        first, last = struct.unpack_from("<QQ", entry, 32)
        _check_entry_range(number, first, last, primary, previous)
        previous = (first, last, number)
        partitions.append(_project_entry(entry, number, first, last, sector_size))
        if slot_label is not None:
            partitions[-1]["uuid"] = str(uuid.UUID(bytes_le=entry[16:32]))
    _validate_roots(partitions, slot_label)
    _validate_firmware(partitions, firmware)
    return {
        "firmware": firmware,
        "format_version": "mkosi-partition-metadata-v1",
        "partitions": partitions,
        "sector_size": sector_size,
    }


def _canonical_header(header, array_crc):
    result = bytearray(header["raw_header"])
    result[16:20] = b"\0" * 4
    result[56:72] = b"\0" * 16
    struct.pack_into("<I", result, 88, array_crc)
    struct.pack_into("<I", result, 16, zlib.crc32(result[: header["header_size"]]))
    return bytes(result)


def _hash_bytes(image, digest, size):
    """Feeds the next size bytes of image into digest in bounded chunks."""
    while size:
        chunk = image.read(min(_HASH_CHUNK_BYTES, size))
        if not chunk:
            raise ValueError("raw image is truncated while hashing")
        digest.update(chunk)
        size -= len(chunk)


def _hash_with_patches(path, image_size, patches):
    digest = hashlib.sha256()
    cursor = 0
    with open(path, "rb") as image:
        for offset, replacement in sorted(patches):
            if offset < cursor:
                raise ValueError("canonical GPT patches overlap")
            _hash_bytes(image, digest, offset - cursor)
            image.seek(len(replacement), os.SEEK_CUR)
            digest.update(replacement)
            cursor = offset + len(replacement)
        _hash_bytes(image, digest, image_size - cursor)
    return digest.hexdigest()


def canonical_image_sha256(path):
    """Hashes every image byte after normalizing only GPT identity and CRC fields."""
    project_image(path)
    image_size, _, primary, backup = _validated_gpt(path)
    array = bytearray(primary["array"])
    for slot in range(primary["count"]):
        offset = slot * primary["entry_size"]
        array[offset + 16 : offset + 32] = b"\0" * 16
    array = bytes(array)
    array_crc = zlib.crc32(array)
    patches = [
        (primary["header_offset"], _canonical_header(primary, array_crc)),
        (primary["array_offset"], array),
        (backup["array_offset"], array),
        (backup["header_offset"], _canonical_header(backup, array_crc)),
    ]
    return _hash_with_patches(path, image_size, patches)


def _image_version_from_file(path, slot_label_image_id):
    """Returns the validated version in path using the sibling image_version.py helper.

    The helper is loaded only here, so modules that import this one for GPT projection do not need it.
    """
    image_version = _load_sibling(__file__, "image_version")
    try:
        return image_version.read_image_version(path, slot_label_image_id)
    except (OSError, ValueError) as error:
        raise SystemExit("IMAGE_VERSION_INVALID: {}".format(error)) from None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--firmware", choices=("uefi", "bios"), default="uefi")
    slot = parser.add_mutually_exclusive_group()
    slot.add_argument("--slot-label")
    slot.add_argument(
        "--slot-label-image-id",
        help="image id of the populated slot label '<image id>_<version>', with the --image-version-file version",
    )
    parser.add_argument("--image-version-file")
    args = parser.parse_args()
    if (args.slot_label_image_id is None) != (args.image_version_file is None):
        parser.error("--slot-label-image-id and --image-version-file must be given together")
    slot_label = args.slot_label
    if args.slot_label_image_id is not None:
        image_version = _image_version_from_file(args.image_version_file, args.slot_label_image_id)
        slot_label = "{}_{}".format(args.slot_label_image_id, image_version)
    metadata = project_image(args.image, args.firmware, slot_label)
    Path(args.output).write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
