"""Unit tests for the reproducibility projection."""

import hashlib
import importlib.util
import json
import os
import pathlib
import sys
import types
import unittest
from typing import IO, Any, BinaryIO
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from bounded_reads import BoundedReader, FileWrapper, wrap_path_open

# The fakes of Path.open() and of the file objects it returns pass their arguments to the real ones unchanged, so they
# take typing.Any arguments (ANN401) instead of repeating the overloads of Path.open() and IO.__exit__().
spec = importlib.util.spec_from_file_location("projection", sys.argv[1])
assert spec is not None and spec.loader is not None
projection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(projection)


class ProjectionTest(unittest.TestCase):
    def test_projection_is_normalized_and_content_addressed(self) -> None:
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

    def test_split_artifact_hashing_streams_sparse_logical_file(self) -> None:
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

        def bound(_path: str | os.PathLike[str], _mode: str, opened: IO[Any]) -> object:
            return BoundedReader(opened, projection._MAX_JSON_BYTES + 1, "reproducibility")

        with (
            mock.patch.object(
                pathlib.Path,
                "read_bytes",
                side_effect=AssertionError("read_bytes is forbidden"),
            ),
            wrap_path_open(bound),
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

    def test_normalized_json_has_explicit_size_limit(self) -> None:
        root = pathlib.Path(os.environ["TEST_TMPDIR"])
        oversized = root / "oversized.json"
        with oversized.open("wb") as output:
            output.seek(projection._MAX_JSON_BYTES)
            output.write(b"}")
        with self.assertRaisesRegex(ValueError, "JSON size limit"):
            projection._small_json(oversized)

    def _minimal_projection_inputs(self) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path, pathlib.Path]:
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

    def test_versioned_verity_image_is_hashed_with_its_slot_label(self) -> None:
        image, metadata, partitions, _ = self._minimal_projection_inputs()
        cases = [
            ({"artifacts": {"verity_metadata": True}, "image": {"id": "os", "version": "7"}}, "os_7"),
            ({"artifacts": {"verity_metadata": False}, "image": {"id": "os", "version": "7"}}, None),
            ({"artifacts": {"verity_metadata": True}, "image": {"id": "os", "version": None}}, None),
            ({}, None),
        ]
        for build_metadata, slot_label in cases:
            with self.subTest(slot_label=slot_label, build_metadata=build_metadata):
                metadata.write_text(json.dumps(build_metadata))
                with mock.patch.object(
                    projection.partition_metadata, "canonical_image_sha256", return_value="a" * 64
                ) as canonical:
                    projection.project(image, metadata, partitions)
                canonical.assert_called_once_with(image, slot_label, "amd64")

    def test_arm64_image_is_hashed_with_its_root_types(self) -> None:
        image, metadata, partitions, _ = self._minimal_projection_inputs()
        partitions.write_text(json.dumps({"architecture": "arm64"}))
        with mock.patch.object(
            projection.partition_metadata, "canonical_image_sha256", return_value="a" * 64
        ) as canonical:
            projection.project(image, metadata, partitions)
        canonical.assert_called_once_with(image, None, "arm64")

    def test_rejects_descriptor_metadata_change_during_hashing(self) -> None:
        image, metadata, partitions, split = self._minimal_projection_inputs()
        calls = [0]

        def changing_stat(source: BinaryIO) -> os.stat_result | types.SimpleNamespace:
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

    def test_rejects_premature_eof_from_same_descriptor(self) -> None:
        image, metadata, partitions, split = self._minimal_projection_inputs()

        class PrematureEof(FileWrapper[bytes]):
            def __init__(self, wrapped: IO[bytes]) -> None:
                super().__init__(wrapped)
                self.returned = False

            def read(self, size: int = -1) -> bytes:
                if self.returned:
                    return b""
                self.returned = True
                return self.wrapped.read(3)

        def end_early(path: str | os.PathLike[str], _mode: str, opened: IO[Any]) -> object:
            return PrematureEof(opened) if path == split else opened

        with (
            mock.patch.object(
                projection.partition_metadata,
                "canonical_image_sha256",
                return_value="a" * 64,
            ),
            wrap_path_open(end_early),
            self.assertRaisesRegex(ValueError, "artifact changed while hashing"),
        ):
            projection.project(image, metadata, partitions, [("root_image", split)])

    def test_rejects_growth_after_reading_only_initial_size_and_one_byte(self) -> None:
        image, metadata, partitions, split = self._minimal_projection_inputs()
        initial_size = split.stat().st_size
        returned = [0]

        class GrowingReader(FileWrapper[bytes]):
            def __init__(self, wrapped: IO[bytes]) -> None:
                super().__init__(wrapped)
                self.grown = False

            def read(self, size: int = -1) -> bytes:
                if size < 0 or size > projection._HASH_CHUNK_SIZE:
                    raise AssertionError("unbounded reproducibility read")
                value = self.wrapped.read(size)
                returned[0] += len(value)
                if not self.grown and returned[0] == initial_size:
                    self.grown = True
                    # The built-in open() is not patched.
                    with open(split, "ab") as output:
                        output.write(b"growth")
                return value

        def grow(path: str | os.PathLike[str], _mode: str, opened: IO[Any]) -> object:
            return GrowingReader(opened) if path == split else opened

        with (
            mock.patch.object(
                projection.partition_metadata,
                "canonical_image_sha256",
                return_value="a" * 64,
            ),
            wrap_path_open(grow),
            self.assertRaisesRegex(ValueError, "artifact changed while hashing"),
        ):
            projection.project(image, metadata, partitions, [("root_image", split)])
        self.assertEqual(initial_size + 1, returned[0])


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
