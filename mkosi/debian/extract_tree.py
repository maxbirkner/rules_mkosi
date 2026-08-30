"""Safely extract an authenticated Debian tools tarball.

The package flattener emits a tar archive whose links are not guaranteed to
be ordered.  Extraction therefore builds the complete member graph first and
materializes regular objects before resolving hardlink and symlink edges.
"""

import hashlib
import os
import stat
import sys
import tarfile


# These links are intentionally dangling in the flattened Debian package
# set.  The service masks become valid when bubblewrap supplies /dev/null;
# environment.d and the two optional compatibility links are package-provided
# links whose targets are outside this closure.  Their inert placeholders are
# kept inside the tree so no archive links disappear.  All other dangling
# links are archive corruption or an incomplete package closure.
_ALLOWED_DANGLING_SYMLINKS = {
    "etc/modules-load.d/modules.conf",
    "etc/rmt",
    "usr/lib/environment.d/99-environment.conf",
    "usr/lib/systemd/system/cryptdisks-early.service",
    "usr/lib/systemd/system/cryptdisks.service",
    "usr/lib/systemd/system/hwclock.service",
    "usr/lib/systemd/system/x11-common.service",
}


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


def _hardlink_target(linkname):
    # GNU tar records hardlink names relative to the archive root, unlike
    # symlink names which are interpreted relative to their containing path.
    if linkname.startswith("/"):
        raise ValueError("absolute hardlink target: %s" % linkname)
    return _member_path(linkname)


def _digest(archive):
    hasher = hashlib.sha256()
    with open(archive, "rb") as source:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _prepare_mount_roots(root):
    for relative in ("etc", "root", "tmp", "proc", "dev", "workspace", "inputs", "outputs"):
        destination = os.path.join(root, relative)
        if os.path.lexists(destination):
            if not stat.S_ISDIR(os.lstat(destination).st_mode):
                raise ValueError("required namespace mount root is not a directory: %s" % relative)
        else:
            _parent(root, relative)
            os.mkdir(destination)
        os.chmod(destination, 0o755)


def _write_ca_bundle(root):
    certificates = []
    certificate_root = os.path.join(root, "usr/share/ca-certificates")
    if os.path.isdir(certificate_root):
        for directory, dirnames, names in os.walk(certificate_root):
            dirnames.sort()
            for name in sorted(names):
                if name.endswith(".crt"):
                    path = os.path.join(directory, name)
                    if os.path.isfile(path):
                        certificates.append(path)
    if certificates:
        bundle = os.path.join(root, "etc/ssl/certs/ca-certificates.crt")
        _parent(root, "etc/ssl/certs/ca-certificates.crt")
        with open(bundle, "wb") as output:
            for certificate in certificates:
                with open(certificate, "rb") as source:
                    output.write(source.read())
                output.write(b"\n")


def _materialize_runtime_link_targets(root):
    # TreeArtifacts cannot contain dangling links.  These placeholders are
    # hidden by the runtime /dev mount or only serve the package's documented
    # compatibility link; their link names remain preserved.
    for relative in ("etc/environment", "dev/null", "etc/modules", "usr/sbin/rmt"):
        path = os.path.join(root, relative)
        if not os.path.exists(path):
            _parent(root, relative)
            with open(path, "wb"):
                pass
            os.chmod(path, 0o644)


def _resolve_symlink_graph(root, symlinks, members_by_path):
    state = {}
    resolved = {}

    def visit(relative):
        if state.get(relative) == "visiting":
            raise ValueError("symlink cycle involving: %s" % relative)
        if state.get(relative) == "done":
            return
        state[relative] = "visiting"
        target = _link_target(relative, symlinks[relative].linkname)
        target_path = os.path.join(root, target)
        target_member = members_by_path.get(target)
        if target_member is not None and target_member.issym():
            visit(target)
        elif not os.path.exists(target_path):
            if relative not in _ALLOWED_DANGLING_SYMLINKS:
                raise ValueError("dangling symlink: %s -> %s" % (relative, symlinks[relative].linkname))
        state[relative] = "done"
        resolved[relative] = target

    for relative in sorted(symlinks):
        visit(relative)

    # The DFS above validates every edge before any link is created.  Create
    # links in graph order so forward chains work regardless of tar order.
    for relative in sorted(symlinks, key=lambda item: _symlink_depth(item, symlinks)):
        member = symlinks[relative]
        _parent(root, relative)
        destination = os.path.join(root, relative)
        if os.path.lexists(destination):
            raise ValueError("archive path collision: %s" % relative)
        target = _link_target(relative, member.linkname)
        # Keep links rooted inside the extracted tree even when the archive
        # used an absolute Debian path; TreeArtifact validation must not
        # resolve it against the host root.
        linkname = os.path.relpath(os.path.join(root, target), os.path.dirname(destination))
        os.symlink(linkname, destination)


