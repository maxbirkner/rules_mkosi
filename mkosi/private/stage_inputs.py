#!/usr/bin/python3
"""Stage declared mkosi configuration and source trees."""

import argparse
import json
import os
import pathlib
import shutil

_EPOCH = (0, 0)


def _normalise_relative(path):
    parts = pathlib.PurePosixPath(path).parts
    if not parts or pathlib.PurePosixPath(path).is_absolute() or any(
        part in ("", ".", "..") for part in parts
    ):
        raise ValueError("invalid staged path: {}".format(path))
    return "/".join(parts)


def _check_link(source_path, root):
    link_target = os.readlink(source_path)
    if os.path.isabs(link_target):
        raise ValueError("absolute symlink in declared tree: {}".format(source_path))
    resolved = (source_path.parent / link_target).resolve()
    if not resolved.is_relative_to(root) or not resolved.exists():
        raise ValueError("symlink escapes or is dangling in declared tree: {}".format(source_path))
    return link_target


def _tree_entries(source, destination, owner):
    """Returns every entry in a declared tree before touching the output."""
    source = source.resolve()
    if not source.is_dir():
        raise ValueError("{} is not a directory".format(source))

    entries = {}
    destination = destination.rstrip("/")
    if destination:
        entries[destination] = (owner, "directory", source, None)

    def visit(source_dir, relative):
        for item in sorted(os.scandir(source_dir), key=lambda entry: entry.name):
            source_path = pathlib.Path(item.path)
            child = "/".join(part for part in (destination, relative, item.name) if part)
            if item.is_symlink():
                link_target = _check_link(source_path, source)
                entries[child] = (owner, "symlink", source_path, link_target)
            elif item.is_dir(follow_symlinks=False):
                entries[child] = (owner, "directory", source_path, None)
                visit(source_path, "/".join(part for part in (relative, item.name) if part))
            elif item.is_file(follow_symlinks=False):
                entries[child] = (owner, "file", source_path, None)
            else:
                raise ValueError("unsupported entry in declared tree: {}".format(source_path))

    visit(source, "")
    return entries


def _manifest(mappings):
    """Build and validate the complete staged manifest without writing."""
    entries = {}
    canonical_sources = {}
    for source_string, destination_string, role in mappings:
        source = pathlib.Path(source_string)
        if not source.exists():
            raise ValueError("declared source does not exist: {}".format(source))
        canonical = source.resolve()
        for prior_canonical, prior_source in canonical_sources.items():
            if (
                canonical == prior_canonical
                or canonical.is_relative_to(prior_canonical)
                or prior_canonical.is_relative_to(canonical)
            ):
                raise ValueError(
                    "source alias '{}' and '{}' overlap at '{}'".format(
                        prior_source, source, canonical
                    )
                )
        canonical_sources[canonical] = source
        destination = "" if destination_string == "." else _normalise_relative(destination_string)
        owner = "{} -> {}".format(source, destination or ".")
        if role == "tree" and not source.is_dir():
            raise ValueError("source-tree mapping must be a directory: {}".format(source))
        if role == "file" and not source.is_file():
            raise ValueError("file mapping must be a regular file: {}".format(source))
        if role == "tree":
            current = _tree_entries(source, destination, owner)
        elif role == "file":
            path = destination
            if not path:
                raise ValueError("a file mapping requires a destination")
            current = {path: (owner, "file", source, None)}
        else:
            raise ValueError("unknown mapping role: {}".format(role))

        for path, entry in current.items():
            prior = entries.get(path)
            if prior is not None and prior[0] != owner:
                raise ValueError("exact staged collision at '{}'".format(path))
            entries[path] = entry

        # A mapping may not be nested under, or contain, another mapping.
        # This catches file/dir collisions even when one side is empty.
        for prior_path, prior in entries.items():
            if prior[0] == owner or not destination or not prior_path:
                continue
            config_directory_contains_mapping = (
                destination.startswith(prior_path + "/")
                and prior[1] == "directory"
                and prior[0].endswith(" -> .")
            )
            if config_directory_contains_mapping:
                continue
            if (
                destination == prior_path
                or destination.startswith(prior_path + "/")
                or prior_path.startswith(destination + "/")
            ):
                raise ValueError(
                    "prefix staged collision between '{}' and '{}'".format(
                        destination, prior_path
                    )
                )

    paths = sorted(entries)
    for index, path in enumerate(paths):
        entry = entries[path]
        for other_path in paths[index + 1 :]:
            if not other_path.startswith(path + "/"):
                break
            if entry[1] != "directory":
                raise ValueError("file/dir staged collision at '{}'".format(path))

        if entry[1] == "symlink":
            target = pathlib.PurePosixPath(path).parent / entry[3]
            normalised = pathlib.PurePosixPath(os.path.normpath(str(target)))
            if normalised.is_absolute() or ".." in normalised.parts:
                raise ValueError("staged symlink escapes output root: {}".format(path))
            target_path = "/".join(normalised.parts)
            target_entry = entries.get(target_path)
            if target_entry is None:
                raise ValueError("staged symlink is dangling at '{}'".format(path))
            if target_entry[0] != entry[0]:
                raise ValueError("staged symlink aliases another mapping at '{}'".format(path))
    return entries


def _copy_manifest(output, entries, executable_paths):
    directories = {output}
    for path, (_, kind, _, _) in entries.items():
        parts = path.split("/")
        directories.update(
            output.joinpath(*parts[:index])
            for index in range(1, len(parts) + 1)
            if index < len(parts) or kind == "directory"
        )
    for path, (_, kind, source, link_target) in sorted(entries.items()):
        target = output.joinpath(*path.split("/"))
        if kind == "directory":
            target.mkdir(parents=True, exist_ok=True)
    for path, (_, kind, source, link_target) in sorted(entries.items()):
        target = output.joinpath(*path.split("/"))
        if kind == "symlink":
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(link_target)
            os.utime(target, _EPOCH, follow_symlinks=False)
        elif kind == "file":
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            os.chmod(target, 0o755 if path in executable_paths else 0o644)
            os.utime(target, _EPOCH)
    for target in sorted(directories, reverse=True):
        os.chmod(target, 0o755)
        os.utime(target, _EPOCH, follow_symlinks=False)


def _write_manifest(path, entries, executable_paths):
    manifest = []
    for staged_path, (_, kind, _, link_target) in sorted(entries.items()):
        manifest.append({
            "path": staged_path,
            "kind": kind,
            "link_target": link_target,
            "mode": 0o755 if staged_path in executable_paths else 0o644,
        })
    path.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument(
        "--mapping",
        action="append",
        nargs=3,
        metavar=("SOURCE", "DESTINATION", "ROLE"),
        required=True,
    )
    parser.add_argument("--executable", action="append", default=[])
    parser.add_argument("--manifest", type=pathlib.Path)
    args = parser.parse_args()

    if args.output.is_symlink():
        raise ValueError("staging output already exists: {}".format(args.output))
    entries = _manifest(args.mapping)
    executable_paths = {
        _normalise_relative(path) for path in args.executable
    }
    for path in executable_paths:
        if path not in entries or entries[path][1] != "file":
            raise ValueError("executable path is not a staged file: {}".format(path))
    if args.output.exists():
        if not args.output.is_dir():
            raise ValueError("staging output is not a directory: {}".format(args.output))
        shutil.rmtree(args.output)
    args.output.mkdir(parents=True, exist_ok=True)
    _copy_manifest(args.output, entries, executable_paths)
    if args.manifest:
        _write_manifest(args.manifest, entries, executable_paths)


if __name__ == "__main__":
    main()
