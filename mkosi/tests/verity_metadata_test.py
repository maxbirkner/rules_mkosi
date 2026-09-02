import hashlib
import json
import struct
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "private"))
import verity_metadata


class VerityMetadataTest(unittest.TestCase):
    def setUp(self):
        self.root = Path("root.raw")
        self.hash = Path("root-verity.raw")
        self.roothash = Path("root.roothash")
        self.partitions = Path("partitions.json")
        self.salt = bytes(range(16))
        self.root.write_bytes(b"A" * 4096 + b"B" * 4096)
        digests = [
            hashlib.sha256(self.salt + block).digest()
            for block in (b"A" * 4096, b"B" * 4096)
        ]
        tree = b"".join(digests).ljust(4096, b"\0")
        root_hash = hashlib.sha256(self.salt + tree).hexdigest()
        superblock = bytearray(512)
        superblock[:8] = b"verity\0\0"
        struct.pack_into("<II", superblock, 8, 1, 1)
        superblock[32:39] = b"sha256\0"
        struct.pack_into("<IIQH", superblock, 64, 4096, 4096, 2, len(self.salt))
        superblock[88:88 + len(self.salt)] = self.salt
        self.hash.write_bytes(bytes(superblock).ljust(4096, b"\0") + tree)
        self.roothash.write_text(root_hash + "\n")
        self._write_partitions(8192, 8192)

    def tearDown(self):
        for path in (self.root, self.hash, self.roothash, self.partitions):
            path.unlink(missing_ok=True)

    def _write_partitions(self, root_size, hash_size):
        self.partitions.write_text(json.dumps({"partitions": [
            {"number": 1, "size_bytes": root_size, "type_guid": verity_metadata.ROOT},
            {"number": 2, "size_bytes": hash_size, "type_guid": verity_metadata.ROOT_VERITY},
        ]}))

    def _project(self):
        return verity_metadata.project(self.roothash, self.partitions, self.root, self.hash)

    def _write_sha1_fixture(self):
        digests = [
            hashlib.sha1(self.salt + block).digest()
            for block in (b"A" * 4096, b"B" * 4096)
        ]
        tree = b"".join(digest.ljust(32, b"\0") for digest in digests).ljust(4096, b"\0")
        superblock = bytearray(512)
        superblock[:8] = b"verity\0\0"
        struct.pack_into("<II", superblock, 8, 1, 1)
        superblock[32:37] = b"sha1\0"
        struct.pack_into("<IIQH", superblock, 64, 4096, 4096, 2, len(self.salt))
        superblock[88:88 + len(self.salt)] = self.salt
        self.hash.write_bytes(bytes(superblock).ljust(4096, b"\0") + tree)
        self.roothash.write_text(hashlib.sha1(self.salt + tree).hexdigest() + "\n")

    def test_verifies_geometry_tree_and_artifacts(self):
        projected = self._project()
        self.assertEqual("sha256", projected["hash_algorithm"])
        self.assertEqual(4096, projected["data_block_size"])
        self.assertEqual(2, projected["data_blocks"])
        self.assertEqual(1, projected["hash_levels"])
        self.assertEqual(4096, projected["tree_offset"])
        self.assertEqual(4096, projected["tree_size"])
        self.assertEqual(hashlib.sha256(self.root.read_bytes()).hexdigest(), projected["artifacts"]["root"]["sha256"])

    def test_rejects_mismatched_partition_extent(self):
        self._write_partitions(12288, 8192)
        with self.assertRaisesRegex(ValueError, "root artifact size"):
            self._project()

    def test_rejects_truncated_hash_artifact(self):
        self.hash.write_bytes(self.hash.read_bytes()[:-1])
        self._write_partitions(8192, 8191)
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self._project()

    def test_rejects_changed_root_byte(self):
        value = bytearray(self.root.read_bytes())
        value[4096] ^= 1
        self.root.write_bytes(value)
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self._project()

    def test_rejects_changed_hash_byte(self):
        value = bytearray(self.hash.read_bytes())
        value[4096] ^= 1
        self.hash.write_bytes(value)
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self._project()

    def test_rejects_wrong_salt(self):
        value = bytearray(self.hash.read_bytes())
        value[88] ^= 1
        self.hash.write_bytes(value)
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self._project()

    def test_rejects_wrong_supplied_root_hash(self):
        self.roothash.write_text("00" * 32)
        with self.assertRaisesRegex(ValueError, "verified root"):
            self._project()

    def test_rejects_nonzero_trailing_padding(self):
        value = bytearray(self.hash.read_bytes())
        value.extend(b"\1")
        self.hash.write_bytes(value)
        self._write_partitions(8192, 8193)
        with self.assertRaisesRegex(ValueError, "trailing"):
            self._project()

    def test_sha1_uses_power_of_two_digest_slots(self):
        self._write_sha1_fixture()
        projected = self._project()
        self.assertEqual(20, projected["digest_size"])
        self.assertEqual(32, projected["digest_slot_size"])

    def test_sha1_rejects_nonzero_digest_slot_padding(self):
        self._write_sha1_fixture()
        value = bytearray(self.hash.read_bytes())
        value[4096 + 20] = 1
        self.hash.write_bytes(value)
        with self.assertRaisesRegex(ValueError, "level 0 block 0"):
            self._project()

    def test_many_blocks_never_use_unbounded_reads(self):
        block_size = 512
        blocks = [bytes([index % 251]) * block_size for index in range(129)]
        self.root.write_bytes(b"".join(blocks))
        leaf_digests = [hashlib.sha256(self.salt + block).digest() for block in blocks]

        def level(values):
            output = []
            for offset in range(0, len(values), 16):
                block = b"".join(values[offset:offset + 16]).ljust(block_size, b"\0")
                output.append((block, hashlib.sha256(self.salt + block).digest()))
            return output

        leaves = level(leaf_digests)
        top = level([digest for _, digest in leaves])
        tree = top[0][0] + b"".join(block for block, _ in leaves)
        superblock = bytearray(512)
        superblock[:8] = b"verity\0\0"
        struct.pack_into("<II", superblock, 8, 1, 1)
        superblock[32:39] = b"sha256\0"
        struct.pack_into("<IIQH", superblock, 64, block_size, block_size, len(blocks), len(self.salt))
        superblock[88:88 + len(self.salt)] = self.salt
        self.hash.write_bytes(bytes(superblock) + tree)
        self.roothash.write_text(top[0][1].hex() + "\n")
        self._write_partitions(len(blocks) * block_size, len(self.hash.read_bytes()))

        original_open = open

        class Guarded:
            def __init__(self, wrapped):
                self.wrapped = wrapped

            def read(self, size=-1):
                if size < 0 or size > 1024 * 1024:
                    raise AssertionError("unbounded verifier read")
                return self.wrapped.read(size)

            def __getattr__(self, name):
                return getattr(self.wrapped, name)

            def __enter__(self):
                self.wrapped.__enter__()
                return self

            def __exit__(self, *args):
                return self.wrapped.__exit__(*args)

        def guarded_open(path, mode="r", *args, **kwargs):
            wrapped = original_open(path, mode, *args, **kwargs)
            return Guarded(wrapped) if "b" in mode else wrapped

        with mock.patch("builtins.open", side_effect=guarded_open):
            projected = self._project()
        self.assertEqual(2, projected["hash_levels"])


if __name__ == "__main__":
    unittest.main()
