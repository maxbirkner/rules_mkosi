#!/usr/bin/env python3
"""Reads the Secure Boot ESP manifest and other files from the EFI system partition of a raw disk image.

secure_boot_signed_image writes /loader/rules_mkosi-secure-boot.json onto the ESP, so that install tooling can check
an image before writing it. This module finds the ESP in the image's GPT and reads its FAT12, FAT16 or FAT32 file
system itself, without mounting the image or needing mtools. It uses only the Python standard library, so it also runs
as a plain script outside Bazel:

    python3 rules_mkosi_esp_manifest.py os.raw         # Prints the ESP manifest.
    python3 rules_mkosi_esp_manifest.py --list os.raw  # Lists the files on the ESP.
    python3 rules_mkosi_esp_manifest.py --extract EFI/BOOT/BOOTX64.EFI os.raw > BOOTX64.EFI

ESP paths are relative to the ESP's root and, as on FAT, case-insensitive. The exit status is 1 for an unreadable or
malformed image or manifest, 2 for invalid arguments, and 3 when the ESP lacks the requested file, for example the
manifest of an image that secure_boot_signed_image did not produce.
"""

import argparse
import json
import os
import struct
import sys
import uuid
import zlib
from typing import NamedTuple

ESP_MANIFEST_PATH = "loader/rules_mkosi-secure-boot.json"
ESP_MANIFEST_FORMAT = "mkosi-secure-boot-esp-manifest-v1"
ESP_TYPE_GUID = uuid.UUID("c12a7328-f81f-11d2-ba4b-00a0c93ec93b")

_GPT_SECTOR_SIZES = (512, 4096)
_MAX_GPT_ARRAY_BYTES = 4 << 20
_DIRECTORY_ENTRY = 32
# A FAT directory holds at most 65536 entries.
_MAX_DIRECTORY_BYTES = 65536 * _DIRECTORY_ENTRY
_ATTRIBUTE_VOLUME_LABEL = 0x08
_ATTRIBUTE_DIRECTORY = 0x10
_ATTRIBUTE_LONG_NAME = 0x0F
_LAST_LONG_NAME_SLOT = 0x40
# A long name has at most 255 UTF-16 code units, 13 per slot.
_MAX_LONG_NAME_SLOTS = 20
_DELETED = 0xE5
# Like Linux and mtools, tell FAT32 apart by its zero 16-bit FAT size and FAT12 from FAT16 by the cluster count.
_FAT12_CLUSTER_LIMIT = 4085
_END_OF_CHAIN = {12: 0xFF8, 16: 0xFFF8, 32: 0x0FFFFFF8}


class InvalidImageError(ValueError):
    """The disk image, its GPT, its ESP's FAT file system, or the ESP manifest is malformed or unsupported."""


class EspFileNotFoundError(FileNotFoundError):
    """The ESP has no regular file at the requested path."""


class Partition(NamedTuple):
    """A GPT partition's byte offset and size in the disk image, and the disk's logical sector size."""

    offset: int
    size: int
    sector_size: int


class EspFile(NamedTuple):
    """A regular file on the ESP: its path, with the stored long names and '/' separators, and its size in bytes."""

    path: str
    size: int


class _Entry(NamedTuple):
    name: str
    short_name: str
    attributes: int
    cluster: int
    size: int

    @property
    def is_directory(self):
        return bool(self.attributes & _ATTRIBUTE_DIRECTORY)


class _Geometry(NamedTuple):
    """Byte offsets and sizes of a FAT file system's regions, from its boot sector."""

    fat32: bool
    fat_offset: int
    fat_size: int
    root_offset: int
    root_size: int
    root_cluster: int
    data_offset: int
    cluster_size: int
    clusters: int


class _Image:
    """An open disk image file or block device that reads only within its size."""

    def __init__(self, file):
        self.file = file
        self.size = file.seek(0, os.SEEK_END)

    def read(self, offset, size, what):
        """Returns size bytes at offset; raises InvalidImageError unless they lie within the image."""
        if offset < 0 or size < 0 or offset + size > self.size:
            raise InvalidImageError("{} at byte {} lies beyond the end of the image".format(what, offset))
        self.file.seek(offset)
        data = self.file.read(size)
        if len(data) != size:
            raise InvalidImageError("{} at byte {} is truncated".format(what, offset))
        return data


