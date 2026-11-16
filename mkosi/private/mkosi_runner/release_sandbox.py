"""Prepares the fixed sandbox files and the local Debian mirror of a build that runs without network."""

import os
import runpy
import shutil
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from . import tree

if TYPE_CHECKING:
    from mkosi.private.file_hashing import sha256_file
else:
    # file_hashing.py is a sibling of run_mkosi.py, outside this package, which run_mkosi.py loads by path.
    sha256_file = runpy.run_path(str(Path(__file__).parents[1] / "file_hashing.py"))["sha256_file"]

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
# extra_packages.py writes into the repository's index.
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
class ExtraPackages:
    """The extra_packages of a build.

    Attributes:
        index: The directory with the Packages and Release files that extra_packages.py writes for the packages.
        packages: The .deb files that the index lists, in any order and under any file names.
    """

    index: str | os.PathLike[str]
    packages: Sequence[str | os.PathLike[str]]


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
    extra_packages: ExtraPackages | None = None,
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
        place_extra_packages(extra_packages, destination)
        tree.normalize(directory, 0o755)
    return SnapshotMirror(directory, configure_release_sandbox(workspace, arguments), extra_packages is not None)


def place_extra_packages(extra_packages: ExtraPackages, destination: Path) -> None:
    """Copies the index of the extra packages to destination, and each .deb file next to it under its indexed name.

    This is the only copy of the .deb files that a build makes. shutil.copyfile uses copy_file_range, so a file system
    that supports it, such as Btrfs or XFS, may share the data of the copy with the Bazel input instead of writing it.
    """
    tree.materialize_tree(extra_packages.index, destination)
    filenames = _read_indexed_filenames(destination / "Packages")
    for package in extra_packages.packages:
        filename = filenames.pop(sha256_file(package), None)
        if filename is None:
            raise SystemExit("extra package {} is not in the extra packages' index".format(os.fspath(package)))
        shutil.copyfile(package, destination / filename)
        tree.normalize(destination / filename, 0o644)
    if filenames:
        raise SystemExit(
            "the build lacks {} of the extra packages' index".format(", ".join(sorted(filenames.values())))
        )
    tree.normalize(destination, 0o755)


def _read_indexed_filenames(packages_index: Path) -> dict[str, str]:
    """Returns the file name of each package of the Packages index that extra_packages.py writes, keyed by SHA-256."""
    filenames: dict[str, str] = {}
    for paragraph in packages_index.read_text().split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in paragraph.splitlines() if line.startswith(("Filename: ", "SHA256: "))
        )
        if not fields:
            continue
        filename = fields.get("Filename", "").removeprefix("./")
        if "/" in filename or filename in ("", ".", ".."):
            raise SystemExit("invalid file name {} in the extra packages' index".format(filename))
        if not fields.get("SHA256"):
            raise SystemExit("{} has no SHA256 in the extra packages' index".format(filename))
        filenames[fields["SHA256"]] = filename
    return filenames
