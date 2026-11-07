"""Tests the ESP manifest reader with GPT disks whose FAT ESPs the pinned mkfs.fat and mtools create."""

import ast
import functools
import itertools
import json
import os
import random
import runpy
import shutil
import struct
import subprocess
import sys
import unittest
import uuid
import zlib
from pathlib import Path
from unittest import mock

import rules_mkosi_esp_manifest as esp_manifest

SCRIPT, LAUNCHER_TOOL, DEBIAN_TOOLS, SECURE_BOOT_IMAGE = (str(Path(path).absolute()) for path in sys.argv[1:5])
launcher_tool = runpy.run_path(LAUNCHER_TOOL)
# Relative, so that the Debian tools launcher maps the paths into its namespace.
WORK = Path("esp-manifest-work")
LINUX_DATA = uuid.UUID("0fc63daf-8483-4772-8e79-3d69d8477de4")
ESP_START = 1 << 20
MANIFEST = {
    "auto_enroll_keys": [],
    "format_version": esp_manifest.ESP_MANIFEST_FORMAT,
    "replaced": [],
    "secure_boot_enroll": None,
}
BIG = random.Random(0).randbytes(300 * 1024)
FILES = {
    "EFI/BOOT/BOOTX64.EFI": b"MZ boot loader",
    "EFI/Linux/os_1+3.efi": b"MZ unified kernel image",
    "big.bin": BIG,
    "loader/loader.conf": b"timeout 3\n",
    "loader/empty": b"",
    "loader/keys/auto/db.auth": b"db",
    "loader/entries/Thirteen char": b"a long name that fills exactly one slot",
    **{"loader/entries/entry-{:02}-with-a-long-name.conf".format(n): b"entry %d\n" % n for n in range(40)},
    esp_manifest.ESP_MANIFEST_PATH: json.dumps(MANIFEST).encode(),
}
FRAGMENTED = "EFI/fragmented.bin"
# Name: (FAT type, sector size of the file system and the disk, sectors per cluster, file system size in KiB).
SCENARIOS = {
    "fat12": (12, 512, 4, 4096),
    "fat16": (16, 512, 4, 32768),
    "fat32": (32, 512, 1, 40960),
    "fat16_4k_sectors": (16, 4096, 1, 32768),
    "fat32_4k_sectors": (32, 4096, 1, 40960),
}


def _write_tree(tree, files):
    shutil.rmtree(tree, ignore_errors=True)
    for esp_path, data in files.items():
        (tree / esp_path).parent.mkdir(parents=True, exist_ok=True)
        (tree / esp_path).write_bytes(data)


def _esp_commands(name, bits, sector_size, cluster_sectors, size_kib):
    """Returns the shell lines that create the FAT image of a scenario and leave EFI/fragmented.bin fragmented."""
    image = WORK / (name + ".fat")
    tree = WORK / (name + "-tree")
    _write_tree(tree, FILES | {"EFI/gap.bin": bytes(3 * 4096), "EFI/after.bin": b"after", FRAGMENTED: BIG[:40000]})
    (tree / FRAGMENTED).rename(WORK / (name + "-fragmented.bin"))
    path = launcher_tool["namespace_path"]
    tool = DEBIAN_TOOLS
    options = "-F {} -S {} -s {}".format(bits, sector_size, cluster_sectors)
    commands = ["/usr/sbin/mkfs.fat -C -i 12345678 {} {} {}".format(options, path(tool, image), size_kib)]
    for top in sorted(tree.iterdir()):
        commands.append("/usr/bin/mcopy -s -i {} {} ::/".format(path(tool, image), path(tool, top)))
    commands.append("/usr/bin/mdel -i {} ::/EFI/gap.bin".format(path(tool, image)))
    fragmented = path(tool, WORK / (name + "-fragmented.bin"))
    commands.append("/usr/bin/mcopy -i {} {} ::/{}".format(path(tool, image), fragmented, FRAGMENTED))
    return image, commands


def _gpt(first, last, total, sector_size, type_guids):
    """Returns the primary GPT header and partition array of a disk with one partition per type GUID.

    The reader checks only the primary GPT, so the disk needs no backup GPT.
    """
    array = bytearray(128 * 128)
    for index, type_guid in enumerate(type_guids):
        partition_guid = uuid.UUID(int=index + 1).bytes_le
        entry = (type_guid.bytes_le, partition_guid, first, last, 0, "ESP".encode("utf-16-le"))
        struct.pack_into("<16s16sQQQ72s", array, index * 128, *entry)
    header = bytearray(92)
    array_sectors = len(array) // sector_size
    usable = (2 + array_sectors, total - 2 - array_sectors)
    locations = (1, total - 1, *usable, uuid.UUID(int=99).bytes_le, 2, 128, 128, zlib.crc32(array))
    struct.pack_into("<8sIII4xQQQQ16sQIII", header, 0, b"EFI PART", 0x00010000, 92, 0, *locations)
    struct.pack_into("<I", header, 16, zlib.crc32(header))
    return header, array


