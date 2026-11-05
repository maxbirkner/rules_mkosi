"""Prepares the fixed sandbox files and the local Debian mirror of a build that runs without network."""

import os

from . import tree

PASSWD = "root:x:0:0:root:/root:/bin/sh\n"
GROUP = "root:x:0:\n"
HOSTS = "127.0.0.1 localhost\n::1 localhost\n"
NSSWITCH = """\
passwd:     files
shadow:     files
group:      files
hosts:      files
services:   files
netgroup:   files
automount:  files

aliases:    files
ethers:     files
gshadow:    files
networks:   files
protocols:  files
publickey:  files
rpc:        files
"""
APT_CONFIGURATION = 'Acquire::Languages "none";\nAcquire::By-Hash "no";\n'

_SANDBOX_FILES = (
    ("etc/apt/apt.conf.d/99rules-mkosi-release", APT_CONFIGURATION),
    ("etc/passwd", PASSWD),
    ("etc/group", GROUP),
    ("etc/hosts", HOSTS),
    ("etc/nsswitch.conf", NSSWITCH),
)


def configure_release_sandbox(workspace, arguments):
    """Supplies fixed sandbox files instead of host /etc state to a build that runs without network."""
    sandbox_tree = workspace / "release-sandbox"
    for path, content in _SANDBOX_FILES:
        tree.write_file(sandbox_tree / path, content)
    arguments.extend(["--sandbox-tree", os.fspath(sandbox_tree)])


def configure_release_mirror(source, workspace, arguments):
    """Copies the Debian snapshot into the workspace as mkosi's local mirror and returns the copy."""
    mirror = workspace / "debian-snapshot"
    tree.materialize_tree(source, mirror)
    arguments.extend(["--local-mirror", "file://" + os.fspath(mirror)])
    configure_release_sandbox(workspace, arguments)
    return mirror
