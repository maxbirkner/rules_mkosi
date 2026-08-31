#!/usr/bin/python3
"""Run mkosi after resolving Bazel paths before mkosi changes directory."""

import os
import json
import runpy
import shutil
import sys
from pathlib import Path

_EPOCH = (0, 0)


_PATH_OPTIONS = {
    "-I",
    "--include",
    "-C",
    "--directory",
    "--tools-tree",
    "--extra-search-path",
    "--output-directory",
    "--workspace-directory",
    "--cache-directory",
    "--package-cache-directory",
    "--build-directory",
}


def _absolute_paths(arguments):
    result = []
    resolve_next = False
    for argument in arguments:
        if resolve_next:
            result.append(os.path.abspath(argument))
            resolve_next = False
        elif argument in _PATH_OPTIONS:
            result.append(argument)
            resolve_next = True
        elif any(argument.startswith(option + "=") for option in _PATH_OPTIONS):
            option, value = argument.split("=", 1)
            result.append(option + "=" + os.path.abspath(value))
        else:
            result.append(argument)
    if resolve_next:
        raise SystemExit("mkosi path option is missing its value")
    return result


def _materialize_tree(source, destination, executable_paths=()):
    source = Path(source)
    source_root = source.resolve(strict=True)
    executable_paths = set(executable_paths)
    destination = Path(destination)
    if destination.is_symlink():
        raise SystemExit("materialization destination is a symlink")
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=False)
    os.chmod(destination, 0o755)
    os.utime(destination, _EPOCH)

    def copy_tree(source_dir, target_dir, relative_prefix):
        target_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(target_dir, 0o755)
        os.utime(target_dir, _EPOCH)
        for item in sorted(os.scandir(source_dir), key=lambda entry: entry.name):
            source_path = Path(item.path)
            target_path = target_dir / item.name
            if item.is_symlink():
                resolved = source_path.resolve(strict=True)
                if resolved.is_relative_to(source_root):
                    target_path.symlink_to(os.readlink(source_path))
                    os.utime(target_path, _EPOCH, follow_symlinks=False)
                elif resolved.is_dir():
                    copy_tree(resolved, target_path, relative_prefix / item.name)
                elif resolved.is_file():
                    shutil.copyfile(resolved, target_path)
                    os.chmod(
                        target_path,
                        0o755
                        if (relative_prefix / item.name).as_posix() in executable_paths
                        else 0o644,
                    )
                    os.utime(target_path, _EPOCH)
                else:
                    raise SystemExit("unsupported Bazel input indirection: {}".format(source_path))
            elif item.is_dir(follow_symlinks=False):
                copy_tree(source_path, target_path, relative_prefix / item.name)
            elif item.is_file(follow_symlinks=False):
                shutil.copyfile(source_path, target_path)
                os.chmod(
                    target_path,
                    0o755
                    if (relative_prefix / item.name).as_posix() in executable_paths
                    else 0o644,
                )
                os.utime(target_path, _EPOCH)
            else:
                raise SystemExit("unsupported staged entry: {}".format(source_path))
        os.chmod(target_dir, 0o755)
        os.utime(target_dir, _EPOCH)

    copy_tree(source_root, destination, Path())


def _restore_manifest_links(destination, manifest_path):
    entries = json.loads(Path(manifest_path).read_text())
    for entry in entries:
        if entry["kind"] != "symlink":
            continue
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise SystemExit("invalid staging manifest path")
        target = destination / relative
        if target.is_symlink() or target.is_file():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
        else:
            raise SystemExit("staging manifest entry is missing")
        link_target = entry["link_target"]
        if not link_target or os.path.isabs(link_target):
            raise SystemExit("invalid staging manifest link")
        target.symlink_to(link_target)
    directories = []
    for root, dirnames, _ in os.walk(destination, followlinks=False):
        directories.append(Path(root))
        for name in dirnames:
            path = Path(root) / name
            if not path.is_symlink():
                directories.append(path)
    for path in sorted(set(directories), reverse=True):
        os.chmod(path, 0o755)
        os.utime(path, _EPOCH)


def main():
    if len(sys.argv) < 3:
        raise SystemExit("usage: run_mkosi.py MKOSI_SCRIPT [--executable-path PATH] -- [mkosi arguments]")
    script = os.path.abspath(sys.argv[1])
    preamble_end = 2
    executable_paths = []
    staging_manifest = None
    while preamble_end < len(sys.argv) and sys.argv[preamble_end] != "--":
        option = sys.argv[preamble_end]
        if option == "--executable-path" and preamble_end + 1 < len(sys.argv):
            executable_paths.append(sys.argv[preamble_end + 1])
            preamble_end += 2
        elif option == "--staging-manifest" and preamble_end + 1 < len(sys.argv):
            staging_manifest = os.path.abspath(sys.argv[preamble_end + 1])
            preamble_end += 2
        else:
            raise SystemExit("invalid run_mkosi.py preamble")
    if preamble_end == len(sys.argv):
        raise SystemExit("run_mkosi.py preamble is missing --")
    if os.environ.get("PYTHONPATH"):
        python_paths = os.environ["PYTHONPATH"].split(os.pathsep)
        os.environ["PYTHONPATH"] = os.pathsep.join(
            os.path.abspath(path or ".")
            for path in python_paths
        )
        sys.path[:] = [
            os.path.abspath(path) if path in python_paths else path
            for path in sys.path
        ]
    arguments = _absolute_paths(sys.argv[preamble_end + 1 :])
    if "-C" in arguments:
        directory = Path(arguments[arguments.index("-C") + 1])
        workspace = Path(arguments[arguments.index("--workspace-directory") + 1])
        materialized = workspace / "staging-root"
        _materialize_tree(directory, materialized, executable_paths)
        if staging_manifest:
            _restore_manifest_links(materialized, staging_manifest)
        arguments[arguments.index("-C") + 1] = os.fspath(materialized)
        for option in ("-I", "--include"):
            for index, argument in enumerate(arguments):
                if argument.startswith(os.fspath(directory) + os.sep):
                    arguments[index] = os.fspath(materialized) + argument[len(os.fspath(directory)) :]
    sys.argv[:] = [script] + arguments
    runpy.run_path(script, run_name="__main__")


if __name__ == "__main__":
    main()
