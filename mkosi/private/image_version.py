#!/usr/bin/python3
"""Execution-time validation of os-release IMAGE_VERSION values read from Bazel files.

This mirrors validate_image_version in image_identity.bzl for versions that are only known when an action runs,
such as versions produced by a stamped genrule. It is a module for the other action scripts and a command that
writes build metadata whose image version comes from such a file.
"""

import argparse
import json
from pathlib import Path

VERSION_CHARACTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.")


def validate_image_version(image_version):
    """Returns image_version, or raises ValueError unless it is non-empty and uses only letters, digits and '.'.

    systemd-sysupdate accepts only letters, digits and ".,_-+" in a version. '_' separates the image id from the
    version and '+'/'-' introduce systemd-boot boot-counting suffixes, so a version is restricted further.
    """
    if not image_version or not VERSION_CHARACTERS.issuperset(image_version):
        raise ValueError(
            "image_version must be non-empty and use only letters, digits and '.': {!r}".format(image_version)
        )
    return image_version


def read_image_version(path):
    """Returns the validated version stored in path, which may end with one newline.

    Raises:
        ValueError: The file is not UTF-8 or does not contain a valid version.
        OSError: The file cannot be read.
    """
    try:
        content = Path(path).read_bytes().decode("utf-8")
        return validate_image_version(content.removesuffix("\n"))
    except ValueError as error:
        raise ValueError("invalid image_version_file {}: {}".format(path, error)) from None


def write_build_metadata(metadata_json, image_version_file, output):
    """Writes build metadata with image.version taken from image_version_file.

    The encoding matches Starlark's json.encode, which the rule uses when the version is known during analysis.
    """
    metadata = json.loads(metadata_json)
    metadata["image"]["version"] = read_image_version(image_version_file)
    Path(output).write_text(json.dumps(metadata, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    metadata_parser = commands.add_parser("build-metadata")
    metadata_parser.add_argument("--metadata-json", required=True)
    metadata_parser.add_argument("--image-version-file", required=True)
    metadata_parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        write_build_metadata(args.metadata_json, args.image_version_file, args.output)
    except (OSError, ValueError) as error:
        raise SystemExit("IMAGE_VERSION_INVALID: {}".format(error))


if __name__ == "__main__":
    main()
