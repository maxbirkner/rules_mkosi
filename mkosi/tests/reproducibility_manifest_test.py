"""Unit tests for the reproducibility projection."""

import importlib.util
import os
import pathlib
import sys
import unittest


spec = importlib.util.spec_from_file_location("projection", sys.argv[1])
projection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(projection)


class ProjectionTest(unittest.TestCase):
    def test_projection_is_normalized_and_content_addressed(self):
        root = pathlib.Path(os.environ["TEST_TMPDIR"])
        image = root / "image.raw"
        metadata = root / "metadata.json"
        image.write_bytes(b"immutable image")
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
            ],
            [item["field"] for item in result["excluded_variable_fields"]],
        )
        self.assertEqual(
            {"a": 1, "z": 2},
            result["normalized_manifests"]["build_metadata"],
        )
        self.assertEqual(
            "01fb46967bebb2984c75571aedef3fce9a302f741628c5aed6e9e52a5a9604fa",
            result["immutable_artifacts"]["raw_image"]["sha256"],
        )


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