def _symlink_depth(relative, symlinks):
    seen = set()
    depth = 0
    current = relative
    while current in symlinks and current not in seen:
        seen.add(current)
        current = _link_target(current, symlinks[current].linkname)
        depth += 1
    return (depth, relative)


def _resolve_hardlink_graph(root, hardlinks, members_by_path):
    state = {}
    targets = {}

    def visit(relative):
        if state.get(relative) == "visiting":
            raise ValueError("hardlink cycle involving: %s" % relative)
        if state.get(relative) == "done":
            return targets[relative]
        state[relative] = "visiting"
        target = _hardlink_target(hardlinks[relative].linkname)
        target_member = members_by_path.get(target)
        if target_member is None:
            raise ValueError("dangling hardlink: %s -> %s" % (relative, target))
        if target_member.islnk():
            target = visit(target)
        elif not target_member.isfile():
            raise ValueError("hardlink target is not a regular file: %s" % relative)
        state[relative] = "done"
        targets[relative] = target
        return target

    for relative in sorted(hardlinks):
        target = visit(relative)
        _parent(root, relative)
        destination = os.path.join(root, relative)
        if os.path.lexists(destination):
            raise ValueError("archive path collision: %s" % relative)
        os.link(os.path.join(root, target), destination)


def extract(archive, root, expected_digest):
    if not expected_digest:
        raise ValueError("expected archive digest is required")
    actual_digest = _digest(archive)
    if actual_digest != expected_digest:
        raise ValueError(
            "Debian tools archive digest mismatch: expected=%s actual=%s"
            % (expected_digest, actual_digest)
        )

    root = os.path.abspath(root)
    os.makedirs(root, exist_ok=True)
    # Authentication deliberately precedes tarfile.open: a tampered archive
    # must not be parsed or partially materialized.
    with tarfile.open(archive, mode="r:*") as source:
        members = []
        members_by_path = {}
        for member in source:
            relative = _member_path(member.name)
            if not relative:
                continue
            if relative in members_by_path:
                raise ValueError("duplicate archive member")
            members.append((member, relative))
            members_by_path[relative] = member

        symlinks = {relative: member for member, relative in members if member.issym()}
        hardlinks = {relative: member for member, relative in members if member.islnk()}

        # Materialize real directories and files first.  In particular, no
        # archive symlink can redirect a later parent creation.
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
                source_file = source.extractfile(member)
                if source_file is None:
                    raise ValueError("regular archive member has no data: %s" % relative)
                with source_file, open(destination, "wb") as output:
                    while True:
                        chunk = source_file.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                os.chmod(destination, stat.S_IMODE(member.mode))
            elif not member.issym() and not member.islnk():
                raise ValueError("unsupported archive member: %s" % relative)

        _write_ca_bundle(root)
        _materialize_runtime_link_targets(root)
        _resolve_hardlink_graph(root, hardlinks, members_by_path)
        _resolve_symlink_graph(root, symlinks, members_by_path)

    _prepare_mount_roots(root)

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

    # The package archive contains tmp.mount metadata, but /tmp is a runtime
    # tmpfs and must never retain package files.
    temporary = os.path.join(root, "tmp")
    if os.path.isdir(temporary) and not os.path.islink(temporary):
        for name in os.listdir(temporary):
            raise ValueError("package content unexpectedly populated /tmp: %s" % name)


def main():
    if len(sys.argv) != 4:
        raise SystemExit("usage: extract_tree.py ARCHIVE ROOT EXPECTED_SHA256")
    extract(sys.argv[1], sys.argv[2], sys.argv[3])


if __name__ == "__main__":
    try:
        main()
    except (OSError, tarfile.TarError, ValueError) as error:
        print("Debian tools extraction failed: %s" % error, file=sys.stderr)
        sys.exit(1)
