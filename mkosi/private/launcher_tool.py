"""Runs commands from the pinned Debian tools root on files in the action's working directory.

Arguments that are ``os.PathLike`` name files below the working directory; when the tool is the Debian tools
``launcher``, the working directory is bound read-write at ``/outputs/work`` and relative paths are rewritten to it.
Plain strings are passed unchanged, so tool syntax such as mtools' ``::/EFI`` survives. Any other tool is a wrapper
that receives the command line unchanged.
"""

import os
import shutil
import subprocess
from pathlib import Path

WORK = "/outputs/work"
_counter = 0


def _argument(value, launcher):
    if not isinstance(value, os.PathLike):
        return value
    path = os.fspath(value)
    if not launcher or os.path.isabs(path):
        return path
    return WORK + "/" + os.path.normpath(path)


def command(tool, arguments):
    """Returns the command line and environment that run arguments through tool."""
    global _counter
    launcher = Path(tool).name == "launcher"
    converted = [_argument(value, launcher) for value in arguments]
    if not launcher:
        return [os.fspath(tool), *converted], None
    _counter += 1
    cwd = os.getcwd()
    env = dict(os.environ)
    env["MKOSI_DEBIAN_TOOLS_SCRATCH"] = os.path.join(cwd, ".debian-tool-{}-{}".format(os.getpid(), _counter))
    return [os.fspath(tool), "--rw-bind", "{}:{}".format(cwd, WORK), *converted], env


def run_tool(tool, *arguments, capture=False):
    """Runs arguments[0] with the remaining arguments and returns the completed process."""
    command_line, env = command(tool, list(arguments))
    try:
        return subprocess.run(command_line, check=True, capture_output=capture, env=env)
    finally:
        # Each launcher call extracts a full Debian tools root into its scratch directory.
        if env:
            shutil.rmtree(env["MKOSI_DEBIAN_TOOLS_SCRATCH"], ignore_errors=True)
