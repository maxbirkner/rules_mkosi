#!/usr/bin/python3
"""Derives an mkosi_image version from everything that its image build action reads.

The digest covers the build action's command line, environment, execution requirements and every input file. Inputs
are identified by their path relative to the execution root, with the configuration segment of bazel-out/<config>/bin
removed, so that neither the sandbox, the output base nor the configuration name changes the version. As when Bazel
digests inputs, symlinks are followed to their content, except artifacts declared as symlinks, which are identified by
their target text, and directories are walked. The version is the first VERSION_LENGTH hex characters of the digest.

An optional manifest lists every hashed input with its digest next to the version, so that the manifests of two builds
show which input changed the version.
"""

import argparse
import hashlib
import json
import os
import re
import runpy
import stat
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, TypeAlias

_load_sibling = runpy.run_path(str(Path(__file__).with_name("sibling_loader.py")))["load_sibling"]
file_hashing = _load_sibling(__file__, "file_hashing")

FORMAT_VERSION = "rules-mkosi-input-digest-v1"
MANIFEST_FORMAT_VERSION = "rules-mkosi-input-manifest-v1"
# INPUT_VERSION_LENGTH in image_identity.bzl bounds image_id with the same length.
VERSION_LENGTH = 16
COMMAND_LINE_MARKER = "--command-line"
_CONFIGURATION_SEGMENT = re.compile(r"bazel-out/[^/]+/bin/")

# A [path, kind, digest, executable] input entry.
_Entry: TypeAlias = list[str | bool]


def stable_path(value: str) -> str:
    """Returns value with every bazel-out/<config>/bin/ prefix replaced by bazel-out/bin/."""
    return _CONFIGURATION_SEGMENT.sub("bazel-out/bin/", value)


def _file_entry(path: str, name: str) -> _Entry:
    """Returns the entry of a regular file, following symlinks."""
    mode = os.stat(path).st_mode
    if not stat.S_ISREG(mode):
        raise ValueError("input is neither a regular file nor a directory: {}".format(path))
    return [name, "file", file_hashing.sha256_file(path), bool(mode & 0o111)]


def _directory_entries(path: str, name: str, ancestors: frozenset[tuple[int, int]]) -> list[_Entry]:
    """Returns the entries of a directory and its descendants, following symlinks."""
    status = os.stat(path)
    identity = (status.st_dev, status.st_ino)
    if identity in ancestors:
        raise ValueError("symlink cycle in input directory: {}".format(path))
    ancestors = ancestors | {identity}
    entries: list[_Entry] = [[name, "directory", "", False]]
    for child in sorted(os.listdir(path)):
        entries.extend(_entries(os.path.join(path, child), name + "/" + child, ancestors))
    return entries


def _entries(path: str, name: str, ancestors: frozenset[tuple[int, int]]) -> list[_Entry]:
    if not os.path.exists(path):
        raise ValueError("input does not exist or is a dangling symlink: {}".format(path))
    if os.path.isdir(path):
        return _directory_entries(path, name, ancestors)
    return [_file_entry(path, name)]


def input_entries(paths: Iterable[str], symlinks: Iterable[str] = ()) -> list[_Entry]:
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


def _stable_json(value: object) -> object:
    """Returns value with stable_path applied to every string in it."""
    if isinstance(value, str):
        return stable_path(value)
    if isinstance(value, list):
        return [_stable_json(item) for item in value]
    if isinstance(value, dict):
        return {key: _stable_json(item) for key, item in value.items()}
    return value


