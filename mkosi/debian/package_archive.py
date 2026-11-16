"""Build a deterministic Debian package tree archive without host tools."""

import contextlib
import io
import os
import runpy
import shutil
import stat
import sys
import tarfile
from collections.abc import Iterator, Mapping, MutableMapping, Sequence
from typing import IO, NamedTuple, TypeAlias

# extract_tree.py owns the member path validation and stream hashing; the archive action stages it next to this script.
_extract_tree = runpy.run_path(os.path.join(os.path.dirname(__file__), "extract_tree.py"))
_member_path = _extract_tree["member_path"]
_sha256 = _extract_tree["sha256_stream"]


class _Directory(NamedTuple):
    """A directory of a package, or a parent directory that its members imply."""

    mode: int


class _RegularFile(NamedTuple):
    """A regular file of a package, with the path of its extracted contents."""

    mode: int
    extracted: str


class _Link(NamedTuple):
    """A symbolic or hard link of a package, with its tar member type."""

    mode: int
    type: bytes
    linkname: str


_PackageObject: TypeAlias = _Directory | _RegularFile | _Link


def _ar_members(data: bytes) -> Iterator[tuple[str, bytes]]:
    if not data.startswith(b"!<arch>\n"):
        raise ValueError("not a Debian ar archive")
    offset = 8
    while offset < len(data):
        if offset + 60 > len(data):
            raise ValueError("truncated Debian ar header")
        header = data[offset : offset + 60]
        if header[58:60] != b"`\n":
            raise ValueError("invalid Debian ar header")
        name = header[:16].decode("ascii").strip().rstrip("/")
        size = int(header[48:58].decode("ascii").strip())
        start = offset + 60
        end = start + size
        if end > len(data):
            raise ValueError("truncated Debian ar member")
        yield name, data[start:end]
        offset = end + (end & 1)


def _package_data(package: IO[bytes]) -> bytes:
    data = package.read()
    for name, member in _ar_members(data):
        if name.startswith("data.tar"):
            return member
    raise ValueError("Debian package has no data archive")


def _ensure_parent(objects: MutableMapping[str, _PackageObject], relative: str) -> None:
    parent = os.path.dirname(relative)
    if not parent:
        return
    pieces = parent.split(os.sep)
    for index in range(1, len(pieces) + 1):
        current = os.path.join(*pieces[:index])
        if current not in objects:
            objects[current] = _Directory(0o755)


def _read_manifest(manifest: str) -> dict[str, str]:
    """Returns the expected SHA-256 of every package keyed by file name."""
    expected = {}
    with open(manifest, encoding="utf-8") as entries:
        for line in entries:
            fields = line.rstrip("\n").split("|", 2)
            if len(fields) != 3 or fields[0] in expected:
                raise ValueError("invalid or duplicate package manifest entry")
            expected[fields[0]] = fields[1]
    return expected


def _open_authenticated(package: str, expected_digest: str) -> io.BufferedReader:
    """Opens package without following symlinks and verifies its digest before it is parsed."""
    name = os.path.basename(package)
    fd = os.open(os.path.realpath(package), os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    stream = os.fdopen(fd, "rb")
    actual = _sha256(stream)
    if actual != expected_digest:
        stream.close()
        raise ValueError(
            "Debian package digest mismatch for %s: expected=%s actual=%s" % (name, expected_digest, actual)
        )
    stream.seek(0)
    return stream


def _authenticated_streams(
    packages: Sequence[str], expected: Mapping[str, str], stack: contextlib.ExitStack
) -> list[tuple[str, io.BufferedReader]]:
    """Opens and authenticates every package; stack closes each opened stream, including on errors."""
    if len(expected) != len(packages):
        raise ValueError("package manifest does not match package inputs")
    streams = []
    seen = set()
    for package in packages:
        name = os.path.basename(package)
        if name not in expected:
            raise ValueError("package is absent from manifest: %s" % name)
        if name in seen:
            raise ValueError("package is duplicated in action inputs: %s" % name)
        seen.add(name)
        streams.append((package, stack.enter_context(_open_authenticated(package, expected[name]))))
    if seen != set(expected):
        raise ValueError("package manifest does not match package inputs")
    return streams


def _extract_file(source: tarfile.TarFile, member: tarfile.TarInfo, relative: str, work: str) -> str:
    destination = os.path.join(work, relative)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    source_file = source.extractfile(member)
    if source_file is None:
        raise ValueError("package member has no data: %s" % relative)
    with source_file, open(destination, "wb") as output:
        shutil.copyfileobj(source_file, output)
    return destination


def _member_object(source: tarfile.TarFile, member: tarfile.TarInfo, relative: str, work: str) -> _PackageObject:
    """Returns the record of one package member, extracting a regular file into work."""
    mode = stat.S_IMODE(member.mode)
    if member.isdir():
        return _Directory(mode)
    if member.isfile():
        return _RegularFile(mode, _extract_file(source, member, relative, work))
    if member.issym():
        return _Link(mode, tarfile.SYMTYPE, member.linkname)
    if member.islnk():
        return _Link(mode, tarfile.LNKTYPE, member.linkname)
    raise ValueError("unsupported package member: %s" % relative)


def _collect_package(stream: IO[bytes], objects: MutableMapping[str, _PackageObject], work: str) -> None:
    with tarfile.open(fileobj=io.BytesIO(_package_data(stream)), mode="r:*") as source:
        for member in source:
            relative = _member_path(member.name, "package")
            if not relative:
                continue
            _ensure_parent(objects, relative)
            objects[relative] = _member_object(source, member, relative, work)


def _collect(packages: Sequence[str], manifest: str, work: str) -> dict[str, _PackageObject]:
    expected = _read_manifest(manifest)
    objects: dict[str, _PackageObject] = {}
    with contextlib.ExitStack() as stack:
        for _, stream in _authenticated_streams(packages, expected, stack):
            _collect_package(stream, objects, work)
    return objects


def _archive(output: str, objects: Mapping[str, _PackageObject]) -> None:
    with tarfile.open(output, "w", format=tarfile.PAX_FORMAT) as destination:
        for relative in sorted(objects, key=lambda item: (item.count(os.sep), item)):
            item = objects[relative]
            member = tarfile.TarInfo("./" + relative)
            member.mode = item.mode
            member.uid = 0
            member.gid = 0
            member.uname = ""
            member.gname = ""
            member.mtime = 0
            if isinstance(item, _Directory):
                member.type = tarfile.DIRTYPE
                destination.addfile(member)
            elif isinstance(item, _RegularFile):
                member.size = os.path.getsize(item.extracted)
                with open(item.extracted, "rb") as contents:
                    destination.addfile(member, contents)
            else:
                member.type = item.type
                member.linkname = item.linkname
                destination.addfile(member)


def main() -> None:
    if len(sys.argv) < 4:
        raise SystemExit("usage: package_archive.py OUTPUT MANIFEST PACKAGE...")
    output = os.path.abspath(sys.argv[1])
    manifest = sys.argv[2]
    work = output + ".work"
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, mode=0o700)
    try:
        _archive(output, _collect(sys.argv[3:], manifest, work))
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, tarfile.TarError, ValueError) as error:
        print("Debian package archive construction failed: %s" % error, file=sys.stderr)
        raise SystemExit(1) from error
