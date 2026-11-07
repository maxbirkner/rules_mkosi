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
    if not parts or pathlib.PurePosixPath(path).is_absolute() or any(part in ("", ".", "..") for part in parts):
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
        raise ValueError("symlink target is not canonical POSIX relative syntax: {}".format(source_path))
    resolved = (source_path.parent / link_target).resolve()
    if not resolved.is_relative_to(root) or not resolved.exists():
        raise ValueError("symlink escapes or is dangling in declared tree: {}".format(source_path))
    return link_target


def _tree_item_entry(item, source, owner, generated):
    source_path = pathlib.Path(item.path)
    if item.is_symlink():
        if generated and os.path.isabs(os.readlink(source_path)):
            if not source_path.resolve().is_file():
                raise ValueError("generated tree transport link is not a file: {}".format(source_path))
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
            raise ValueError("source alias '{}' and '{}' overlap at '{}'".format(prior_source, source, canonical))
    canonical_sources[canonical] = source


_WRAP_HINT = (
    "map it through trees with mkosi_config_tree(src = ...), which keeps relative links and rejects absolute ones"
)
# Bazel reaches a source file through at most a sandbox link, an execroot link and a repository link.
_MAX_BAZEL_LINKS = 8
_REPOSITORY_MARKERS = ("MODULE.bazel", "REPO.bazel", "WORKSPACE", "WORKSPACE.bazel")


def _is_repository_root(directory):
    return any((directory / name).is_file() for name in _REPOSITORY_MARKERS)


def _is_bazel_tree(directory):
    """Whether Bazel laid out directory: the execroot, which links the main repository's files, or a fetched
    repository below <output_base>/external, which Bazel marks with @<name>.marker."""
    if any((directory / name).is_symlink() for name in _REPOSITORY_MARKERS):
        return True
    resolved = directory.resolve()
    return resolved.parent.name == "external" and (resolved.parent / "@{}.marker".format(resolved.name)).is_file()


def _is_source_checkout(directory):
    return _is_repository_root(directory) and not _is_bazel_tree(directory)


def _mirrors(repository, directory):
    """Whether repository links every entry of directory, as new_local_repository lays out a repository."""
    try:
        names = os.listdir(directory)
    except OSError:
        return False
    return bool(names) and all(
        os.path.islink(repository / name) and os.readlink(repository / name) == os.path.join(directory, name)
        for name in names
    )


def _bazel_hop(link, parts, index, repository_depth):
    """Returns (root, consumed parts) to restart from if link is one of Bazel's own, otherwise None.

    A sandbox, runfiles or execroot link points at the same path below a repository root or an output base. A link at
    the top of a repository points at the same name in a repository root, or mirrors a new_local_repository directory.
    """
    target = os.readlink(link)
    if not os.path.isabs(target):
        return None
    prefix = "/".join(parts[: index + 1])
    if target != "/" + prefix and target.endswith("/" + prefix):
        root = pathlib.Path(target[: len(target) - len(prefix)])
        output_base = parts[0] == "external" and (root / "external" / "@{}.marker".format(parts[1])).is_file()
        if _is_repository_root(root) or output_base:
            return root, 0
    directory = pathlib.Path(target).parent
    top_level = index == repository_depth and pathlib.Path(target).name == parts[index]
    if top_level and (_is_repository_root(directory) or _mirrors(link.parent, directory)):
        return directory, index
    return None


def _walk_source_file(root, parts, package_depth, source):
    """Walks parts below root and returns (root, consumed parts) after one of Bazel's links, or None at the file.

    Bazel's links are only followed until the walk enters a source checkout, so links inside it fail.
    """
    repository_depth = 2 if parts[0] == "external" else 0
    in_checkout = repository_depth == 0 and _is_source_checkout(root)
    current = root
    for index, part in enumerate(parts):
        current = current / part
        if current.is_symlink():
            hop = None if in_checkout else _bazel_hop(current, parts, index, repository_depth)
            if hop is not None:
                return hop
            if index >= package_depth:
                raise ValueError(
                    "source file {} is a symlink or lies below one at {}; Bazel would copy what it points to, "
                    "so {}".format(source, "/".join(parts[: index + 1]), _WRAP_HINT)
                )
        if index + 1 == repository_depth:
            in_checkout = _is_source_checkout(current)
    return None


def _check_source_file(source, package):
    """Rejects a declared source file that is, or lies below, a symlink inside its package.

    Only Bazel's own sandbox, runfiles, execroot and repository links are followed.
    """
    if package and not source.startswith(package + "/"):
        raise ValueError("source file {} is not below its package {}".format(source, package))
    parts = source.split("/")
    package_depth = len(package.split("/")) if package else 0
    root, consumed = pathlib.Path("."), 0
    for _ in range(_MAX_BAZEL_LINKS):
        hop = _walk_source_file(root, parts[consumed:], package_depth - consumed, source)
        if hop is None:
            return
        root, consumed = hop[0], consumed + hop[1]
    raise ValueError("source file {} is behind too many links".format(source))


