#!/usr/bin/python3
"""Stage declared mkosi configuration and source trees."""

import argparse
import os
import pathlib
import shutil


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
    for source_string, destination_string in mappings:
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
        if source.is_dir():
            current = _tree_entries(source, destination, owner)
        elif source.exists():
            path = destination
            if not path:
                raise ValueError("a file mapping requires a destination")
            current = {path: (owner, "file", source, None)}

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
            if target_entry is not None and target_entry[0] != entry[0]:
                raise ValueError("staged symlink aliases another mapping at '{}'".format(path))
    return entries


def _copy_manifest(output, entries):
    for path, (_, kind, source, link_target) in sorted(entries.items()):
        target = output.joinpath(*path.split("/"))
        if kind == "directory":
            target.mkdir(parents=True, exist_ok=True)
        elif kind == "symlink":
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(link_target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--mapping", action="append", nargs=2, metavar=("SOURCE", "DESTINATION"), required=True)
    args = parser.parse_args()

    if args.output.is_symlink():
        raise ValueError("staging output already exists: {}".format(args.output))
    entries = _manifest(args.mapping)
    if args.output.exists():
        if not args.output.is_dir():
            raise ValueError("staging output is not a directory: {}".format(args.output))
        shutil.rmtree(args.output)
    args.output.mkdir(parents=True, exist_ok=True)
    _copy_manifest(args.output, entries)


if __name__ == "__main__":
    main()
