"""Minimal PE/COFF binaries and ESP disk images for the Secure Boot tests."""

import json
import shutil
import struct

ESP_TYPE_GUID = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
# The ESP starts at 1 MiB and is followed by 1 MiB of nonzero bytes that must survive any ESP rewrite.
ESP_OFFSET = 1 << 20
TRAILER = b"\xa5" * (1 << 20)


def minimal_pe(marker=b"requested UKI"):
    data = bytearray(0x400)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", data, 0x84, 0x8664, 1, 0, 0, 0, 0xF0, 0x22)
    optional = 0x98
    struct.pack_into("<H", data, optional, 0x20B)
    struct.pack_into("<I", data, optional + 16, 0x1000)
    struct.pack_into("<Q", data, optional + 24, 0x400000)
    struct.pack_into("<II", data, optional + 32, 0x1000, 0x200)
    struct.pack_into("<I", data, optional + 56, 0x2000)
    struct.pack_into("<I", data, optional + 60, 0x200)
    struct.pack_into("<H", data, optional + 68, 10)
    struct.pack_into("<I", data, optional + 108, 16)
    section = optional + 0xF0
    data[section : section + 8] = b".linux\0\0"
    struct.pack_into("<IIII", data, section + 8, 0x200, 0x1000, 0x200, 0x200)
    data[0x200 : 0x200 + len(marker)] = marker
    return bytes(data)


def disk_with_esp(run_tool, tools, work, files):
    """Returns a disk whose FAT ESP holds files, keyed by ESP path, and its partition metadata.

    Values are source paths or bytes.
    """
    tree = work / "esp-tree"
    shutil.rmtree(tree, ignore_errors=True)
    for esp_path, source in files.items():
        (tree / esp_path).parent.mkdir(parents=True, exist_ok=True)
        (tree / esp_path).write_bytes(source if isinstance(source, bytes) else source.read_bytes())
    esp = work / "esp.img"
    esp.unlink(missing_ok=True)
    run_tool(tools, "/usr/sbin/mkfs.fat", "-C", "-i", "12345678", esp, "8192")
    for top in sorted(tree.iterdir()):
        run_tool(tools, "/usr/bin/mcopy", "-s", "-i", esp, top, "::/")
    disk = work / "disk.raw"
    disk.write_bytes(bytes(ESP_OFFSET) + esp.read_bytes() + TRAILER)
    metadata = work / "partitions.json"
    partition = {"start_bytes": ESP_OFFSET, "size_bytes": esp.stat().st_size, "type_guid": ESP_TYPE_GUID}
    metadata.write_text(json.dumps({"partitions": [partition]}))
    return disk, metadata
