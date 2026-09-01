#!/usr/bin/python3
"""Project immutable mkosi outputs into reviewable normalized JSON."""

import argparse
import hashlib
import json
import struct
import uuid
from pathlib import Path

_LINUX_ROOT_X86_64 = uuid.UUID("4f68bce3-e8cd-4db1-96e7-fbcaf984b709")


def _raw_image_manifest(path):
    with path.open("rb") as image:
        image.seek(512)
        header = image.read(512)
        if header[:8] != b"EFI PART":
            raise ValueError("raw image has no primary GPT header")
        disk_guid = uuid.UUID(bytes_le=header[56:72])
        entries_lba, entry_count, entry_size = struct.unpack_from("<QII", header, 72)
        image.seek(entries_lba * 512)
        entries = image.read(entry_count * entry_size)
        root = None
        for index in range(entry_count):
            entry = entries[index * entry_size:(index + 1) * entry_size]
            if uuid.UUID(bytes_le=entry[:16]) == _LINUX_ROOT_X86_64:
                root = entry
                break
        if root is None:
            raise ValueError("raw image has no Linux x86-64 root partition")
        partition_uuid = uuid.UUID(bytes_le=root[16:32])
        first_lba, last_lba, attributes = struct.unpack_from("<QQQ", root, 32)
        image.seek(first_lba * 512 + 1024)
        superblock = image.read(1024)
        if superblock[56:58] != b"\x53\xef":
            raise ValueError("root partition is not ext4")
        filesystem_uuid = uuid.UUID(bytes=superblock[104:120])
        hash_seed = uuid.UUID(bytes=superblock[236:252])
        blocks = struct.unpack_from("<I", superblock, 4)[0]
        blocks |= struct.unpack_from("<I", superblock, 336)[0] << 32
        return {
            "disk_guid": str(disk_guid),
            "image_size": path.stat().st_size,
            "root_partition": {
                "attributes": attributes,
                "filesystem": {
                    "block_count": blocks,
                    "block_size": 1024 << struct.unpack_from("<I", superblock, 24)[0],
                    "hash_seed": str(hash_seed),
                    "inode_count": struct.unpack_from("<I", superblock, 0)[0],
                    "uuid": str(filesystem_uuid),
                },
                "first_lba": first_lba,
                "last_lba": last_lba,
                "type_uuid": str(_LINUX_ROOT_X86_64),
                "uuid": str(partition_uuid),
            },
        }


def _metadata_projection(path):
    content = path.read_bytes()
    return (
        {
            "sha256": hashlib.sha256(content).hexdigest(),
            "size": len(content),
        },
        json.loads(content),
    )


def project(raw_image, build_metadata, partition_metadata):
    metadata_bytes = build_metadata.read_bytes()
    metadata = json.loads(metadata_bytes)
    partition_artifact, partitions = _metadata_projection(partition_metadata)
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
                "field": "raw_image.sha256",
                "reason": (
                    "ext4 allocation and bookkeeping bytes are not stable; "
                    "the documented GPT/ext4 manifest is compared instead."
                ),
            },
        ],
        "format_version": "mkosi-reproducibility-manifest-v1",
        "immutable_artifacts": {
            "build_metadata": {
                "sha256": hashlib.sha256(metadata_bytes).hexdigest(),
                "size": len(metadata_bytes),
            },
            "partition_metadata": partition_artifact,
        },
        "normalized_manifests": {
            "build_metadata": metadata,
            "partition_metadata": partitions,
            "raw_image": _raw_image_manifest(raw_image),
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
