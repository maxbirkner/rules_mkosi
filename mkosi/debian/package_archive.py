"""Build a deterministic Debian package tree archive without host tools."""

import contextlib
import io
import hashlib
import os
import shutil
import stat
import sys
import tarfile


def _member_path(name):
    if name.startswith("/"):
        raise ValueError("absolute package member: %s" % name)
    while name.startswith("./"):
        name = name[2:]
    if name in ("", "."):
        return ""
    parts = name.split("/")
    if parts and parts[-1] == "":
        parts.pop()
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise ValueError("unsafe package member: %s" % name)
    return os.path.join(*parts)


def _ar_members(data):
    if not data.startswith(b"!<arch>\n"):
        raise ValueError("not a Debian ar archive")
    offset = 8
    while offset < len(data):
        if offset + 60 > len(data):
            raise ValueError("truncated Debian ar header")
        header = data[offset:offset + 60]
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


def _package_data(package):
    data = package.read()
    for name, member in _ar_members(data):
        if name.startswith("data.tar"):
            return member
    raise ValueError("Debian package has no data archive")


def _ensure_parent(objects, relative):
    parent = os.path.dirname(relative)
    if not parent:
        return
    pieces = parent.split(os.sep)
    for index in range(1, len(pieces) + 1):
        current = os.path.join(*pieces[:index])
        if current not in objects:
            objects[current] = ("dir", 0o755, None, None)


def _read_manifest(manifest):
    """Returns the expected SHA-256 of every package keyed by file name."""
    expected = {}
    with open(manifest, "r", encoding="utf-8") as entries:
        for line in entries:
            fields = line.rstrip("\n").split("|", 2)
            if len(fields) != 3 or fields[0] in expected:
                raise ValueError("invalid or duplicate package manifest entry")
            expected[fields[0]] = fields[1]
    return expected


def _sha256(stream):
    digest = hashlib.sha256()
    while True:
        chunk = stream.read(1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
    return digest.hexdigest()


def _open_authenticated(package, expected_digest):
    """Opens package without following symlinks and verifies its digest before it is parsed."""
    name = os.path.basename(package)
    fd = os.open(os.path.realpath(package), os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    stream = os.fdopen(fd, "rb")
    actual = _sha256(stream)
    if actual != expected_digest:
        stream.close()
        raise ValueError(
            "Debian package digest mismatch for %s: expected=%s actual=%s"
            % (name, expected_digest, actual)
        )
    stream.seek(0)
    return stream


def _authenticated_streams(packages, expected, stack):
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


def _extract_file(source, member, relative, work):
    destination = os.path.join(work, relative)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    source_file = source.extractfile(member)
    if source_file is None:
        raise ValueError("package member has no data: %s" % relative)
    with source_file, open(destination, "wb") as output:
        shutil.copyfileobj(source_file, output)
    return destination


def _member_object(source, member, relative, work):
    """Returns the (kind, mode, extracted file, link name) record of one package member."""
    mode = stat.S_IMODE(member.mode)
    if member.isdir():
        return ("dir", mode, None, None)
    if member.isfile():
        return ("file", mode, _extract_file(source, member, relative, work), None)
    if member.issym():
        return ("symlink", mode, None, member.linkname)
    if member.islnk():
        return ("hardlink", mode, None, member.linkname)
    raise ValueError("unsupported package member: %s" % relative)


def _collect_package(stream, objects, work):
    with tarfile.open(fileobj=io.BytesIO(_package_data(stream)), mode="r:*") as source:
        for member in source:
            relative = _member_path(member.name)
            if not relative:
                continue
            _ensure_parent(objects, relative)
            objects[relative] = _member_object(source, member, relative, work)


def _collect(packages, manifest, work):
    expected = _read_manifest(manifest)
    objects = {}
    with contextlib.ExitStack() as stack:
        for _, stream in _authenticated_streams(packages, expected, stack):
            _collect_package(stream, objects, work)
    return objects


def _archive(output, objects):
    with tarfile.open(output, "w", format=tarfile.PAX_FORMAT) as destination:
        for relative in sorted(objects, key=lambda item: (item.count(os.sep), item)):
            kind, mode, source, linkname = objects[relative]
            member = tarfile.TarInfo("./" + relative)
            member.mode = mode
            member.uid = 0
            member.gid = 0
            member.uname = ""
            member.gname = ""
            member.mtime = 0
            if kind == "dir":
                member.type = tarfile.DIRTYPE
                destination.addfile(member)
            elif kind == "file":
                member.size = os.path.getsize(source)
                with open(source, "rb") as contents:
                    destination.addfile(member, contents)
            elif kind == "symlink":
                member.type = tarfile.SYMTYPE
                member.linkname = linkname
                destination.addfile(member)
            else:
                member.type = tarfile.LNKTYPE
                member.linkname = linkname
                destination.addfile(member)


def main():
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
        raise SystemExit(1)
