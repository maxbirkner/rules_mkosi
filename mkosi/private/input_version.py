#!/usr/bin/python3
"""Derives an mkosi_image version from everything that its image build action reads.

The digest covers the build action's command line, environment, execution requirements and every input file. Inputs
are identified by their path relative to the execution root, with the configuration segment of bazel-out/<config>/bin
removed, so that neither the sandbox, the output base nor the configuration name changes the version. As when Bazel
digests inputs, symlinks are followed to their content, except artifacts declared as symlinks, which are identified by
their target text, and directories are walked. The version is the first VERSION_LENGTH hex characters of the digest.
"""

import argparse
import hashlib
import json
import os
import re
import runpy
import stat
import sys
from pathlib import Path

_load_sibling = runpy.run_path(str(Path(__file__).with_name("sibling_loader.py")))["load_sibling"]
file_hashing = _load_sibling(__file__, "file_hashing")

FORMAT_VERSION = "rules-mkosi-input-digest-v1"
# INPUT_VERSION_LENGTH in image_identity.bzl bounds image_id with the same length.
VERSION_LENGTH = 16
COMMAND_LINE_MARKER = "--command-line"
_CONFIGURATION_SEGMENT = re.compile(r"bazel-out/[^/]+/bin/")


def stable_path(value):
    """Returns value with every bazel-out/<config>/bin/ prefix replaced by bazel-out/bin/."""
    return _CONFIGURATION_SEGMENT.sub("bazel-out/bin/", value)


def _file_entry(path, name):
    """Returns the entry of a regular file, following symlinks."""
    mode = os.stat(path).st_mode
    if not stat.S_ISREG(mode):
        raise ValueError("input is neither a regular file nor a directory: {}".format(path))
    return [name, "file", file_hashing.sha256_file(path), bool(mode & 0o111)]


def _directory_entries(path, name, ancestors):
    """Returns the entries of a directory and its descendants, following symlinks."""
    status = os.stat(path)
    identity = (status.st_dev, status.st_ino)
    if identity in ancestors:
        raise ValueError("symlink cycle in input directory: {}".format(path))
    ancestors = ancestors | {identity}
    entries = [[name, "directory", "", False]]
    for child in sorted(os.listdir(path)):
        entries.extend(_entries(os.path.join(path, child), name + "/" + child, ancestors))
    return entries


def _entries(path, name, ancestors):
    if not os.path.exists(path):
        raise ValueError("input does not exist or is a dangling symlink: {}".format(path))
    if os.path.isdir(path):
        return _directory_entries(path, name, ancestors)
    return [_file_entry(path, name)]


def input_entries(paths, symlinks=()):
    """Returns the sorted [path, kind, digest, executable] entries of the input files, directories and symlinks.

    paths are followed to their content. symlinks are artifacts that Bazel declared as symlinks and identifies by
    their target text, which is recorded without following it.

    Raises:
        ValueError: An input is missing, a dangling symlink, a symlink cycle or a special file.
        OSError: An input cannot be read.
    """
    entries = [entry for path in paths for entry in _entries(path, stable_path(path), frozenset())]
    entries += [[stable_path(path), "symlink", stable_path(os.readlink(path)), False] for path in symlinks]
    return sorted(entries)


def digest(paths, command_line, environment, execution_requirements, symlinks=()):
    """Returns the lowercase hex SHA-256 of the canonical JSON description of an action."""
    document = {
        "command_line": [stable_path(argument) for argument in command_line],
        "environment": {key: stable_path(value) for key, value in environment.items()},
        "execution_requirements": execution_requirements,
        "format_version": FORMAT_VERSION,
        "inputs": input_entries(paths, symlinks),
    }
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _parse(argv):
    if COMMAND_LINE_MARKER not in argv:
        raise SystemExit("IMAGE_INPUT_VERSION_FAILED: missing {}".format(COMMAND_LINE_MARKER))
    split = argv.index(COMMAND_LINE_MARKER)
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs-file", required=True, type=Path)
    parser.add_argument("--symlinks-file", type=Path)
    parser.add_argument("--environment-json", required=True, type=json.loads)
    parser.add_argument("--execution-requirements-json", required=True, type=json.loads)
    parser.add_argument("--version-output", required=True, type=Path)
    parser.add_argument("--digest-output", required=True, type=Path)
    return parser.parse_args(argv[:split]), argv[split + 1 :]


def main(argv=None):
    args, command_line = _parse(sys.argv[1:] if argv is None else argv)
    try:
        paths = args.inputs_file.read_text(encoding="utf-8").splitlines()
        symlinks = args.symlinks_file.read_text(encoding="utf-8").splitlines() if args.symlinks_file else []
        environment, requirements = args.environment_json, args.execution_requirements_json
        hex_digest = digest(paths, command_line, environment, requirements, symlinks)
    except (OSError, ValueError) as error:
        raise SystemExit("IMAGE_INPUT_VERSION_FAILED: {}".format(error)) from error
    args.digest_output.write_text(hex_digest + "\n", encoding="ascii")
    args.version_output.write_text(hex_digest[:VERSION_LENGTH] + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