def _write_disk(disk, esp, sector_size, type_guids=(esp_manifest.ESP_TYPE_GUID,)):
    """Writes a GPT disk whose partitions, one per type GUID, all hold the file system image esp at 1 MiB."""
    data = esp.read_bytes()
    first = ESP_START // sector_size
    last = first + -(-len(data) // sector_size) - 1
    total = last + 1 + 64
    header, array = _gpt(first, last, total, sector_size, type_guids)
    mbr = bytearray(512)
    struct.pack_into("<B3xB3xII", mbr, 446, 0, 0xEE, 1, min(total - 1, 0xFFFFFFFF))
    mbr[510:512] = b"\x55\xaa"
    with open(disk, "wb") as writer:
        writer.write(mbr)
        writer.seek(sector_size)
        writer.write(header)
        writer.seek(2 * sector_size)
        writer.write(array)
        for offset in range(0, len(data), 1 << 16):
            block = data[offset : offset + (1 << 16)]
            if block.count(0) != len(block):
                writer.seek(ESP_START + offset)
                writer.write(block)
        writer.truncate(total * sector_size)


def _fat_type(esp):
    """Returns the FAT type that mkfs.fat recorded in the boot sector of the file system image esp."""
    boot = esp.read_bytes()[:512]
    return 32 if struct.unpack_from("<H", boot, 22)[0] == 0 else int(boot[54:59].decode().removeprefix("FAT"))


def _run(*arguments, env=None):
    return subprocess.run([sys.executable, SCRIPT, *map(str, arguments)], capture_output=True, check=False, env=env)


class Fixture:
    """The disks of every scenario, built with one call of the Debian tools launcher."""

    def __init__(self):
        shutil.rmtree(WORK, ignore_errors=True)
        WORK.mkdir()
        self.esps = {}
        commands = ["set -eu", "export MTOOLS_SKIP_CHECK=1"]
        for name, scenario in SCENARIOS.items():
            self.esps[name], lines = _esp_commands(name, *scenario)
            commands += lines
        # A deleted manifest leaves deleted long name slots and a deleted short entry behind.
        self.esps["fat12_without_manifest"] = WORK / "fat12_without_manifest.fat"
        path = functools.partial(launcher_tool["namespace_path"], DEBIAN_TOOLS)
        without_manifest = path(self.esps["fat12_without_manifest"])
        commands.append("/bin/cp {} {}".format(path(self.esps["fat12"]), without_manifest))
        commands.append("/usr/bin/mdel -i {} ::/{}".format(without_manifest, esp_manifest.ESP_MANIFEST_PATH))
        script = WORK / "create.sh"
        script.write_text("\n".join(commands) + "\n")
        launcher_tool["run_tool"](DEBIAN_TOOLS, "/bin/sh", script)
        self.disks = {}
        for name, (_, sector_size, _, _) in SCENARIOS.items():
            self.disks[name] = WORK / (name + ".raw")
            _write_disk(self.disks[name], self.esps[name], sector_size)
        self.disk_without_manifest = WORK / "fat12_without_manifest.raw"
        _write_disk(self.disk_without_manifest, self.esps["fat12_without_manifest"], 512)
        self.files = FILES | {"EFI/after.bin": b"after", FRAGMENTED: BIG[:40000]}

    def patched(self, name, patch):
        """Returns a copy of the FAT16 disk that patch(data, ESP offset) changed in place."""
        data = bytearray(self.disks["fat16"].read_bytes())
        patch(data, ESP_START)
        path = WORK / (name + ".raw")
        path.write_bytes(data)
        return path


@functools.cache
def _fixture():
    return Fixture()


def _entry(data, offset, short_name):
    """Returns the offset of the only directory entry with the 11-byte short_name after offset."""
    position = data.find(short_name, offset)
    if position < 0 or data.find(short_name, position + 1) >= 0:
        raise AssertionError("expected one {} entry".format(short_name))
    return position


def _fat16_entry(data, esp, cluster):
    """Returns the offset of the FAT16 entry of cluster in the first FAT."""
    return esp + struct.unpack_from("<H", data, esp + 14)[0] * 512 + cluster * 2


def _first_cluster(data, entry):
    return struct.unpack_from("<H", data, entry + 26)[0]


def _fat16_chain(data, esp, first):
    """Returns the clusters of the FAT16 chain that starts at first."""
    chain = [first]
    while (following := struct.unpack_from("<H", data, _fat16_entry(data, esp, chain[-1]))[0]) < 0xFFF8:
        chain.append(following)
    return chain


def _fat16_cluster_offset(data, esp, cluster):
    """Returns the offset of a FAT16 data cluster, after the FATs and the fixed root directory."""
    sector, per_cluster, reserved, fats, root_entries = struct.unpack_from("<HBHBH", data, esp + 11)
    fat_size = struct.unpack_from("<H", data, esp + 22)[0]
    data_start = (reserved + fats * fat_size) * sector + root_entries * 32
    return esp + data_start + (cluster - 2) * per_cluster * sector


def _write_clusters(data, esp, chain, content):
    """Writes content across the FAT16 clusters of chain, zero-padded to their size."""
    size = struct.unpack_from("<H", data, esp + 11)[0] * data[esp + 13]
    content = content.ljust(len(chain) * size, b"\0")
    for index, cluster in enumerate(chain):
        offset = _fat16_cluster_offset(data, esp, cluster)
        data[offset : offset + size] = content[index * size : (index + 1) * size]


def _long_name_slot(sequence, checksum, name=""):
    units = name.encode("utf-16-le").ljust(26, b"\0")
    return bytes([sequence]) + units[:10] + bytes([0x0F, 0, checksum]) + units[10:22] + bytes(2) + units[22:26]


def _short_entry(name):
    return name + bytes([0x20]) + bytes(20)


class ScenarioTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = _fixture()

    def test_scenarios_cover_every_fat_type_and_sector_size(self):
        for name, (bits, *_) in SCENARIOS.items():
            self.assertEqual(_fat_type(self.fixture.esps[name]), bits, name)
        sector_sizes = {esp_manifest.find_esp(disk).sector_size for disk in self.fixture.disks.values()}
        self.assertEqual(sector_sizes, {512, 4096})

    def test_a_file_is_fragmented(self):
        fragmented = []
        for name, disk in self.fixture.disks.items():
            with open(disk, "rb") as file:
                # The reader has no public API for cluster chains.
                volume = esp_manifest._FatVolume(esp_manifest._Image(file), esp_manifest.find_esp(disk))
                chain = volume._chain(volume.lookup(FRAGMENTED).cluster, FRAGMENTED)
            if any(cluster + 1 != following for cluster, following in itertools.pairwise(chain)):
                fragmented.append(name)
        self.assertTrue(fragmented)

    def test_esp_is_found_at_its_gpt_extent(self):
        for name, disk in self.fixture.disks.items():
            esp = esp_manifest.find_esp(disk)
            self.assertEqual((esp.offset, esp.size), (ESP_START, self.fixture.esps[name].stat().st_size), name)

    def test_manifest_is_read(self):
        for name, disk in self.fixture.disks.items():
            self.assertEqual(esp_manifest.read_esp_manifest(disk), MANIFEST, name)

    def test_every_file_is_listed_with_its_long_name_and_size(self):
        expected = sorted(esp_manifest.EspFile(path, len(data)) for path, data in self.fixture.files.items())
        for name, disk in self.fixture.disks.items():
            self.assertEqual(esp_manifest.list_esp_files(disk), expected, name)

    def test_every_file_reads_back_byte_for_byte(self):
        for name, disk in self.fixture.disks.items():
            for path, data in self.fixture.files.items():
                self.assertEqual(esp_manifest.read_esp_file(disk, path), data, "{}: {}".format(name, path))

    def test_paths_are_case_insensitive_and_match_short_names(self):
        disk = self.fixture.disks["fat32"]
        self.assertEqual(esp_manifest.read_esp_file(disk, "/efi/boot/bootx64.efi"), FILES["EFI/BOOT/BOOTX64.EFI"])
        self.assertEqual(esp_manifest.read_esp_file(disk, "LOADER/LOADER.CONF"), FILES["loader/loader.conf"])
        self.assertEqual(esp_manifest.read_esp_file(disk, "BIG.BIN"), BIG)

    def test_missing_files_and_directories_are_not_found(self):
        disk = self.fixture.disks["fat12"]
        for path in ("loader/missing.json", "loader", "big.bin/inside", "", "missing/loader.conf"):
            with self.assertRaises(esp_manifest.EspFileNotFoundError, msg=path):
                esp_manifest.read_esp_file(disk, path)

    def test_constants_match_the_signed_image_tool(self):
        assignments = {
            node.targets[0].id: node.value.value
            for node in ast.parse(Path(SECURE_BOOT_IMAGE).read_text()).body
            if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.targets[0], ast.Name)
        }
        self.assertEqual(assignments["ESP_MANIFEST"], esp_manifest.ESP_MANIFEST_PATH)
        self.assertEqual(assignments["ESP_MANIFEST_FORMAT"], esp_manifest.ESP_MANIFEST_FORMAT)

    def test_command_line(self):
        disk = self.fixture.disks["fat16_4k_sectors"]
        printed = _run(disk)
        self.assertEqual((printed.returncode, json.loads(printed.stdout)), (0, MANIFEST), printed.stderr)
        listed = _run("--list", disk)
        self.assertEqual(listed.stdout.decode().splitlines(), sorted(self.fixture.files), listed.stderr)
        extracted = _run("--extract", "big.bin", disk)
        self.assertEqual((extracted.returncode, extracted.stdout), (0, BIG), extracted.stderr)
        environment = dict(os.environ, BUILD_WORKING_DIRECTORY=str(disk.parent.absolute()))
        relative = _run(disk.name, env=environment)
        self.assertEqual((relative.returncode, json.loads(relative.stdout)), (0, MANIFEST), relative.stderr)

    def test_command_line_exit_status_tells_a_missing_file_from_an_invalid_image(self):
        missing = _run("--extract", "loader/missing", self.fixture.disks["fat12"])
        self.assertEqual(missing.returncode, 3)
        self.assertIn(b"loader/missing", missing.stderr)
        self.assertEqual(_run(WORK / "absent.raw").returncode, 1)
        self.assertEqual(_run(self.fixture.esps["fat12"]).returncode, 1)
        self.assertEqual(_run("--list", "--extract", "big.bin", self.fixture.disks["fat12"]).returncode, 2)


class MalformedImageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = _fixture()

    def assert_invalid(self, disk, message, read=lambda disk: esp_manifest.read_esp_file(disk, "big.bin")):
        with self.assertRaisesRegex(esp_manifest.InvalidImageError, message):
            read(disk)

    def test_cyclic_cluster_chain_is_rejected(self):
        def loop(data, esp):
            first = _first_cluster(data, _entry(data, esp, b"BIG     BIN"))
            second = struct.unpack_from("<H", data, _fat16_entry(data, esp, first))[0]
            struct.pack_into("<H", data, _fat16_entry(data, esp, second), first)

        self.assert_invalid(self.fixture.patched("loop", loop), "loops at cluster")

    def test_chain_into_a_free_cluster_is_rejected(self):
        def free(data, esp):
            first = _first_cluster(data, _entry(data, esp, b"BIG     BIN"))
            struct.pack_into("<H", data, _fat16_entry(data, esp, first), 0)

        self.assert_invalid(self.fixture.patched("free", free), "invalid cluster 0")

    def test_size_beyond_the_chain_is_rejected(self):
        def grow(data, esp):
            entry = _entry(data, esp, b"BIG     BIN")
            struct.pack_into("<I", data, entry + 28, len(BIG) + (1 << 16))

        self.assert_invalid(self.fixture.patched("grow", grow), "bytes but a chain of")

    def test_directory_that_contains_its_parent_is_rejected(self):
        def loop(data, esp):
            keys = _first_cluster(data, _entry(data, esp, b"KEYS       "))
            struct.pack_into("<H", data, _entry(data, esp, b"AUTO       ") + 26, keys)

        self.assert_invalid(self.fixture.patched("directory-loop", loop), "cross-linked", esp_manifest.list_esp_files)

    def test_subdirectory_at_cluster_zero_is_rejected(self):
        def to_root(data, esp):
            struct.pack_into("<H", data, _entry(data, esp, b"AUTO       ") + 26, 0)

        disk = self.fixture.patched("directory-at-zero", to_root)
        self.assert_invalid(disk, "invalid cluster 0", esp_manifest.list_esp_files)

    def test_directories_that_share_clusters_are_rejected(self):
        def cross_link(data, esp):
            keys = _first_cluster(data, _entry(data, esp, b"KEYS       "))
            entries = _fat16_chain(data, esp, _first_cluster(data, _entry(data, esp, b"ENTRIES    ")))
            self.assertGreater(len(entries), 1)
            struct.pack_into("<H", data, _fat16_entry(data, esp, keys), entries[1])

        disk = self.fixture.patched("cross-linked", cross_link)
        self.assert_invalid(disk, "shares cluster .* cross-linked", esp_manifest.list_esp_files)

    def test_walk_reads_at_most_the_esp_size_of_directories(self):
        limits = esp_manifest._WalkLimits(4096)
        limits.claim([2], 2048, "first")
        with self.assertRaisesRegex(esp_manifest.InvalidImageError, "larger than the ESP"):
            limits.claim([3, 4], 4096, "second")

    def test_long_name_slot_runs_are_bounded(self):
        """A directory of stray long name slots is parsed in linear time, and a slot count of 0 names nothing."""

        def stray_slots(data, esp):
            entry = _entry(data, esp, b"BIG     BIN")
            data[entry + 11] = 0x10
            struct.pack_into("<I", data, entry + 28, 0)
            zero = b"ZERO    BIN"
            content = _long_name_slot(1, 0) * 9000 + _short_entry(b"PLAIN   TXT")
            content += _long_name_slot(0x40, esp_manifest._short_name_checksum(zero), "X") + _short_entry(zero)
            _write_clusters(data, esp, _fat16_chain(data, esp, _first_cluster(data, entry)), content)

        disk = self.fixture.patched("stray-slots", stray_slots)
        with mock.patch.object(esp_manifest, "_long_name", wraps=esp_manifest._long_name) as long_name:
            files = [file.path for file in esp_manifest.list_esp_files(disk)]
        self.assertIn("big.bin/PLAIN.TXT", files)
        self.assertIn("big.bin/ZERO.BIN", files)
        self.assertLessEqual(max(len(call.args[0]) for call in long_name.call_args_list), 20)

    def test_partition_array_outside_the_image_is_rejected(self):
        for lba in (1, 1 << 40, 1 << 63, (1 << 64) - 1):

            def move(data, _, lba=lba):
                struct.pack_into("<QI", data, 512 + 72, lba, 128)
                struct.pack_into("<I", data, 512 + 16, 0)
                struct.pack_into("<I", data, 512 + 16, zlib.crc32(data[512 : 512 + 92]))

            self.assert_invalid(self.fixture.patched("gpt-lba", move), "partition array at LBA {} ".format(lba))

    def test_corrupt_gpt_is_rejected(self):
        def corrupt(data, _):
            data[2 * 512 + 56] ^= 1

        self.assert_invalid(self.fixture.patched("gpt-crc", corrupt), "partition array's CRC")

    def test_image_without_protective_mbr_is_rejected(self):
        def wipe(data, _):
            data[510:512] = b"\0\0"

        self.assert_invalid(self.fixture.patched("no-mbr", wipe), "protective MBR")

    def test_esp_without_fat_is_rejected(self):
        def wipe(data, esp):
            data[esp : esp + 512] = bytes(512)

        self.assert_invalid(self.fixture.patched("no-fat", wipe), "no FAT file system")

    def test_truncated_image_is_rejected(self):
        disk = WORK / "truncated.raw"
        disk.write_bytes(self.fixture.disks["fat16"].read_bytes()[: ESP_START + 4096])
        self.assert_invalid(disk, "does not lie within the image")

    def test_disk_needs_exactly_one_esp(self):
        for name, type_guids in (("no-esp", (LINUX_DATA,)), ("two-esps", (esp_manifest.ESP_TYPE_GUID,) * 2)):
            disk = WORK / (name + ".raw")
            _write_disk(disk, self.fixture.esps["fat12"], 512, type_guids)
            found = type_guids.count(esp_manifest.ESP_TYPE_GUID)
            self.assert_invalid(disk, "exactly one EFI system partition, found {}".format(found))

    def test_manifest_of_another_format_or_not_json_is_rejected(self):
        old = esp_manifest.ESP_MANIFEST_FORMAT.encode()
        for name, new in (("other-format", old[:-1] + b"9"), ("not-json", b"\xff" * len(old))):

            def replace(data, esp, new=new):
                position = _entry(data, esp, old)
                data[position : position + len(old)] = new

            self.assert_invalid(
                self.fixture.patched(name, replace), "ESP manifest is not", esp_manifest.read_esp_manifest
            )

    def test_deleted_manifest_is_not_found(self):
        disk = self.fixture.disk_without_manifest
        with self.assertRaises(esp_manifest.EspFileNotFoundError):
            esp_manifest.read_esp_manifest(disk)
        self.assertNotIn(esp_manifest.ESP_MANIFEST_PATH, [file.path for file in esp_manifest.list_esp_files(disk)])
        self.assertEqual(_run(disk).returncode, 3)


if __name__ == "__main__":
    unittest.main(argv=sys.argv[:1])