def _gpt_sector_size(image):
    """Returns the logical sector size of a GPT disk with a protective MBR."""
    mbr = image.read(0, 512, "the protective MBR")
    types = [mbr[446 + 16 * index + 4] for index in range(4)]
    if mbr[510:512] != b"\x55\xaa" or 0xEE not in types:
        raise InvalidImageError("the image has no protective MBR, so it is not a GPT disk image")
    for sector_size in _GPT_SECTOR_SIZES:
        if image.size >= 2 * sector_size and image.read(sector_size, 8, "the GPT header") == b"EFI PART":
            return sector_size
    raise InvalidImageError("the image has no GPT header at byte 512 or 4096")


def _gpt_entries(image, sector_size):
    """Returns the partition entries of the primary GPT after checking the CRCs of its header and entry array."""
    header = image.read(sector_size, sector_size, "the GPT header")
    header_size, header_crc = struct.unpack_from("<II", header, 12)
    if not 92 <= header_size <= sector_size:
        raise InvalidImageError("the GPT header has an invalid size of {} bytes".format(header_size))
    if zlib.crc32(header[:16] + bytes(4) + header[20:header_size]) != header_crc:
        raise InvalidImageError("the GPT header's CRC does not match")
    array_lba, count, entry_size, array_crc = struct.unpack_from("<QIII", header, 72)
    if entry_size < 128 or entry_size % 8 or count * entry_size > _MAX_GPT_ARRAY_BYTES:
        raise InvalidImageError(
            "the GPT has an invalid partition array of {} {}-byte entries".format(count, entry_size)
        )
    array_offset = array_lba * sector_size
    if array_lba < 2 or array_offset + count * entry_size > image.size:
        raise InvalidImageError("the GPT partition array at LBA {} does not lie within the image".format(array_lba))
    array = image.read(array_offset, count * entry_size, "the GPT partition array")
    if zlib.crc32(array) != array_crc:
        raise InvalidImageError("the GPT partition array's CRC does not match")
    return [array[start : start + entry_size] for start in range(0, len(array), entry_size)]


def _find_esp(image):
    sector_size = _gpt_sector_size(image)
    esps = []
    for entry in _gpt_entries(image, sector_size):
        if uuid.UUID(bytes_le=entry[:16]) == ESP_TYPE_GUID:
            first, last = struct.unpack_from("<QQ", entry, 32)
            esps.append(Partition(first * sector_size, (last - first + 1) * sector_size, sector_size))
    if len(esps) != 1:
        raise InvalidImageError("the GPT must hold exactly one EFI system partition, found {}".format(len(esps)))
    esp = esps[0]
    if esp.offset < 2 * sector_size or esp.size <= 0 or esp.offset + esp.size > image.size:
        raise InvalidImageError("the EFI system partition does not lie within the image")
    return esp


