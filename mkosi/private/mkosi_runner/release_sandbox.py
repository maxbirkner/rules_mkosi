"""Prepares the fixed sandbox files and the local Debian mirror of a build that runs without network."""

import os
from dataclasses import dataclass
from pathlib import Path

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


# mkosi writes its own APT sources only if the sandbox tree does not provide this file.
_MIRROR_SOURCES = "etc/apt/sources.list.d/mkosi.sources"


@dataclass(frozen=True)
class SnapshotMirror:
    """The Debian snapshot copy that a build installs packages from, and the sandbox tree that lists it for APT.

    Attributes:
        directory: The copy, which release_patches.py mounts read-only at mkosi's in-sandbox /repository path.
        sandbox_tree: The --sandbox-tree that receives the APT sources of the mirror.
    """

    directory: Path
    sandbox_tree: Path

    def write_sources(self, release, components):
        """Lists the mirror as the only APT source of the build, with the release suite and the given components."""
        tree.write_file(
            self.sandbox_tree / _MIRROR_SOURCES,
            "Types: deb\nURIs: file:///repository\nSuites: {}\nComponents: {}\nTrusted: yes\n".format(
                release, " ".join(components)
            ),
        )


def configure_release_sandbox(workspace, arguments):
    """Supplies fixed sandbox files instead of host /etc state to a build that runs without network."""
    sandbox_tree = Path(workspace) / "release-sandbox"
    for path, content in _SANDBOX_FILES:
        tree.write_file(sandbox_tree / path, content)
    arguments.extend(["--sandbox-tree", os.fspath(sandbox_tree)])
    return sandbox_tree


def configure_release_mirror(source, workspace, arguments):
    """Copies the Debian snapshot into the workspace and returns it as the build's SnapshotMirror.

    Its write_sources() must run once the parsed configuration has selected the components, before mkosi copies the
    sandbox tree.
    """
    directory = Path(workspace) / "debian-snapshot"
    tree.materialize_tree(source, directory)
    return SnapshotMirror(directory, configure_release_sandbox(workspace, arguments))
