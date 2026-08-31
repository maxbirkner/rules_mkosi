#!/usr/bin/python3
"""Run mkosi after resolving Bazel paths before mkosi changes directory."""

import os
import runpy
import shutil
import stat
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


def _materialize_tree(source, destination):
    source = Path(source)
    source_root = source.resolve(strict=True)
    destination = Path(destination)
    if destination.is_symlink():
        raise SystemExit("materialization destination is a symlink")
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=False)
    os.chmod(destination, 0o755)
    os.utime(destination, _EPOCH)

    def copy_tree(source_dir, target_dir):
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
                    copy_tree(resolved, target_path)
                elif resolved.is_file():
                    shutil.copyfile(resolved, target_path)
                    os.chmod(
                        target_path,
                        0o755 if resolved.stat().st_mode & stat.S_IXUSR else 0o644,
                    )
                    os.utime(target_path, _EPOCH)
                else:
                    raise SystemExit("unsupported Bazel input indirection: {}".format(source_path))
            elif item.is_dir(follow_symlinks=False):
                copy_tree(source_path, target_path)
            elif item.is_file(follow_symlinks=False):
                shutil.copyfile(source_path, target_path)
                os.chmod(
                    target_path,
                    0o755 if source_path.stat().st_mode & stat.S_IXUSR else 0o644,
                )
                os.utime(target_path, _EPOCH)
            else:
                raise SystemExit("unsupported staged entry: {}".format(source_path))
        os.chmod(target_dir, 0o755)
        os.utime(target_dir, _EPOCH)

    copy_tree(source_root, destination)


def main():
    if len(sys.argv) < 3 or sys.argv[2] != "--":
        raise SystemExit("usage: run_mkosi.py MKOSI_SCRIPT -- [mkosi arguments]")
    script = os.path.abspath(sys.argv[1])
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
    arguments = _absolute_paths(sys.argv[3:])
    if "-C" in arguments:
        directory = Path(arguments[arguments.index("-C") + 1])
        workspace = Path(arguments[arguments.index("--workspace-directory") + 1])
        materialized = workspace / "staging-root"
        _materialize_tree(directory, materialized)
        arguments[arguments.index("-C") + 1] = os.fspath(materialized)
        for option in ("-I", "--include"):
            for index, argument in enumerate(arguments):
                if argument.startswith(os.fspath(directory) + os.sep):
                    arguments[index] = os.fspath(materialized) + argument[len(os.fspath(directory)) :]
    sys.argv[:] = [script] + arguments
    runpy.run_path(script, run_name="__main__")


if __name__ == "__main__":
    main()
