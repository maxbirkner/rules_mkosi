"""Unit tests for the reproducibility projection."""

import importlib.util
import os
import pathlib
import sys
import unittest
from unittest import mock


spec = importlib.util.spec_from_file_location("projection", sys.argv[1])
projection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(projection)


class ProjectionTest(unittest.TestCase):
    def test_projection_is_normalized_and_content_addressed(self):
        root = pathlib.Path(os.environ["TEST_TMPDIR"])
        image = root / "image.raw"
        metadata = root / "metadata.json"
        partitions = root / "partitions.json"
        image.write_bytes(b"raw payload")
        metadata.write_text('{"z":2,"a":1}\n')
        partitions.write_text('{"format_version":"mkosi-partitions-v1"}\n')
        with mock.patch.object(
            projection.partition_metadata,
            "canonical_image_sha256",
            return_value="a" * 64,
        ):
            result = projection.project(image, metadata, partitions)

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
                "raw_image.gpt.disk_guid",
                "raw_image.gpt.partitions[].unique_guid",
                "raw_image.gpt.primary.partition_array_crc32",
                "raw_image.gpt.backup.partition_array_crc32",
                "raw_image.gpt.primary.header_crc32",
                "raw_image.gpt.backup.header_crc32",
            ],
            [item["field"] for item in result["excluded_variable_fields"]],
        )
        self.assertEqual(
            {"a": 1, "z": 2},
            result["normalized_manifests"]["build_metadata"],
        )
        self.assertEqual(
            "a" * 64,
            result["immutable_artifacts"]["raw_image"]["canonical_sha256"],
        )
        self.assertEqual(
            {"format_version": "mkosi-partitions-v1"},
            result["normalized_manifests"]["partition_metadata"],
        )
        self.assertEqual(
            64,
            len(result["immutable_artifacts"]["partition_metadata"]["sha256"]),
        )


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