def describe(
    paths: Sequence[str],
    command_line: Sequence[str],
    environment: dict[str, str],
    execution_requirements: dict[str, str],
    symlinks: Sequence[str] = (),
    declared: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Returns the canonical JSON description of an action that digest hashes.

    declared describes inputs that the action does not read but the version covers, such as the roles of signing
    certificates.
    """
    return {
        "command_line": [stable_path(argument) for argument in command_line],
        "declared": _stable_json(declared or {}),
        "environment": {key: stable_path(value) for key, value in environment.items()},
        "execution_requirements": execution_requirements,
        "format_version": FORMAT_VERSION,
        "inputs": input_entries(paths, symlinks),
    }


def hash_description(document: dict[str, Any]) -> str:
    """Returns the lowercase hex SHA-256 of the canonical encoding of a description returned by describe."""
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def digest(
    paths: Sequence[str],
    command_line: Sequence[str],
    environment: dict[str, str],
    execution_requirements: dict[str, str],
    symlinks: Sequence[str] = (),
    declared: dict[str, Any] | None = None,
) -> str:
    """Returns the lowercase hex SHA-256 of the canonical JSON description of an action."""
    return hash_description(describe(paths, command_line, environment, execution_requirements, symlinks, declared))


def build_manifest(document: dict[str, Any], hex_digest: str) -> dict[str, Any]:
    """Returns the manifest of a version: its digest, the hashed description, and every input path with its digest.

    Files map to their SHA-256 and executable bit, declared symlinks to their target text, and directories to their
    kind only, since their entries are listed separately.
    """
    inputs: dict[str, dict[str, Any]] = {}
    for path, kind, content, executable in document["inputs"]:
        if kind == "file":
            inputs[path] = {"executable": executable, "kind": kind, "sha256": content}
        elif kind == "symlink":
            inputs[path] = {"kind": kind, "target": content}
        else:
            inputs[path] = {"kind": kind}
    return {
        "command_line": document["command_line"],
        "declared": document["declared"],
        "digest_format_version": document["format_version"],
        "environment": document["environment"],
        "execution_requirements": document["execution_requirements"],
        "format_version": MANIFEST_FORMAT_VERSION,
        "image_version": hex_digest[:VERSION_LENGTH],
        "input_digest": hex_digest,
        "inputs": inputs,
    }


def _parse(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    if COMMAND_LINE_MARKER not in argv:
        raise SystemExit("IMAGE_INPUT_VERSION_FAILED: missing {}".format(COMMAND_LINE_MARKER))
    split = argv.index(COMMAND_LINE_MARKER)
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs-file", required=True, type=Path)
    parser.add_argument("--symlinks-file", type=Path)
    parser.add_argument("--environment-json", required=True, type=json.loads)
    parser.add_argument("--execution-requirements-json", required=True, type=json.loads)
    parser.add_argument("--declared-json", default={}, type=json.loads)
    parser.add_argument("--version-output", required=True, type=Path)
    parser.add_argument("--digest-output", required=True, type=Path)
    parser.add_argument("--manifest-output", type=Path)
    return parser.parse_args(argv[:split]), argv[split + 1 :]


def main(argv: list[str] | None = None) -> None:
    args, command_line = _parse(sys.argv[1:] if argv is None else argv)
    try:
        paths = args.inputs_file.read_text(encoding="utf-8").splitlines()
        symlinks = args.symlinks_file.read_text(encoding="utf-8").splitlines() if args.symlinks_file else []
        environment, requirements = args.environment_json, args.execution_requirements_json
        document = describe(paths, command_line, environment, requirements, symlinks, args.declared_json)
    except (OSError, ValueError) as error:
        raise SystemExit("IMAGE_INPUT_VERSION_FAILED: {}".format(error)) from error
    hex_digest = hash_description(document)
    args.digest_output.write_text(hex_digest + "\n", encoding="ascii")
    args.version_output.write_text(hex_digest[:VERSION_LENGTH] + "\n", encoding="ascii")
    if args.manifest_output:
        # One input per line, so that a line diff of two manifests names the inputs that changed the version.
        manifest = json.dumps(build_manifest(document, hex_digest), indent=1, sort_keys=True, ensure_ascii=True)
        args.manifest_output.write_text(manifest + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
