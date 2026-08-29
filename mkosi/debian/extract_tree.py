"""Safely extract a Debian tools tarball into a Bazel TreeArtifact."""

import os
import stat
import sys
import tarfile


def _member_path(name):
    if name.startswith("/"):
        raise ValueError("absolute archive member: %s" % name)
    while name.startswith("./"):
        name = name[2:]
    if name in ("", "."):
        return ""
    parts = name.split("/")
    if parts and parts[-1] == "":
        parts.pop()
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise ValueError("unsafe archive member: %s" % name)
    return os.path.join(*parts)


def _parent(root, relative):
    parent = root
    for part in os.path.dirname(relative).split(os.sep):
        if not part:
            continue
        parent = os.path.join(parent, part)
        if os.path.lexists(parent):
            if not stat.S_ISDIR(os.lstat(parent).st_mode):
                raise ValueError("archive member parent is not a directory: %s" % relative)
        else:
            os.mkdir(parent)
    return parent


def _link_target(relative, linkname):
    if linkname.startswith("/"):
        target = _member_path(linkname[1:])
        return target
    target = os.path.normpath(os.path.join(os.path.dirname(relative), linkname))
    if target == ".." or target.startswith("../"):
        raise ValueError("symlink escapes output root: %s -> %s" % (relative, linkname))
    return target


def extract(archive, root):
    root = os.path.abspath(root)
    os.makedirs(root, exist_ok=True)
    with tarfile.open(archive, mode="r:*") as source:
        members = [
            (member, relative)
            for member in source
            for relative in [_member_path(member.name)]
            if relative
        ]
        members_by_path = {relative: member for member, relative in members}
        if len(members_by_path) != len(members):
            raise ValueError("duplicate archive member")

        # Real directories and regular files are created before links, so an
        # archive link can never redirect a later parent creation.
        for member, relative in sorted(members, key=lambda item: (item[1].count(os.sep), item[1])):
            destination = os.path.join(root, relative)
            if member.isdir():
                _parent(root, relative)
                if os.path.lexists(destination) and not stat.S_ISDIR(os.lstat(destination).st_mode):
                    raise ValueError("archive path collision: %s" % relative)
                if not os.path.exists(destination):
                    os.mkdir(destination)
                os.chmod(destination, stat.S_IMODE(member.mode))
            elif member.isfile():
                _parent(root, relative)
                if os.path.lexists(destination):
                    raise ValueError("archive path collision: %s" % relative)
                with source.extractfile(member) as source_file, open(destination, "wb") as output:
                    while True:
                        chunk = source_file.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                os.chmod(destination, stat.S_IMODE(member.mode))
            elif member.islnk():
                target = _link_target(relative, member.linkname)
                _parent(root, relative)
                target_path = os.path.join(root, target)
                if not os.path.isfile(target_path):
                    raise ValueError("hardlink target is not a regular file: %s" % relative)
                if os.path.lexists(destination):
                    raise ValueError("archive path collision: %s" % relative)
                os.link(target_path, destination)
            elif not member.issym():
                raise ValueError("unsupported archive member: %s" % relative)

        certificates = []
        certificate_root = os.path.join(root, "usr/share/ca-certificates")
        if os.path.isdir(certificate_root):
            for directory, _, names in os.walk(certificate_root):
                for name in sorted(names):
                    if name.endswith(".crt"):
                        certificates.append(os.path.join(directory, name))
        if certificates:
            bundle = os.path.join(root, "etc/ssl/certs/ca-certificates.crt")
            _parent(root, "etc/ssl/certs/ca-certificates.crt")
            with open(bundle, "wb") as output:
                for certificate in sorted(certificates):
                    with open(certificate, "rb") as source:
                        output.write(source.read())
                    output.write(b"\n")

        for member, relative in members:
            if not member.issym():
                continue
            target = _link_target(relative, member.linkname)
            destination = os.path.join(root, relative)
            _parent(root, relative)
            if os.path.lexists(destination):
                raise ValueError("archive path collision: %s" % relative)
            # Optional Debian links are omitted when their package target is
            # absent; no synthetic files may mask missing package content.
            if not os.path.exists(os.path.join(root, target)):
                continue
            linkname = os.path.relpath(os.path.join(root, target), os.path.dirname(destination))
            os.symlink(linkname, destination)

    for directory, dirnames, names in os.walk(root):
        for name in names + dirnames:
            path = os.path.join(directory, name)
            if os.path.islink(path) and not os.path.exists(path):
                os.unlink(path)
    optional_masks = (
        os.path.join(root, "etc/xdg/systemd/user"),
    )
    for path in optional_masks:
        if os.path.islink(path) and not os.path.exists(path):
            os.unlink(path)

    for legacy, target in (
        ("bin", "usr/bin"),
        ("sbin", "usr/sbin"),
        ("lib", "usr/lib"),
        ("lib64", "usr/lib/x86_64-linux-gnu"),
    ):
        path = os.path.join(root, legacy)
        if os.path.islink(path):
            os.unlink(path)
        elif os.path.isdir(path):
            os.rmdir(path)
        elif os.path.exists(path):
            raise ValueError("legacy merged-usr path collision: %s" % legacy)
        os.symlink(target, path)
    temporary = os.path.join(root, "tmp")
    if os.path.isdir(temporary) and not os.path.islink(temporary):
        os.rmdir(temporary)


def main():
    extract(*sys.argv[1:])


if __name__ == "__main__":
    try:
        main()
    except (OSError, tarfile.TarError, ValueError) as error:
        print("Debian tools extraction failed: %s" % error, file=sys.stderr)
        sys.exit(1)
