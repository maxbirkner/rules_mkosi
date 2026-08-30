"""Build a deterministic Debian package tree archive without host tools."""

import io
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


def _package_data(path):
    with open(path, "rb") as package:
        data = package.read()
    for name, member in _ar_members(data):
        if name.startswith("data.tar"):
            return member
    raise ValueError("Debian package has no data archive: %s" % path)


def _ensure_parent(objects, relative):
    parent = os.path.dirname(relative)
    if not parent:
        return
    pieces = parent.split(os.sep)
    for index in range(1, len(pieces) + 1):
        current = os.path.join(*pieces[:index])
        if current not in objects:
            objects[current] = ("dir", 0o755, None, None)


def _collect(packages, work):
    objects = {}
    for package in packages:
        with tarfile.open(fileobj=io.BytesIO(_package_data(package)), mode="r:*") as source:
            for member in source:
                relative = _member_path(member.name)
                if not relative:
                    continue
                _ensure_parent(objects, relative)
                if member.isdir():
                    objects[relative] = ("dir", stat.S_IMODE(member.mode), None, None)
                elif member.isfile():
                    destination = os.path.join(work, relative)
                    os.makedirs(os.path.dirname(destination), exist_ok=True)
                    source_file = source.extractfile(member)
                    if source_file is None:
                        raise ValueError("package member has no data: %s" % relative)
                    with source_file, open(destination, "wb") as output:
                        shutil.copyfileobj(source_file, output)
                    objects[relative] = ("file", stat.S_IMODE(member.mode), destination, None)
                elif member.issym():
                    objects[relative] = ("symlink", stat.S_IMODE(member.mode), None, member.linkname)
                elif member.islnk():
                    objects[relative] = ("hardlink", stat.S_IMODE(member.mode), None, member.linkname)
                else:
                    raise ValueError("unsupported package member: %s" % relative)
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
    if len(sys.argv) < 3:
        raise SystemExit("usage: package_archive.py OUTPUT PACKAGE...")
    output = os.path.abspath(sys.argv[1])
    work = output + ".work"
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, mode=0o700)
    try:
        _archive(output, _collect(sys.argv[2:], work))
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, tarfile.TarError, ValueError) as error:
        print("Debian package archive construction failed: %s" % error, file=sys.stderr)
        raise SystemExit(1)
