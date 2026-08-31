#!/usr/bin/python3
"""Run mkosi after resolving Bazel paths before mkosi changes directory."""

import os
import runpy
import shutil
import sys
from pathlib import Path


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
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    for root, directories, files in os.walk(source, followlinks=False):
        relative = Path(root).relative_to(source)
        target_root = destination / relative
        target_root.mkdir(parents=True, exist_ok=True)
        for name in sorted(directories + files):
            source_path = Path(root) / name
            target_path = target_root / name
            if source_path.is_symlink():
                resolved = source_path.resolve()
                if not resolved.is_relative_to(source):
                    if resolved.is_dir():
                        shutil.copytree(resolved, target_path, symlinks=True)
                    else:
                        shutil.copy2(resolved, target_path)
                else:
                    target_path.symlink_to(os.readlink(source_path))
            elif source_path.is_dir():
                target_path.mkdir(parents=True, exist_ok=True)
            else:
                shutil.copy2(source_path, target_path)


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
