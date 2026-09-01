#!/usr/bin/python3
"""Project immutable mkosi outputs into reviewable normalized JSON."""

import argparse
import hashlib
import json
from pathlib import Path


def _digest(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return {"sha256": digest.hexdigest(), "size": size}


def project(raw_image, build_metadata):
    metadata_bytes = build_metadata.read_bytes()
    metadata = json.loads(metadata_bytes)
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
        ],
        "format_version": "mkosi-reproducibility-manifest-v1",
        "immutable_artifacts": {
            "build_metadata": {
                "sha256": hashlib.sha256(metadata_bytes).hexdigest(),
                "size": len(metadata_bytes),
            },
            "raw_image": _digest(raw_image),
        },
        "normalized_manifests": {
            "build_metadata": metadata,
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-image", type=Path, required=True)
    parser.add_argument("--build-metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(
            project(args.raw_image, args.build_metadata),
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
