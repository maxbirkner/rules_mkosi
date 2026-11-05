#!/usr/bin/python3
"""Project immutable mkosi outputs into reviewable normalized JSON."""

import argparse
import hashlib
import json
import os
import runpy
from pathlib import Path

_load_sibling = runpy.run_path(str(Path(__file__).with_name("sibling_loader.py")))["load_sibling"]
partition_metadata = _load_sibling(__file__, "partition_metadata")
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


_EXCLUDED_VARIABLE_FIELDS = (
    (
        "artifact_file_metadata.path",
        "The two clean Bazel output bases intentionally have different paths.",
    ),
    ("artifact_file_metadata.inode", "Filesystem allocation identity is not artifact content."),
    ("artifact_file_metadata.ownership", "Output-base ownership is runner state and is not embedded."),
    ("artifact_file_metadata.permissions", "Output-base permissions are runner state and are not embedded."),
    ("artifact_file_metadata.mtime", "Bazel materialization time is not embedded artifact content."),
    ("build_process.output_base", "Independent output bases are required and must differ."),
    ("build_process.sandbox_path", "Ephemeral action sandbox identity is not embedded."),
    ("build_process.workspace_path", "Checkout location is build-process state and is not embedded."),
    ("build_process.start_time", "Wall-clock action timing is not embedded."),
    ("build_process.duration", "Runner performance is not artifact content."),
    ("raw_image.gpt.disk_guid", "GPT disk identity does not describe payload content."),
    ("raw_image.gpt.partitions[].unique_guid", "GPT partition identities do not describe payload content."),
    (
        "raw_image.gpt.primary.partition_array_crc32",
        "The checksum necessarily changes with normalized partition GUIDs.",
    ),
    (
        "raw_image.gpt.backup.partition_array_crc32",
        "The checksum necessarily changes with normalized partition GUIDs.",
    ),
    (
        "raw_image.gpt.primary.header_crc32",
        "The checksum necessarily changes with the normalized disk GUID and array CRC.",
    ),
    (
        "raw_image.gpt.backup.header_crc32",
        "The checksum necessarily changes with the normalized disk GUID and array CRC.",
    ),
)


def _slot_label(metadata):
    """Returns the A/B slot label of a versioned dm-verity image's root partitions, or None."""
    image = metadata.get("image") or {}
    if (metadata.get("artifacts") or {}).get("verity_metadata") and image.get("version"):
        return "{}_{}".format(image["id"], image["version"])
    return None


def project(raw_image, build_metadata, partition_metadata_path, artifacts=()):
    metadata = _small_json(build_metadata)
    partition_artifact, partitions = _metadata_projection(partition_metadata_path)
    result = {
        "excluded_variable_fields": [{"field": field, "reason": reason} for field, reason in _EXCLUDED_VARIABLE_FIELDS],
        "format_version": "mkosi-reproducibility-manifest-v1",
        "immutable_artifacts": {
            "build_metadata": _artifact_projection(build_metadata),
            "partition_metadata": partition_artifact,
            "raw_image": {
                "canonical_sha256": partition_metadata.canonical_image_sha256(raw_image, _slot_label(metadata)),
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
