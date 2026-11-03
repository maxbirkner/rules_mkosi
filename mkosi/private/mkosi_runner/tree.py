"""Copies Bazel inputs into trees with fixed modes and timestamps, so that host metadata cannot reach an image."""

import json
import os
import shutil
from pathlib import Path

EPOCH = (0, 0)


def normalize(path, mode):
    os.chmod(path, mode)
    os.utime(path, EPOCH)


def write_file(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    normalize(path, 0o644)


def remove_tree(destination, description):
    """Removes a previous copy at destination, refusing to follow a symlink out of the workspace."""
    if destination.is_symlink():
        raise SystemExit("{} is a symlink".format(description))
    if destination.exists():
        shutil.rmtree(destination)


def materialize_tree(source, destination, executable_paths=()):
    """Copies source into destination with normalized metadata.

    Symlinks that stay inside source are kept. Other symlinks, such as those through which Bazel stages its inputs,
    are replaced by copies of their targets, so that mkosi neither follows nor modifies them.
    """
    source_root = Path(source).resolve(strict=True)
    destination = Path(destination)
    remove_tree(destination, "materialization destination")
    destination.mkdir(parents=True, exist_ok=False)
    _TreeCopy(source_root, frozenset(executable_paths)).directory(source_root, destination, Path())


class _TreeCopy:
    def __init__(self, root, executable_paths):
        self._root = root
        self._executable_paths = executable_paths

    def directory(self, source, target, relative):
        target.mkdir(parents=True, exist_ok=True)
        for entry in sorted(os.scandir(source), key=lambda entry: entry.name):
            self._entry(entry, target / entry.name, relative / entry.name)
        normalize(target, 0o755)

    def _entry(self, entry, target, relative):
        source = Path(entry.path)
        if entry.is_symlink():
            self._symlink(source, target, relative)
        elif entry.is_dir(follow_symlinks=False):
            self.directory(source, target, relative)
        elif entry.is_file(follow_symlinks=False):
            self._file(source, target, relative)
        else:
            raise SystemExit("unsupported staged entry: {}".format(source))

    def _symlink(self, source, target, relative):
        resolved = source.resolve(strict=True)
        if resolved.is_relative_to(self._root):
            target.symlink_to(os.readlink(source))
            os.utime(target, EPOCH, follow_symlinks=False)
        elif resolved.is_dir():
            self.directory(resolved, target, relative)
        elif resolved.is_file():
            self._file(resolved, target, relative)
        else:
            raise SystemExit("unsupported Bazel input indirection: {}".format(source))

    def _file(self, source, target, relative):
        shutil.copyfile(source, target)
        normalize(target, 0o755 if relative.as_posix() in self._executable_paths else 0o644)


def restore_manifest_links(destination, manifest_path):
    """Replaces the entries that the staging manifest records as symlinks with those relative symlinks."""
    for entry in json.loads(Path(manifest_path).read_text()):
        if entry["kind"] == "symlink":
            _restore_link(destination, entry["path"], entry["link_target"])
    for directory in sorted((Path(root) for root, _, _ in os.walk(destination)), reverse=True):
        normalize(directory, 0o755)


def _restore_link(destination, path, link_target):
    relative = Path(path)
    if relative.is_absolute() or ".." in relative.parts:
        raise SystemExit("invalid staging manifest path")
    target = destination / relative
    _remove_entry(target)
    if not link_target or os.path.isabs(link_target):
        raise SystemExit("invalid staging manifest link")
    target.symlink_to(link_target)
    os.utime(target, EPOCH, follow_symlinks=False)


def _remove_entry(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    else:
        raise SystemExit("staging manifest entry is missing")
