"""Unit tests for the reproducibility projection."""

import importlib.util
import hashlib
import os
import pathlib
import sys
import types
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

    def test_split_artifact_hashing_streams_sparse_logical_file(self):
        root = pathlib.Path(os.environ["TEST_TMPDIR"])
        image = root / "image.raw"
        metadata = root / "metadata.json"
        partitions = root / "partitions.json"
        split = root / "root.raw"
        image.write_bytes(b"raw")
        metadata.write_text("{}")
        partitions.write_text("{}")
        logical_size = 64 * 1024 * 1024 + 1
        with split.open("wb") as output:
            output.seek(logical_size - 1)
            output.write(b"X")

        expected = hashlib.sha256()
        zeroes = b"\0" * (1024 * 1024)
        for _ in range(64):
            expected.update(zeroes)
        expected.update(b"X")

        original_open = pathlib.Path.open

        class Guarded:
            def __init__(self, wrapped):
                self.wrapped = wrapped

            def read(self, size=-1):
                if size < 0 or size > projection._MAX_JSON_BYTES + 1:
                    raise AssertionError("unbounded reproducibility read")
                return self.wrapped.read(size)

            def __getattr__(self, name):
                return getattr(self.wrapped, name)

            def __enter__(self):
                self.wrapped.__enter__()
                return self

            def __exit__(self, *args):
                return self.wrapped.__exit__(*args)

        def guarded_open(path, *args, **kwargs):
            return Guarded(original_open(path, *args, **kwargs))

        with (
            mock.patch.object(
                pathlib.Path,
                "read_bytes",
                side_effect=AssertionError("read_bytes is forbidden"),
            ),
            mock.patch.object(pathlib.Path, "open", guarded_open),
            mock.patch.object(
                projection.partition_metadata,
                "canonical_image_sha256",
                return_value="a" * 64,
            ),
        ):
            result = projection.project(
                image,
                metadata,
                partitions,
                [("root_image", split)],
            )
        self.assertEqual(
            {"sha256": expected.hexdigest(), "size": logical_size},
            result["immutable_artifacts"]["root_image"],
        )

    def test_normalized_json_has_explicit_size_limit(self):
        root = pathlib.Path(os.environ["TEST_TMPDIR"])
        oversized = root / "oversized.json"
        with oversized.open("wb") as output:
            output.seek(projection._MAX_JSON_BYTES)
            output.write(b"}")
        with self.assertRaisesRegex(ValueError, "JSON size limit"):
            projection._small_json(oversized)

    def _minimal_projection_inputs(self):
        root = pathlib.Path(os.environ["TEST_TMPDIR"])
        image = root / "change-image.raw"
        metadata = root / "change-metadata.json"
        partitions = root / "change-partitions.json"
        split = root / "change-root.raw"
        image.write_bytes(b"raw")
        metadata.write_text("{}")
        partitions.write_text("{}")
        split.write_bytes(b"split artifact")
        return image, metadata, partitions, split

    def test_rejects_descriptor_metadata_change_during_hashing(self):
        image, metadata, partitions, split = self._minimal_projection_inputs()
        calls = [0]

        def changing_stat(source):
            stat = os.fstat(source.fileno())
            if source.name != str(split):
                return stat
            calls[0] += 1
            if calls[0] == 1:
                return stat
            return types.SimpleNamespace(
                st_dev=stat.st_dev,
                st_ino=stat.st_ino,
                st_size=stat.st_size,
                st_mtime=stat.st_mtime,
                st_mtime_ns=stat.st_mtime_ns + 1,
                st_ctime=stat.st_ctime,
                st_ctime_ns=stat.st_ctime_ns,
            )

        with (
            mock.patch.object(
                projection.partition_metadata,
                "canonical_image_sha256",
                return_value="a" * 64,
            ),
            mock.patch.object(projection, "_descriptor_stat", side_effect=changing_stat),
            self.assertRaisesRegex(ValueError, "artifact changed while hashing"),
        ):
            projection.project(image, metadata, partitions, [("root_image", split)])

    def test_rejects_premature_eof_from_same_descriptor(self):
        image, metadata, partitions, split = self._minimal_projection_inputs()
        original_open = pathlib.Path.open

        class PrematureEof:
            def __init__(self, wrapped):
                self.wrapped = wrapped
                self.returned = False

            def read(self, size=-1):
                if self.returned:
                    return b""
                self.returned = True
                return self.wrapped.read(3)

            def __getattr__(self, name):
                return getattr(self.wrapped, name)

            def __enter__(self):
                self.wrapped.__enter__()
                return self

            def __exit__(self, *args):
                return self.wrapped.__exit__(*args)

        def premature_open(path, *args, **kwargs):
            opened = original_open(path, *args, **kwargs)
            return PrematureEof(opened) if path == split else opened

        with (
            mock.patch.object(
                projection.partition_metadata,
                "canonical_image_sha256",
                return_value="a" * 64,
            ),
            mock.patch.object(pathlib.Path, "open", premature_open),
            self.assertRaisesRegex(ValueError, "artifact changed while hashing"),
        ):
            projection.project(image, metadata, partitions, [("root_image", split)])

    def test_rejects_growth_after_reading_only_initial_size_and_one_byte(self):
        image, metadata, partitions, split = self._minimal_projection_inputs()
        original_open = pathlib.Path.open
        initial_size = split.stat().st_size
        returned = [0]

        class GrowingReader:
            def __init__(self, wrapped):
                self.wrapped = wrapped
                self.grown = False

            def read(self, size=-1):
                if size < 0 or size > projection._HASH_CHUNK_SIZE:
                    raise AssertionError("unbounded reproducibility read")
                value = self.wrapped.read(size)
                returned[0] += len(value)
                if not self.grown and returned[0] == initial_size:
                    self.grown = True
                    with original_open(split, "ab") as output:
                        output.write(b"growth")
                return value

            def __getattr__(self, name):
                return getattr(self.wrapped, name)

            def __enter__(self):
                self.wrapped.__enter__()
                return self

            def __exit__(self, *args):
                return self.wrapped.__exit__(*args)

        def growing_open(path, *args, **kwargs):
            opened = original_open(path, *args, **kwargs)
            return GrowingReader(opened) if path == split else opened

        with (
            mock.patch.object(
                projection.partition_metadata,
                "canonical_image_sha256",
                return_value="a" * 64,
            ),
            mock.patch.object(pathlib.Path, "open", growing_open),
            self.assertRaisesRegex(ValueError, "artifact changed while hashing"),
        ):
            projection.project(image, metadata, partitions, [("root_image", split)])
        self.assertEqual(initial_size + 1, returned[0])


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
