#!/usr/bin/python3
"""Project immutable mkosi outputs into reviewable normalized JSON."""

import argparse
import hashlib
import json
from pathlib import Path

import mkosi.private.partition_metadata as partition_metadata


def _metadata_projection(path):
    content = path.read_bytes()
    return (
        {
            "sha256": hashlib.sha256(content).hexdigest(),
            "size": len(content),
        },
        json.loads(content),
    )


def project(raw_image, build_metadata, partition_metadata_path):
    metadata_bytes = build_metadata.read_bytes()
    metadata = json.loads(metadata_bytes)
    partition_artifact, partitions = _metadata_projection(partition_metadata_path)
    return {
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
            "build_metadata": {
                "sha256": hashlib.sha256(metadata_bytes).hexdigest(),
                "size": len(metadata_bytes),
            },
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-image", type=Path, required=True)
    parser.add_argument("--build-metadata", type=Path, required=True)
    parser.add_argument("--partition-metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(
            project(args.raw_image, args.build_metadata, args.partition_metadata),
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
