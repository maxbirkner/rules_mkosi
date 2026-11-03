#!/usr/bin/python3
"""Stage declared mkosi configuration and source trees."""

import argparse
import json
import os
import pathlib
import posixpath
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
    if (
        not link_target
        or "\\" in link_target
        or link_target.startswith("/")
        or link_target.endswith("/")
        or posixpath.normpath(link_target) != link_target
    ):
        raise ValueError(
            "symlink target is not canonical POSIX relative syntax: {}".format(
                source_path
            )
        )
    resolved = (source_path.parent / link_target).resolve()
    if not resolved.is_relative_to(root) or not resolved.exists():
        raise ValueError("symlink escapes or is dangling in declared tree: {}".format(source_path))
    return link_target


def _tree_item_entry(item, source, owner, generated):
    source_path = pathlib.Path(item.path)
    if item.is_symlink():
        if generated and os.path.isabs(os.readlink(source_path)):
            if not source_path.resolve().is_file():
                raise ValueError(
                    "generated tree transport link is not a file: {}".format(
                        source_path
                    )
                )
            return (owner, "file", source_path.resolve(), None)
        return (owner, "symlink", source_path, _check_link(source_path, source))
    if item.is_dir(follow_symlinks=False):
        return (owner, "directory", source_path, None)
    if item.is_file(follow_symlinks=False):
        return (owner, "file", source_path, None)
    raise ValueError("unsupported entry in declared tree: {}".format(source_path))


def _tree_entries(source, destination, owner, generated=False):
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
            child = "/".join(part for part in (destination, relative, item.name) if part)
            entries[child] = _tree_item_entry(item, source, owner, generated)
            if entries[child][1] == "directory":
                visit(entries[child][2], "/".join(part for part in (relative, item.name) if part))

    visit(source, "")
    return entries


_TREE_ROLES = ("tree", "generated-tree")


def _check_source_overlap(canonical_sources, source):
    """Rejects a source that aliases, contains, or is contained in an earlier mapping source."""
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


def _mapping_entries(source, destination, owner, role):
    """Returns the staged entries of one mapping."""
    if role in _TREE_ROLES and not source.is_dir():
        raise ValueError("source-tree mapping must be a directory: {}".format(source))
    if role == "file" and not source.is_file():
        raise ValueError("file mapping must be a regular file: {}".format(source))
    if role in _TREE_ROLES:
        return _tree_entries(source, destination, owner, generated=role == "generated-tree")
    if role != "file":
        raise ValueError("unknown mapping role: {}".format(role))
    if not destination:
        raise ValueError("a file mapping requires a destination")
    return {destination: (owner, "file", source, None)}


def _check_prefix_collisions(entries, destination, owner):
    """Rejects a mapping nested under, or containing, another mapping, even when one side is empty."""
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


def _add_mapping(entries, canonical_sources, source_string, destination_string, role):
    source = pathlib.Path(source_string)
    if not source.exists():
        raise ValueError("declared source does not exist: {}".format(source))
    _check_source_overlap(canonical_sources, source)
    destination = "" if destination_string == "." else _normalise_relative(destination_string)
    owner = "{} -> {}".format(source, destination or ".")
    for path, entry in _mapping_entries(source, destination, owner, role).items():
        prior = entries.get(path)
        if prior is not None and prior[0] != owner:
            raise ValueError("exact staged collision at '{}'".format(path))
        entries[path] = entry
    _check_prefix_collisions(entries, destination, owner)


def _check_staged_symlink(entries, path, entry):
    target = pathlib.PurePosixPath(path).parent / entry[3]
    normalised = pathlib.PurePosixPath(os.path.normpath(str(target)))
    if normalised.is_absolute() or ".." in normalised.parts:
        raise ValueError("staged symlink escapes output root: {}".format(path))
    target_entry = entries.get("/".join(normalised.parts))
    if target_entry is None:
        raise ValueError("staged symlink is dangling at '{}'".format(path))
    if target_entry[0] != entry[0]:
        raise ValueError("staged symlink aliases another mapping at '{}'".format(path))


def _check_layout(entries):
    """Rejects non-directories with staged children and symlinks that leave their own mapping."""
    paths = sorted(entries)
    for index, path in enumerate(paths):
        entry = entries[path]
        for other_path in paths[index + 1 :]:
            if not other_path.startswith(path + "/"):
                break
            if entry[1] != "directory":
                raise ValueError("file/dir staged collision at '{}'".format(path))
        if entry[1] == "symlink":
            _check_staged_symlink(entries, path, entry)


def _manifest(mappings):
    """Build and validate the complete staged manifest without writing."""
    entries = {}
    canonical_sources = {}
    for source_string, destination_string, role in mappings:
        _add_mapping(entries, canonical_sources, source_string, destination_string, role)
    _check_layout(entries)
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


def _executable_paths(executables, entries):
    executable_paths = {
        _normalise_relative(path) for path in executables
    }
    for path in executable_paths:
        if path not in entries or entries[path][1] != "file":
            raise ValueError("executable path is not a staged file: {}".format(path))
    return executable_paths


def _reset_output(output):
    if output.exists():
        if not output.is_dir():
            raise ValueError("staging output is not a directory: {}".format(output))
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)


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
    executable_paths = _executable_paths(args.executable, entries)
    _reset_output(args.output)
    _copy_manifest(args.output, entries, executable_paths)
    if args.manifest:
        _write_manifest(args.manifest, entries, executable_paths)


if __name__ == "__main__":
    main()
