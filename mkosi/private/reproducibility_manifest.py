#!/usr/bin/python3
"""Project immutable mkosi outputs into reviewable normalized JSON."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path


def _load_partition_metadata():
    path = Path(__file__).with_name("partition_metadata.py")
    spec = importlib.util.spec_from_file_location("mkosi_partition_metadata", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("partition metadata projector cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


partition_metadata = _load_partition_metadata()
_HASH_CHUNK_SIZE = 1024 * 1024
_MAX_JSON_BYTES = 4 * 1024 * 1024


def _descriptor_stat(source):
    return os.fstat(source.fileno())


def _identity(stat):
    return (
        stat.st_dev,
        stat.st_ino,
        stat.st_size,
        getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)),
        getattr(stat, "st_ctime_ns", int(stat.st_ctime * 1_000_000_000)),
    )


def _artifact_projection(path):
    digest = hashlib.sha256()
    count = 0
    with path.open("rb") as source:
        initial = _descriptor_stat(source)
        remaining = initial.st_size
        while remaining:
            chunk = source.read(min(_HASH_CHUNK_SIZE, remaining))
            if not chunk:
                raise ValueError("artifact changed while hashing: {}".format(path))
            digest.update(chunk)
            count += len(chunk)
            remaining -= len(chunk)
        if source.read(1):
            raise ValueError("artifact changed while hashing: {}".format(path))
        final = _descriptor_stat(source)
    if count != initial.st_size or _identity(initial) != _identity(final):
        raise ValueError("artifact changed while hashing: {}".format(path))
    return {"sha256": digest.hexdigest(), "size": count}


def _small_json(path):
    size = path.stat().st_size
    if size > _MAX_JSON_BYTES:
        raise ValueError("{} exceeds normalized JSON size limit".format(path))
    with path.open("rb") as source:
        content = source.read(_MAX_JSON_BYTES + 1)
    if len(content) != size:
        raise ValueError("{} changed while being projected".format(path))
    return json.loads(content)


def _metadata_projection(path):
    return _artifact_projection(path), _small_json(path)


def project(raw_image, build_metadata, partition_metadata_path, artifacts=()):
    metadata = _small_json(build_metadata)
    partition_artifact, partitions = _metadata_projection(partition_metadata_path)
    result = {
        "excluded_variable_fields": [
            {
                "field": "artifact_file_metadata.path",
                "reason": "The two clean Bazel output bases intentionally have different paths.",
            },
            {
                "field": "artifact_file_metadata.inode",
                "reason": "Filesystem allocation identity is not artifact content.",
            },
            {
                "field": "artifact_file_metadata.ownership",
                "reason": "Output-base ownership is runner state and is not embedded.",
            },
            {
                "field": "artifact_file_metadata.permissions",
                "reason": "Output-base permissions are runner state and are not embedded.",
            },
            {
                "field": "artifact_file_metadata.mtime",
                "reason": "Bazel materialization time is not embedded artifact content.",
            },
            {
                "field": "build_process.output_base",
                "reason": "Independent output bases are required and must differ.",
            },
            {
                "field": "build_process.sandbox_path",
                "reason": "Ephemeral action sandbox identity is not embedded.",
            },
            {
                "field": "build_process.workspace_path",
                "reason": "Checkout location is build-process state and is not embedded.",
            },
            {
                "field": "build_process.start_time",
                "reason": "Wall-clock action timing is not embedded.",
            },
            {
                "field": "build_process.duration",
                "reason": "Runner performance is not artifact content.",
            },
            {
                "field": "raw_image.gpt.disk_guid",
                "reason": "GPT disk identity does not describe payload content.",
            },
            {
                "field": "raw_image.gpt.partitions[].unique_guid",
                "reason": "GPT partition identities do not describe payload content.",
            },
            {
                "field": "raw_image.gpt.primary.partition_array_crc32",
                "reason": "The checksum necessarily changes with normalized partition GUIDs.",
            },
            {
                "field": "raw_image.gpt.backup.partition_array_crc32",
                "reason": "The checksum necessarily changes with normalized partition GUIDs.",
            },
            {
                "field": "raw_image.gpt.primary.header_crc32",
                "reason": "The checksum necessarily changes with the normalized disk GUID and array CRC.",
            },
            {
                "field": "raw_image.gpt.backup.header_crc32",
                "reason": "The checksum necessarily changes with the normalized disk GUID and array CRC.",
            },
        ],
        "format_version": "mkosi-reproducibility-manifest-v1",
        "immutable_artifacts": {
            "build_metadata": _artifact_projection(build_metadata),
            "partition_metadata": partition_artifact,
            "raw_image": {
                "canonical_sha256": partition_metadata.canonical_image_sha256(
                    raw_image
                ),
                "size": raw_image.stat().st_size,
            },
        },
        "normalized_manifests": {
            "build_metadata": metadata,
            "partition_metadata": partitions,
        },
    }
    for role, path in artifacts:
        result["immutable_artifacts"][role] = _artifact_projection(path)
        if role.endswith("_metadata"):
            result["normalized_manifests"][role] = _small_json(path)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-image", type=Path, required=True)
    parser.add_argument("--build-metadata", type=Path, required=True)
    parser.add_argument("--partition-metadata", type=Path, required=True)
    parser.add_argument("--artifact", nargs=2, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(
            project(
                args.raw_image,
                args.build_metadata,
                args.partition_metadata,
                [(role, Path(path)) for role, path in args.artifact],
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
