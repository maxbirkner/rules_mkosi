#!/usr/bin/python3
"""Validates the extra_packages of a build and indexes them as a flat APT repository with a normalized manifest.

The index holds a Packages file built from the control files of the packages, which lists each package under its
Debian file name, and a Release file whose label the build's APT preferences pin, so that APT prefers an extra package
over a Debian snapshot package of the same name. The index holds no copy of the .deb files: the image build places
them next to it in its mirror of the Debian snapshot. The manifest lists each package's name, version, architecture,
size and SHA-256.
"""

import argparse
import gzip
import hashlib
import importlib
import io
import json
import lzma
import os
import re
import runpy
import tarfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

_load_sibling = runpy.run_path(str(Path(__file__).with_name("sibling_loader.py")))["load_sibling"]
if TYPE_CHECKING:
    from mkosi.private import debian_control, diagnostics, file_hashing
else:
    debian_control = _load_sibling(__file__, "debian_control")
    diagnostics = _load_sibling(__file__, "diagnostics")
    file_hashing = _load_sibling(__file__, "file_hashing")

FORMAT_VERSION = "mkosi-extra-packages-v1"
# The Release file's Origin and Label, which the APT preferences of the build pin; see release_sandbox.py.
REPOSITORY_ORIGIN = "rules_mkosi"
REPOSITORY_LABEL = "rules-mkosi-extra-packages"
# No date of its own: the repository depends only on the packages.
_RELEASE_DATE = "Thu, 01 Jan 1970 00:00:00 UTC"

_AR_MAGIC = b"!<arch>\n"
_AR_HEADER_SIZE = 60
# Bounds a control archive, which holds only metadata and maintainer scripts, before it is read into memory.
_MAX_CONTROL_ARCHIVE_BYTES = 64 * 1024 * 1024
_NAME = re.compile(r"[a-z0-9][a-z0-9+.-]+")
# Characters that Debian allows in a version; they are also safe in the repository's file names.
_VERSION = re.compile(r"(?:[0-9]+:)?[A-Za-z0-9][A-Za-z0-9.+~-]*")
# Fields that the Packages index derives from the file, so a control file must not set them.
_INDEX_FIELDS = ("Filename", "Size", "MD5sum", "SHA1", "SHA256", "SHA512")


class ExtraPackageError(Exception):
    """An extra package is not a valid Debian binary package for the image."""


@dataclass(frozen=True)
class ExtraPackage:
    """A validated extra package and the control paragraph that its Packages entry starts with."""

    source: Path
    name: str
    version: str
    architecture: str
    size: int
    sha256: str
    control: str

    @property
    def filename(self) -> str:
        """Returns the Debian file name, name_version_architecture.deb, with the version's epoch removed."""
        return "{}_{}_{}.deb".format(self.name, self.version.partition(":")[2] or self.version, self.architecture)

    def index_entry(self) -> str:
        return "{}\nFilename: ./{}\nSize: {}\nSHA256: {}\n".format(self.control, self.filename, self.size, self.sha256)

    def manifest_entry(self) -> dict[str, object]:
        return {
            "architecture": self.architecture,
            "filename": self.filename,
            "name": self.name,
            "sha256": self.sha256,
            "size": self.size,
            "version": self.version,
        }


def _ar_member(source: BinaryIO, path: Path) -> tuple[str, int] | None:
    """Reads the next ar member header and returns its name and size, or None at the end of the archive."""
    header = source.read(_AR_HEADER_SIZE)
    if not header:
        return None
    if len(header) != _AR_HEADER_SIZE or header[58:60] != b"`\n":
        raise ExtraPackageError("{} has a truncated or malformed ar member header".format(path))
    name = header[:16].decode("ascii", "replace").rstrip(" ").rstrip("/")
    size_field = header[48:58].decode("ascii", "replace").strip()
    if not size_field.isdigit():
        raise ExtraPackageError("{} has a malformed ar member size".format(path))
    return name, int(size_field)


def _read_member(source: BinaryIO, size: int, path: Path) -> bytes:
    content = source.read(size)
    if len(content) != size:
        raise ExtraPackageError("{} is truncated".format(path))
    if size % 2:
        source.read(1)
    return content


def _control_archive(path: Path) -> tuple[str, bytes]:
    """Returns the name and content of the control archive of the .deb at path, checking the deb(5) format."""
    with path.open("rb") as source:
        if source.read(len(_AR_MAGIC)) != _AR_MAGIC:
            raise ExtraPackageError("{} is not a Debian binary package: it is not an ar archive".format(path))
        first = _ar_member(source, path)
        if first is None or first[0] != "debian-binary":
            raise ExtraPackageError(
                "{} is not a Debian binary package: debian-binary is not its first member".format(path)
            )
        if not _read_member(source, first[1], path).startswith(b"2."):
            raise ExtraPackageError("{} has an unsupported Debian binary package format".format(path))
        while (member := _ar_member(source, path)) is not None:
            name, size = member
            if name.startswith("control.tar"):
                if size > _MAX_CONTROL_ARCHIVE_BYTES:
                    raise ExtraPackageError("{} has a control archive larger than 64 MiB".format(path))
                return name, _read_member(source, size, path)
            # Members whose name starts with an underscore, such as signatures, may precede the control archive.
            if not name.startswith("_"):
                break
            source.seek(size + size % 2, os.SEEK_CUR)
    raise ExtraPackageError("{} has no control archive".format(path))


