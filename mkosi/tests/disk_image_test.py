"""Tests the GPT reader of the shared disk image test helper on synthetic images."""

import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

import rules_mkosi_disk_image as disk_image

from mkosi.tests.partition_metadata_test import SECTOR, image

_ROOT = disk_image.gpt_partitions.ROOT_X86_64
# The pinned Debian tools launcher, the first argument of the test.
_LAUNCHER = ""


class DiskImageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = pathlib.Path(self.directory.name) / "image.raw"

    def write(self, raw: bytes | bytearray) -> pathlib.Path:
        self.path.write_bytes(raw)
        return self.path

    def test_lists_used_partitions_in_table_order(self) -> None:
        raw = image([(1, 2048, 4095, disk_image.gpt_partitions.ESP, "esp"), (3, 4096, 8191, _ROOT, "root-x86-64")])
        self.assertEqual(
            disk_image.list_partitions(self.write(raw)),
            [
                disk_image.Partition(1, disk_image.gpt_partitions.ESP, "esp", 2048 * SECTOR, 2048 * SECTOR),
                disk_image.Partition(3, _ROOT, "root-x86-64", 4096 * SECTOR, 4096 * SECTOR),
            ],
        )

    def test_rejects_an_image_without_a_valid_gpt(self) -> None:
        raw = image()
        raw[SECTOR : SECTOR + 8] = b"NOT GPT!"
        with self.assertRaises(ValueError):
            disk_image.list_partitions(self.write(raw))

    def test_finds_the_populated_root_and_skips_inactive_slots(self) -> None:
        raw = image([(1, 2048, 4095, _ROOT, "image_1"), (2, 4096, 6143, _ROOT, "_empty")])
        self.assertEqual(disk_image.find_root_partition(self.write(raw)).label, "image_1")

    def test_requires_one_root_of_the_architecture(self) -> None:
        path = self.write(image())
        with self.assertRaisesRegex(AssertionError, "arm64"):
            disk_image.find_root_partition(path, "arm64")

    def test_extracts_partition_bytes_and_holes(self) -> None:
        raw = image()
        start = 2048 * SECTOR
        raw[start : start + 5] = b"first"
        raw[start + 2048 * SECTOR - 4 : start + 2048 * SECTOR] = b"last"
        # A sparse copy of raw, whose holes extract_partition skips.
        with self.path.open("wb") as sparse:
            sparse.truncate(len(raw))
            for offset in range(0, len(raw), 4096):
                if any(raw[offset : offset + 4096]):
                    sparse.seek(offset)
                    sparse.write(raw[offset : offset + 4096])
        destination = pathlib.Path(self.directory.name) / "root.ext4"
        root = disk_image.extract_root_partition(self.path, destination)
        self.assertEqual(destination.read_bytes(), bytes(raw[start : start + root.size_bytes]))

    def test_rejects_a_truncated_partition(self) -> None:
        path = self.write(image())
        beyond = disk_image.Partition(9, _ROOT, "root-x86-64", path.stat().st_size - SECTOR, 2 * SECTOR)
        with self.assertRaisesRegex(AssertionError, "truncated"):
            disk_image.extract_partition(path, beyond, pathlib.Path(self.directory.name) / "partition")


class PopulatedRootTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = pathlib.Path(tempfile.mkdtemp(dir=os.environ["TEST_TMPDIR"]))

    def make_ext4(self, files: dict[str, str]) -> pathlib.Path:
        """Returns an 8 MiB ext4 image that mkfs.ext4 of the Debian tools populates with files."""
        tree = self.directory / "tree"
        for path, content in files.items():
            (tree / path).parent.mkdir(parents=True, exist_ok=True)
            (tree / path).write_text(content)
        tree.mkdir(exist_ok=True)
        output = self.directory / "output"
        output.mkdir()
        environment = {"PATH": "", "MKOSI_DEBIAN_TOOLS_SCRATCH": str(self.directory / "scratch")}
        environment.update({name: os.environ[name] for name in ("RUNFILES_DIR",) if name in os.environ})
        subprocess.run(
            [
                _LAUNCHER,
                "--ro-bind",
                "{}:/inputs/tree".format(tree),
                "--rw-bind",
                "{}:/outputs/root".format(output),
                "/usr/sbin/mkfs.ext4",
                "-q",
                "-d",
                "/inputs/tree",
                "/outputs/root/root.ext4",
                "8M",
            ],
            env=environment,
            check=True,
        )
        return output / "root.ext4"

    def test_accepts_an_ext4_root_with_os_release(self) -> None:
        root = self.make_ext4({"usr/lib/os-release": 'ID=debian\nPRETTY_NAME="Debian GNU/Linux 13 (trixie)"\n'})
        disk_image.require_populated_root(_LAUNCHER, root)
        self.assertEqual("Debian GNU/Linux 13 (trixie)", disk_image.read_os_release(_LAUNCHER, root)["PRETTY_NAME"])

    def test_rejects_an_empty_ext4_root(self) -> None:
        with self.assertRaisesRegex(AssertionError, "no /usr/lib/os-release; is the root partition empty"):
            disk_image.require_populated_root(_LAUNCHER, self.make_ext4({}))

    def test_rejects_an_empty_erofs_root_and_accepts_a_populated_one(self) -> None:
        superblock = bytearray(2048)
        superblock[1024:1028] = b"\xe2\xe1\xf5\xe0"
        root = self.directory / "root.erofs"
        for inodes, accepted in ((1, False), (12359, True)):
            superblock[1040:1048] = inodes.to_bytes(8, "little")
            root.write_bytes(superblock)
            with self.subTest(inodes=inodes):
                if accepted:
                    disk_image.require_populated_root(_LAUNCHER, root)
                else:
                    with self.assertRaisesRegex(AssertionError, "empty EROFS"):
                        disk_image.require_populated_root(_LAUNCHER, root)

    def test_rejects_a_partition_without_a_file_system(self) -> None:
        root = self.directory / "zeros"
        root.write_bytes(bytes(4096))
        with self.assertRaisesRegex(AssertionError, "no ext4 or EROFS superblock"):
            disk_image.require_populated_root(_LAUNCHER, root)


if __name__ == "__main__":
    _LAUNCHER = sys.argv.pop(1)
    unittest.main()
