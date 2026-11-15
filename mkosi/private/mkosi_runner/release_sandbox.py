"""Prepares the fixed sandbox files and the local Debian mirror of a build that runs without network."""

import os
from collections.abc import Iterable
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

# The flat APT repository of the extra_packages inside the mirror, and the Origin and Label of its Release file, which
# extra_packages.py writes.
EXTRA_PACKAGES_DIRECTORY = "rules-mkosi-extra-packages"
EXTRA_PACKAGES_ORIGIN = "rules_mkosi"
EXTRA_PACKAGES_LABEL = "rules-mkosi-extra-packages"
_EXTRA_PACKAGES_PREFERENCES = "etc/apt/preferences.d/rules-mkosi-extra-packages.pref"
# A priority above 1000 makes APT install an extra package instead of a snapshot package of the same name, even if the
# snapshot's version is higher, like mkosi's own PackageDirectories= repository.
EXTRA_PACKAGES_PIN = "Package: *\nPin: release o={},l={}\nPin-Priority: 1100\n".format(
    EXTRA_PACKAGES_ORIGIN, EXTRA_PACKAGES_LABEL
)


@dataclass(frozen=True)
class SnapshotMirror:
    """The Debian snapshot copy that a build installs packages from, and the sandbox tree that lists it for APT.

    Attributes:
        directory: The copy, which release_patches.py mounts read-only at mkosi's in-sandbox /repository path.
        sandbox_tree: The --sandbox-tree that receives the APT sources of the mirror.
        extra_packages: Whether the copy contains the flat repository of the extra_packages in
            EXTRA_PACKAGES_DIRECTORY.
    """

    directory: Path
    sandbox_tree: Path
    extra_packages: bool = False

    def write_sources(self, release: str, components: Iterable[str]) -> None:
        """Lists the mirror as the only APT source of the build, with the release suite and the given components.

        The extra packages come first: for a version that both repositories list, APT then reads the extra package's
        file.
        """
        snapshot = "Types: deb\nURIs: file:///repository\nSuites: {}\nComponents: {}\nTrusted: yes\n".format(
            release, " ".join(components)
        )
        if not self.extra_packages:
            tree.write_file(self.sandbox_tree / _MIRROR_SOURCES, snapshot)
            return
        extra = "Types: deb\nURIs: file:///repository/{}\nSuites: ./\nTrusted: yes\n".format(EXTRA_PACKAGES_DIRECTORY)
        tree.write_file(self.sandbox_tree / _MIRROR_SOURCES, extra + "\n" + snapshot)
        tree.write_file(self.sandbox_tree / _EXTRA_PACKAGES_PREFERENCES, EXTRA_PACKAGES_PIN)


def configure_release_sandbox(workspace: str | os.PathLike[str], arguments: list[str]) -> Path:
    """Supplies fixed sandbox files instead of host /etc state to a build that runs without network."""
    sandbox_tree = Path(workspace) / "release-sandbox"
    for path, content in _SANDBOX_FILES:
        tree.write_file(sandbox_tree / path, content)
    arguments.extend(["--sandbox-tree", os.fspath(sandbox_tree)])
    return sandbox_tree


def configure_release_mirror(
    source: str | os.PathLike[str],
    workspace: str | os.PathLike[str],
    arguments: list[str],
    extra_packages: str | os.PathLike[str] | None = None,
) -> SnapshotMirror:
    """Copies the Debian snapshot, and the extra packages' repository if any, into the workspace as the build's mirror.

    Its write_sources() must run once the parsed configuration has selected the components, before mkosi copies the
    sandbox tree.
    """
    directory = Path(workspace) / "debian-snapshot"
    tree.materialize_tree(source, directory)
    if extra_packages is not None:
        destination = directory / EXTRA_PACKAGES_DIRECTORY
        if destination.exists() or destination.is_symlink():
            raise SystemExit("the Debian snapshot repository already contains {}".format(EXTRA_PACKAGES_DIRECTORY))
        tree.materialize_tree(extra_packages, destination)
        tree.normalize(directory, 0o755)
    return SnapshotMirror(directory, configure_release_sandbox(workspace, arguments), extra_packages is not None)