def _zstd_decompress(content: bytes) -> bytes:
    # compression.zstd is new in Python 3.14, which the mkosi toolchain provides; mypy checks for Python 3.10.
    try:
        zstd = importlib.import_module("compression.zstd")
    except ImportError as error:
        raise ExtraPackageError("zstd-compressed control archives require Python 3.14") from error
    decompressed: bytes = zstd.decompress(content)
    return decompressed


_DECOMPRESSORS: dict[str, Callable[[bytes], bytes]] = {
    "control.tar": lambda content: content,
    "control.tar.gz": gzip.decompress,
    "control.tar.xz": lzma.decompress,
    "control.tar.zst": _zstd_decompress,
}


def _control_text(path: Path) -> str:
    name, content = _control_archive(path)
    if name not in _DECOMPRESSORS:
        raise ExtraPackageError("{} has an unsupported control archive {}".format(path, name))
    try:
        with tarfile.open(fileobj=io.BytesIO(_DECOMPRESSORS[name](content)), mode="r:") as archive:
            members = [member for member in archive.getmembers() if member.name in ("control", "./control")]
            if len(members) != 1 or not members[0].isfile():
                raise ExtraPackageError("{} must have exactly one control file".format(path))
            control = archive.extractfile(members[0])
            assert control is not None
            return control.read().decode("utf-8")
    except (EOFError, OSError, lzma.LZMAError, tarfile.TarError, UnicodeDecodeError) as error:
        raise ExtraPackageError("{} has an unreadable control archive: {}".format(path, error)) from error


def _control_paragraph(path: Path, text: str) -> tuple[dict[str, str], str]:
    """Returns the fields of the control file and its text without surrounding blank lines."""
    try:
        paragraphs = debian_control.paragraphs(text)
    except ValueError as error:
        raise ExtraPackageError("{} has a malformed control file: {}".format(path, error)) from error
    if len(paragraphs) != 1:
        raise ExtraPackageError("{} must have exactly one control paragraph".format(path))
    fields: dict[str, str] = paragraphs[0]
    for field in ("Package", "Version", "Architecture"):
        if not fields.get(field):
            raise ExtraPackageError("{} has no {} field".format(path, field))
    reserved = sorted(set(fields) & set(_INDEX_FIELDS))
    if reserved:
        raise ExtraPackageError(
            "{} sets Packages index fields in its control file: {}".format(path, ", ".join(reserved))
        )
    return fields, "\n".join(line for line in text.strip("\n").splitlines() if line.strip())


def read_package(path: Path, architecture: str) -> ExtraPackage:
    """Validates the .deb at path for an image of the Debian architecture and returns its index data.

    Raises ExtraPackageError if the file is not a Debian binary package, has an invalid name or version, or is built
    for an architecture other than architecture or all.
    """
    if not path.is_file():
        raise ExtraPackageError("{} is not a Debian binary package: it is not a file".format(path))
    fields, control = _control_paragraph(path, _control_text(path))
    name, version, package_architecture = fields["Package"], fields["Version"], fields["Architecture"]
    if not _NAME.fullmatch(name):
        raise ExtraPackageError("{} has an invalid package name {!r}".format(path, name))
    if not _VERSION.fullmatch(version):
        raise ExtraPackageError("{} has an invalid version {!r}".format(path, version))
    if package_architecture not in ("all", architecture):
        raise ExtraPackageError(
            "{} ({}) is built for architecture {}, but the image's Debian snapshot is {}; use a package for {} "
            "or all".format(path, name, package_architecture, architecture, architecture)
        )
    return ExtraPackage(
        source=path,
        name=name,
        version=version,
        architecture=package_architecture,
        size=path.stat().st_size,
        sha256=file_hashing.sha256_file(path),
        control=control,
    )


def read_packages(paths: Sequence[Path], architecture: str) -> list[ExtraPackage]:
    """Returns the validated packages at paths sorted by name; raises ExtraPackageError for duplicate names."""
    packages: dict[str, ExtraPackage] = {}
    for path in paths:
        package = read_package(path, architecture)
        if package.name in packages:
            raise ExtraPackageError(
                "extra_packages contain package {} twice: {} and {}".format(
                    package.name, packages[package.name].source, path
                )
            )
        packages[package.name] = package
    return [packages[name] for name in sorted(packages)]


def release_file(packages_index: bytes) -> str:
    """Returns the Release file of the flat repository, which APT checks the Packages index against."""
    return "Origin: {}\nLabel: {}\nDate: {}\nSHA256:\n {} {} Packages\n".format(
        REPOSITORY_ORIGIN,
        REPOSITORY_LABEL,
        _RELEASE_DATE,
        hashlib.sha256(packages_index).hexdigest(),
        len(packages_index),
    )


def manifest(packages: Sequence[ExtraPackage], architecture: str) -> dict[str, object]:
    return {
        "architecture": architecture,
        "format_version": FORMAT_VERSION,
        "packages": [package.manifest_entry() for package in packages],
    }


def write_index(packages: Sequence[ExtraPackage], directory: Path) -> None:
    """Writes the Packages index and the Release file of a flat repository of packages into directory."""
    directory.mkdir(parents=True, exist_ok=True)
    index = "\n".join(package.index_entry() for package in packages).encode("utf-8")
    (directory / "Packages").write_bytes(index)
    (directory / "Release").write_text(release_file(index))


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--architecture", required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("packages", type=Path, nargs="+")
    args = parser.parse_args(argv)
    try:
        packages = read_packages(args.packages, args.architecture)
    except ExtraPackageError as error:
        diagnostics.fail("EXTRA_PACKAGE_FAILURE", str(error))
        raise  # Not reached: diagnostics.fail exits.
    write_index(packages, args.index)
    args.manifest.write_text(json.dumps(manifest(packages, args.architecture), indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
