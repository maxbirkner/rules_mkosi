#!/usr/bin/python3
"""Stage declared mkosi configuration and source trees."""

import argparse
import os
import pathlib
import shutil


def _copy_tree(source, destination):
    # Runfiles may expose the declared root through a symlink. Resolve only
    # that runfiles indirection; links encountered inside the tree are checked
    # below before being reproduced.
    source = source.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    for root, directories, files in os.walk(source, topdown=True, followlinks=False):
        directories.sort()
        files.sort()
        root_path = pathlib.Path(root)
        relative = root_path.relative_to(source)
        target_root = destination / relative
        target_root.mkdir(parents=True, exist_ok=True)

        for name in list(directories):
            source_path = root_path / name
            target_path = target_root / name
            if source_path.is_symlink():
                directories.remove(name)
                link_target = os.readlink(source_path)
                if os.path.isabs(link_target):
                    raise ValueError("absolute symlink in declared tree: {}".format(source_path))
                resolved = (source_path.parent / link_target).resolve()
                if not resolved.is_relative_to(source):
                    raise ValueError("symlink escapes declared tree: {}".format(source_path))
                target_path.symlink_to(link_target)

        for name in files:
            source_path = root_path / name
            target_path = target_root / name
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if source_path.is_symlink():
                link_target = os.readlink(source_path)
                if os.path.isabs(link_target):
                    raise ValueError("absolute symlink in declared tree: {}".format(source_path))
                resolved = (source_path.parent / link_target).resolve()
                if not resolved.is_relative_to(source):
                    raise ValueError("symlink escapes declared tree: {}".format(source_path))
                target_path.symlink_to(link_target)
            else:
                shutil.copy2(source_path, target_path)


def _copy_file(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)

def _destination_path(output, value):
    if value == ".":
        return output
    path = pathlib.PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts or "" in path.parts:
        raise ValueError("invalid staged destination: {}".format(value))
    return output.joinpath(*path.parts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--mapping", action="append", nargs=2, metavar=("SOURCE", "DESTINATION"), required=True)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    for source_string, destination_string in args.mapping:
        source = pathlib.Path(source_string)
        destination = _destination_path(args.output, destination_string)
        if source.is_dir():
            _copy_tree(source, destination)
        else:
            _copy_file(source, destination)


if __name__ == "__main__":
    main()