def _mapping_entries(source, destination, owner, role):
    """Returns the staged entries of one mapping."""
    if role in _TREE_ROLES and not source.is_dir():
        raise ValueError("source-tree mapping must be a directory: {}".format(source))
    if role == "source-file" and source.is_dir():
        raise ValueError("source file mapping {} is a directory; {}".format(source, _WRAP_HINT))
    if role in ("file", "source-file") and not source.is_file():
        raise ValueError("file mapping must be a regular file: {}".format(source))
    if role in _TREE_ROLES:
        return _tree_entries(source, destination, owner, generated=role == "generated-tree")
    if role not in ("file", "source-file"):
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
            destination.startswith(prior_path + "/") and prior[1] == "directory" and prior[0].endswith(" -> .")
        )
        if config_directory_contains_mapping:
            continue
        if (
            destination == prior_path
            or destination.startswith(prior_path + "/")
            or prior_path.startswith(destination + "/")
        ):
            raise ValueError("prefix staged collision between '{}' and '{}'".format(destination, prior_path))


def _add_mapping(entries, canonical_sources, mapping, merge, shared_owners):
    """Adds one mapping; merge allows shared sources and merged directories, but still rejects colliding files.

    shared_owners collects every mapping that contributes a merged directory.
    """
    source_string, destination_string, role = mapping
    source = pathlib.Path(source_string)
    if not source.exists():
        raise ValueError("declared source does not exist: {}".format(source))
    if not merge:
        _check_source_overlap(canonical_sources, source)
    destination = "" if destination_string == "." else _normalise_relative(destination_string)
    owner = "{} -> {}".format(source, destination or ".")
    for path, entry in _mapping_entries(source, destination, owner, role).items():
        prior = entries.get(path)
        merged = merge and prior is not None and prior[1] == entry[1] == "directory"
        if prior is not None and prior[0] != owner and not merged:
            raise ValueError("exact staged collision at '{}'".format(path))
        if merged:
            shared_owners.setdefault(path, {prior[0]}).add(owner)
        else:
            entries[path] = entry
    if not merge:
        _check_prefix_collisions(entries, destination, owner)


def _check_staged_symlink(entries, path, entry, shared_owners):
    target = pathlib.PurePosixPath(path).parent / entry[3]
    normalised = pathlib.PurePosixPath(os.path.normpath(str(target)))
    if normalised.is_absolute() or ".." in normalised.parts:
        raise ValueError("staged symlink escapes output root: {}".format(path))
    target_path = "/".join(normalised.parts)
    target_entry = entries.get(target_path)
    if target_entry is None:
        raise ValueError("staged symlink is dangling at '{}'".format(path))
    if target_entry[0] != entry[0] and entry[0] not in shared_owners.get(target_path, ()):
        raise ValueError("staged symlink aliases another mapping at '{}'".format(path))


def _check_layout(entries, shared_owners):
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
            _check_staged_symlink(entries, path, entry, shared_owners)


def _manifest(mappings, merge=False):
    """Build and validate the complete staged manifest without writing."""
    entries = {}
    canonical_sources = {}
    shared_owners = {}
    for mapping in mappings:
        _add_mapping(entries, canonical_sources, mapping, merge, shared_owners)
    _check_layout(entries, shared_owners)
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
    for path, (_, kind, _, _) in sorted(entries.items()):
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
        manifest.append(
            {
                "path": staged_path,
                "kind": kind,
                "link_target": link_target,
                "mode": 0o755 if staged_path in executable_paths else 0o644,
            }
        )
    path.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n")


def _executable_paths(executables, entries):
    executable_paths = {_normalise_relative(path) for path in executables}
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


def _arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument(
        "--mapping",
        action="append",
        nargs=3,
        metavar=("SOURCE", "DESTINATION", "ROLE"),
        default=[],
    )
    parser.add_argument(
        "--source-file",
        action="append",
        nargs=3,
        metavar=("SOURCE", "DESTINATION", "PACKAGE"),
        default=[],
        help="a file of a source package, which must neither be nor lie below a symlink inside PACKAGE",
    )
    parser.add_argument("--executable", action="append", default=[])
    parser.add_argument("--manifest", type=pathlib.Path)
    parser.add_argument(
        "--merge",
        action="store_true",
        help="assemble a configuration tree: allow shared sources and merge directories of different mappings",
    )
    args = parser.parse_args()
    if not args.mapping and not args.source_file:
        parser.error("at least one --mapping or --source-file is required")
    return args


def main():
    args = _arguments()
    if args.output.is_symlink():
        raise ValueError("staging output already exists: {}".format(args.output))
    for source, _, package in args.source_file:
        _check_source_file(source, package)
    mappings = args.mapping + [(source, destination, "source-file") for source, destination, _ in args.source_file]
    entries = _manifest(mappings, args.merge)
    executable_paths = _executable_paths(args.executable, entries)
    _reset_output(args.output)
    _copy_manifest(args.output, entries, executable_paths)
    if args.manifest:
        _write_manifest(args.manifest, entries, executable_paths)


if __name__ == "__main__":
    main()
