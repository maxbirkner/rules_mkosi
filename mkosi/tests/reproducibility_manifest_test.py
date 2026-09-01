"""Unit tests for the reproducibility projection."""

import importlib.util
import os
import pathlib
import struct
import sys
import unittest
import uuid


spec = importlib.util.spec_from_file_location("projection", sys.argv[1])
projection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(projection)


class ProjectionTest(unittest.TestCase):
    def test_projection_is_normalized_and_content_addressed(self):
        root = pathlib.Path(os.environ["TEST_TMPDIR"])
        image = root / "image.raw"
        metadata = root / "metadata.json"
        raw = bytearray(1024 * 1024)
        raw[512:520] = b"EFI PART"
        disk_uuid = uuid.UUID("00000000-0000-4000-8000-000000000001")
        raw[568:584] = disk_uuid.bytes_le
        struct.pack_into("<QII", raw, 584, 2, 1, 128)
        root_type = uuid.UUID("4f68bce3-e8cd-4db1-96e7-fbcaf984b709")
        partition_uuid = uuid.UUID("00000000-0000-4000-8000-000000000002")
        raw[1024:1040] = root_type.bytes_le
        raw[1040:1056] = partition_uuid.bytes_le
        struct.pack_into("<QQQ", raw, 1056, 8, 1023, 0)
        superblock = 8 * 512 + 1024
        struct.pack_into("<I", raw, superblock, 32)
        struct.pack_into("<I", raw, superblock + 4, 128)
        raw[superblock + 56:superblock + 58] = b"\x53\xef"
        filesystem_uuid = uuid.UUID("00000000-0000-4000-8000-000000000003")
        hash_seed = uuid.UUID("00000000-0000-4000-8000-000000000004")
        raw[superblock + 104:superblock + 120] = filesystem_uuid.bytes
        raw[superblock + 236:superblock + 252] = hash_seed.bytes
        image.write_bytes(raw)
        metadata.write_text('{"z":2,"a":1}\n')
        result = projection.project(image, metadata)

        self.assertEqual("mkosi-reproducibility-manifest-v1", result["format_version"])
        self.assertEqual(
            [
                "artifact_file_metadata.path",
                "artifact_file_metadata.inode",
                "artifact_file_metadata.ownership",
                "artifact_file_metadata.permissions",
                "artifact_file_metadata.mtime",
                "build_process.output_base",
                "build_process.sandbox_path",
                "build_process.workspace_path",
                "build_process.start_time",
                "build_process.duration",
                "raw_image.sha256",
            ],
            [item["field"] for item in result["excluded_variable_fields"]],
        )
        self.assertEqual(
            {"a": 1, "z": 2},
            result["normalized_manifests"]["build_metadata"],
        )
        self.assertEqual(
            "00000000-0000-4000-8000-000000000003",
            result["normalized_manifests"]["raw_image"]["root_partition"][
                "filesystem"
            ]["uuid"],
        )


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
