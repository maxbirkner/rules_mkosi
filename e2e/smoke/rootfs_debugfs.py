"""Runs debugfs requests on an extracted ext4 root filesystem with the pinned Debian tools launcher."""

import itertools
import os
import pathlib
import subprocess

_REQUESTS = itertools.count()


def run_debugfs(launcher: str, directory: pathlib.Path, mount: str, request: str) -> str:
    """Returns the output of a debugfs request on directory/rootfs.ext4, which the launcher sees in /inputs/<mount>.

    Raises:
        AssertionError: If debugfs fails.
    """
    environment = dict(os.environ)
    environment["MKOSI_DEBIAN_TOOLS_SCRATCH"] = str(directory / "launcher-{}".format(next(_REQUESTS)))
    result = subprocess.run(
        [
            launcher,
            "--ro-bind",
            "{}:/inputs/{}".format(directory, mount),
            "/usr/sbin/debugfs",
            "-R",
            request,
            "/inputs/{}/rootfs.ext4".format(mount),
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=environment,
    )
    if result.returncode:
        raise AssertionError(
            "debugfs request {!r} failed with {}: {}".format(request, result.returncode, result.stdout)
        )
    return result.stdout