def _geometry(boot, partition):
    """Returns the geometry of the FAT file system whose boot sector is boot; raises InvalidImageError if invalid."""
    sector, per_cluster, reserved, fats, root_entries, total16, _, fat_size16 = struct.unpack_from(
        "<HBHBHHBH", boot, 11
    )
    total32, fat_size32, _, _, root_cluster = struct.unpack_from("<IIHHI", boot, 32)
    fat32 = fat_size16 == 0
    fat_size = (fat_size32 if fat32 else fat_size16) * sector
    total = (total16 or total32) * sector
    valid = (
        boot[510:512] == b"\x55\xaa"
        and sector in (512, 1024, 2048, 4096)
        and per_cluster in (1, 2, 4, 8, 16, 32, 64, 128)
        and reserved > 0
        and fats > 0
        and fat_size > 0
        and (root_entries == 0) == fat32
    )
    if not valid:
        raise InvalidImageError("the ESP holds no FAT file system: its boot sector is invalid")
    if total > partition.size:
        raise InvalidImageError("the ESP's FAT file system is larger than the partition")
    root_offset = reserved * sector + fats * fat_size
    root_size = root_entries * _DIRECTORY_ENTRY
    data_offset = root_offset + -(-root_size // sector) * sector
    cluster_size = per_cluster * sector
    clusters = max(total - data_offset, 0) // cluster_size
    if clusters == 0:
        raise InvalidImageError("the ESP's FAT file system has no data clusters")
    return _Geometry(
        fat32=fat32,
        fat_offset=partition.offset + reserved * sector,
        fat_size=fat_size,
        root_offset=partition.offset + root_offset,
        root_size=root_size,
        root_cluster=root_cluster if fat32 else 0,
        data_offset=partition.offset + data_offset,
        cluster_size=cluster_size,
        clusters=clusters,
    )


def _short_name_checksum(raw_name):
    checksum = 0
    for byte in raw_name:
        checksum = (((checksum & 1) << 7) + (checksum >> 1) + byte) & 0xFF
    return checksum


def _short_name(raw):
    """Returns the 8.3 name of a directory entry, lowercased as the Windows NT case flags request."""
    base = (b"\xe5" + raw[1:8] if raw[0] == 0x05 else raw[:8]).rstrip(b" ").decode("cp437")
    extension = raw[8:11].rstrip(b" ").decode("cp437")
    if raw[12] & 0x08:
        base = base.lower()
    if raw[12] & 0x10:
        extension = extension.lower()
    return base + "." + extension if extension else base


def _long_name(slots, raw):
    """Returns the VFAT long name that slots, in on-disk order, give the short entry raw, or None if they do not.

    Like Windows and Linux, ignores long names whose slots are out of order or belong to another short name.
    """
    if not slots:
        return None
    count = slots[0][0] & ~_LAST_LONG_NAME_SLOT
    if not 1 <= count <= _MAX_LONG_NAME_SLOTS:
        return None
    expected = [count | _LAST_LONG_NAME_SLOT, *range(count - 1, 0, -1)]
    checksum = _short_name_checksum(raw[:11])
    if [slot[0] for slot in slots] != expected or any(slot[13] != checksum for slot in slots):
        return None
    units = b"".join(slot[1:11] + slot[14:26] + slot[28:32] for slot in reversed(slots))
    return units.decode("utf-16-le", errors="replace").split("\0", 1)[0] or None


def _fold(name):
    return name.upper()


class _WalkLimits:
    """The clusters that the directories of one walk use, and how many more directory bytes the walk may read."""

    def __init__(self, budget):
        self.claimed = set()
        self.remaining = budget

    def claim(self, chain, size, what):
        """Records a directory of size bytes in chain; raises InvalidImageError if it is cross-linked or too large."""
        shared = self.claimed.intersection(chain)
        if shared:
            raise InvalidImageError(
                "{} shares cluster {} with another directory, so the ESP is cross-linked".format(what, min(shared))
            )
        self.claimed.update(chain)
        # Every cluster is read at most once, so this limit only guards against a mistake in that reasoning.
        self.remaining -= size
        if self.remaining < 0:
            raise InvalidImageError("the ESP's directories are larger than the ESP")


class _FatVolume:
    """A read-only FAT12, FAT16 or FAT32 file system on a partition of an open disk image."""

    def __init__(self, image, partition):
        self.image = image
        self.partition = partition
        self.geometry = _geometry(image.read(partition.offset, 512, "the ESP's boot sector"), partition)
        self.last_cluster = self.geometry.clusters + 1
        if self.geometry.fat32:
            self.bits = 32
        else:
            self.bits = 12 if self.geometry.clusters < _FAT12_CLUSTER_LIMIT else 16
        if (self.last_cluster + 1) * self.bits > self.geometry.fat_size * 8:
            raise InvalidImageError("the ESP's FAT is too small for its {} clusters".format(self.geometry.clusters))
        self.fat = image.read(self.geometry.fat_offset, self.geometry.fat_size, "the ESP's FAT")

    def _next_cluster(self, cluster):
        if self.bits == 12:
            value = struct.unpack_from("<H", self.fat, cluster * 3 // 2)[0]
            return value >> 4 if cluster & 1 else value & 0xFFF
        if self.bits == 16:
            return struct.unpack_from("<H", self.fat, cluster * 2)[0]
        return struct.unpack_from("<I", self.fat, cluster * 4)[0] & 0x0FFFFFFF

    def _chain(self, first, what):
        """Returns the clusters of the chain that starts at first; raises InvalidImageError if it is broken or loops."""
        chain = []
        visited = set()
        cluster = first
        while True:
            if not 2 <= cluster <= self.last_cluster:
                raise InvalidImageError("the cluster chain of {} reaches invalid cluster {}".format(what, cluster))
            if cluster in visited:
                raise InvalidImageError("the cluster chain of {} loops at cluster {}".format(what, cluster))
            visited.add(cluster)
            chain.append(cluster)
            cluster = self._next_cluster(cluster)
            if cluster >= _END_OF_CHAIN[self.bits]:
                return chain

    def _read_chain(self, chain, what):
        size = self.geometry.cluster_size
        offset = self.geometry.data_offset
        return b"".join(self.image.read(offset + (cluster - 2) * size, size, what) for cluster in chain)

    def read_file(self, entry, what):
        """Returns the bytes of the regular file of a directory entry."""
        if entry.size == 0:
            return b""
        chain = self._chain(entry.cluster, what)
        if len(chain) != -(-entry.size // self.geometry.cluster_size):
            raise InvalidImageError(
                "{} has {} bytes but a chain of {} {}-byte clusters".format(
                    what, entry.size, len(chain), self.geometry.cluster_size
                )
            )
        return self._read_chain(chain, what)[: entry.size]

    def directory(self, cluster, what, limits=None):
        """Returns the entries of the directory at cluster, or of the root directory if cluster is None.

        A walk passes its _WalkLimits, which reject a directory that shares a cluster with another one.
        """
        if cluster is None and not self.geometry.fat32:
            if limits:
                limits.claim([], self.geometry.root_size, what)
            return self._entries(self.image.read(self.geometry.root_offset, self.geometry.root_size, what))
        chain = self._chain(self.geometry.root_cluster if cluster is None else cluster, what)
        size = len(chain) * self.geometry.cluster_size
        if size > _MAX_DIRECTORY_BYTES:
            raise InvalidImageError("{} has more than 65536 entries".format(what))
        if limits:
            limits.claim(chain, size, what)
        return self._entries(self._read_chain(chain, what))

    @staticmethod
    def _add_slot(slots, raw):
        """Returns the long name slots before the next short entry, dropping runs longer than any long name."""
        if raw[0] & _LAST_LONG_NAME_SLOT:
            return [raw]
        if len(slots) >= _MAX_LONG_NAME_SLOTS:
            return []
        slots.append(raw)
        return slots

    def _entries(self, data):
        """Returns the files and subdirectories in the directory data, without the volume label, '.' and '..'."""
        entries = []
        slots = []
        for start in range(0, len(data) - _DIRECTORY_ENTRY + 1, _DIRECTORY_ENTRY):
            raw = data[start : start + _DIRECTORY_ENTRY]
            if raw[0] == 0:
                break
            if raw[0] == _DELETED:
                slots = []
            elif raw[11] & 0x3F == _ATTRIBUTE_LONG_NAME:
                slots = self._add_slot(slots, raw)
            else:
                long_name, slots = _long_name(slots, raw), []
                short_name = _short_name(raw)
                if raw[11] & _ATTRIBUTE_VOLUME_LABEL or short_name in (".", ".."):
                    continue
                high = struct.unpack_from("<H", raw, 20)[0] if self.geometry.fat32 else 0
                cluster = high << 16 | struct.unpack_from("<H", raw, 26)[0]
                size = struct.unpack_from("<I", raw, 28)[0]
                entries.append(_Entry(long_name or short_name, short_name, raw[11], cluster, size))
        return entries

    def lookup(self, esp_path):
        """Returns the directory entry of esp_path, matching each long or short name component case-insensitively."""
        components = [component for component in esp_path.split("/") if component]
        if not components:
            raise EspFileNotFoundError("the ESP path {!r} names no file".format(esp_path))
        entry = None
        for index, component in enumerate(components):
            if entry is not None and not entry.is_directory:
                raise EspFileNotFoundError("the ESP has no file {}: {} is a file".format(esp_path, entry.name))
            parent = "/".join(components[:index]) or "the root directory"
            folded = _fold(component)
            matches = [
                found
                for found in self.directory(None if entry is None else entry.cluster, parent)
                if folded in (_fold(found.name), _fold(found.short_name))
            ]
            if not matches:
                raise EspFileNotFoundError("the ESP has no file {}".format(esp_path))
            entry = matches[0]
        return entry

    def walk(self):
        """Returns every regular file on the ESP; raises InvalidImageError if two directories share a cluster."""
        files = []
        pending = [("", None)]
        limits = _WalkLimits(self.partition.size)
        while pending:
            prefix, cluster = pending.pop()
            for entry in self.directory(cluster, prefix.rstrip("/") or "the root directory", limits):
                if entry.is_directory:
                    pending.append((prefix + entry.name + "/", entry.cluster))
                else:
                    files.append(EspFile(prefix + entry.name, entry.size))
        return sorted(files)


def find_esp(image_path: str | os.PathLike) -> Partition:
    """Returns the location of the only EFI system partition in the GPT of the raw disk image at image_path.

    Raises:
        InvalidImageError: if the image has no valid GPT, or the GPT does not hold exactly one ESP inside the image.
        OSError: if the image cannot be read.
    """
    with open(image_path, "rb") as file:
        return _find_esp(_Image(file))


def list_esp_files(image_path: str | os.PathLike) -> list[EspFile]:
    """Returns every regular file on the ESP of the raw disk image at image_path, sorted by path.

    Raises:
        InvalidImageError: if the image, its GPT, or the ESP's FAT file system is malformed.
        OSError: if the image cannot be read.
    """
    with open(image_path, "rb") as file:
        image = _Image(file)
        return _FatVolume(image, _find_esp(image)).walk()


def read_esp_file(image_path: str | os.PathLike, esp_path: str) -> bytes:
    """Returns the bytes of the file at esp_path, such as EFI/BOOT/BOOTX64.EFI, on the ESP of a raw disk image.

    Raises:
        EspFileNotFoundError: if the ESP has no regular file at esp_path.
        InvalidImageError: if the image, its GPT, or the ESP's FAT file system is malformed.
        OSError: if the image cannot be read.
    """
    with open(image_path, "rb") as file:
        image = _Image(file)
        volume = _FatVolume(image, _find_esp(image))
        entry = volume.lookup(esp_path)
        if entry.is_directory:
            raise EspFileNotFoundError("the ESP path {} is a directory".format(esp_path))
        return volume.read_file(entry, esp_path)


def read_esp_manifest(image_path: str | os.PathLike) -> dict:
    """Returns the ESP manifest that secure_boot_signed_image wrote to the raw disk image at image_path.

    The manifest describes the image as built, so read it before the image boots for the first time.

    Raises:
        EspFileNotFoundError: if the ESP has no manifest, so the image was not built by secure_boot_signed_image.
        InvalidImageError: if the image or the manifest is malformed, or the manifest has another format_version.
        OSError: if the image cannot be read.
    """
    data = read_esp_file(image_path, ESP_MANIFEST_PATH)
    try:
        manifest = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InvalidImageError("the ESP manifest is not JSON: {}".format(error)) from error
    if not isinstance(manifest, dict) or manifest.get("format_version") != ESP_MANIFEST_FORMAT:
        raise InvalidImageError("the ESP manifest is not a {} document".format(ESP_MANIFEST_FORMAT))
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image", help="raw disk image with a GPT")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--list", action="store_true", help="print the path of every file on the ESP")
    action.add_argument("--extract", metavar="ESP_PATH", help="write the bytes of the file at ESP_PATH to stdout")
    args = parser.parse_args(argv)
    # `bazel run` starts the tool in its runfiles directory; relative paths name files in the caller's directory.
    args.image = os.path.join(os.environ.get("BUILD_WORKING_DIRECTORY", ""), args.image)
    try:
        if args.list:
            sys.stdout.write("".join(file.path + "\n" for file in list_esp_files(args.image)))
        elif args.extract is not None:
            sys.stdout.flush()
            sys.stdout.buffer.write(read_esp_file(args.image, args.extract))
        else:
            sys.stdout.write(json.dumps(read_esp_manifest(args.image), indent=2, sort_keys=True) + "\n")
    except EspFileNotFoundError as error:
        print("esp_manifest: {}: {}".format(args.image, error), file=sys.stderr)
        return 3
    except (OSError, ValueError) as error:
        print("esp_manifest: {}: {}".format(args.image, error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
