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

# Debian's systemd package intentionally ships this link to an empty
# configuration directory.  Keep a marker in the target so TreeArtifact
# consumers retain the directory when Bazel materializes the output.
_EMPTY_DIRECTORY_SYMLINK_TARGETS = {
    "etc/xdg/systemd/user": ("etc/systemd/user", "../../systemd/user"),
    "usr/lib/ssl/private": ("etc/ssl/private", "/etc/ssl/private"),
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
            os.chmod(parent, 0o755)
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


def _digest_file(source):
    hasher = hashlib.sha256()
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


def set_deterministic_metadata(root):
    for directory, dirnames, names in os.walk(root, topdown=False):
        for name in names + dirnames:
            path = os.path.join(directory, name)
            os.utime(path, (0, 0), follow_symlinks=False)
        os.utime(directory, (0, 0), follow_symlinks=False)
    os.utime(root, (0, 0), follow_symlinks=False)


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
        os.chmod(bundle, 0o644)


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


def _materialize_empty_directory_symlink_targets(root, symlinks):
    for relative, (target, expected_linkname) in _EMPTY_DIRECTORY_SYMLINK_TARGETS.items():
        member = symlinks.get(relative)
        if member is None or member.linkname != expected_linkname:
            continue
        directory = os.path.join(root, target)
        if not os.path.isdir(directory) or os.path.islink(directory):
            continue
        marker = os.path.join(directory, ".rules_mkosi_empty_directory")
        if not os.path.exists(marker):
            with open(marker, "wb"):
                pass
            os.chmod(marker, 0o644)


def _raw_link_components(relative, linkname):
    if linkname.startswith("/"):
        return linkname.split("/")
    parent = os.path.dirname(relative).split(os.sep) if os.path.dirname(relative) else []
    return parent + linkname.split("/")


def _resolve_link_path(relative, symlinks, members_by_path):
    components = _raw_link_components(relative, symlinks[relative].linkname)
    resolved_components = []
    dependencies = []
    seen = set()
    resolutions = 0
    while components:
        component = components.pop(0)
        if component in ("", "."):
            continue
        if component == "..":
            if not resolved_components:
                raise ValueError("symlink escapes output root: %s" % relative)
            resolved_components.pop()
            continue
        resolved_components.append(component)
        current = os.path.join(*resolved_components)
        member = members_by_path.get(current)
        if member is not None and member.issym():
            if current in seen:
                raise ValueError("symlink cycle involving: %s" % current)
            seen.add(current)
            dependencies.append(current)
            resolved_components = []
            components = _raw_link_components(current, member.linkname) + components
            resolutions += 1
            if resolutions > len(symlinks) + len(components) + 1:
                raise ValueError("symlink graph resolution exceeded its bound: %s" % relative)
            continue
    return (os.path.join(*resolved_components) if resolved_components else ""), dependencies


def _resolve_symlink_graph(root, symlinks, members_by_path):
    state = {}
    resolved = {}
    dependencies = {}

    def visit(relative):
        if state.get(relative) == "visiting":
            raise ValueError("symlink cycle involving: %s" % relative)
        if state.get(relative) == "done":
            return
        state[relative] = "visiting"
        target, direct_dependencies = _resolve_link_path(relative, symlinks, members_by_path)
        for dependency in direct_dependencies:
            if dependency != relative:
                visit(dependency)
        dependencies[relative] = direct_dependencies
        target_path = os.path.join(root, target)
        if not os.path.exists(target_path):
            if relative not in _ALLOWED_DANGLING_SYMLINKS:
                raise ValueError("dangling symlink: %s -> %s" % (relative, symlinks[relative].linkname))
        state[relative] = "done"
        resolved[relative] = target

    for relative in sorted(symlinks):
        visit(relative)

    # The DFS above validates every edge before any link is created.  Create
    # links in graph order so forward chains work regardless of tar order.
    def depth(relative):
        return max((depth(dependency) for dependency in dependencies[relative]), default=0) + 1

    for relative in sorted(symlinks, key=lambda item: (depth(item), item)):
        member = symlinks[relative]
        _parent(root, relative)
        destination = os.path.join(root, relative)
        if os.path.lexists(destination):
            raise ValueError("archive path collision: %s" % relative)
        target = resolved[relative]
        if member.linkname.startswith("/"):
            # Keep links rooted inside the extracted tree even when the
            # archive used an absolute Debian path; TreeArtifact validation
            # must not resolve it against the host root.
            linkname = os.path.relpath(os.path.join(root, target), os.path.dirname(destination))
        else:
            linkname = member.linkname
        os.symlink(linkname, destination)


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
    archive_path = os.path.realpath(archive)
    archive_fd = os.open(archive_path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    with os.fdopen(archive_fd, "rb") as archive_stream:
        actual_digest = _digest_file(archive_stream)
        if actual_digest != expected_digest:
            raise ValueError(
                "Debian tools archive digest mismatch: expected=%s actual=%s"
                % (expected_digest, actual_digest)
            )
        archive_stream.seek(0)
        # Authentication deliberately precedes tarfile.open: a tampered
        # archive must not be parsed or partially materialized. Both phases
        # operate on this one no-follow descriptor.
        root = os.path.abspath(root)
        os.makedirs(root, exist_ok=True)
        os.chmod(root, 0o755)
        with tarfile.open(fileobj=archive_stream, mode="r:*") as source:
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
            _materialize_empty_directory_symlink_targets(root, symlinks)
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
    set_deterministic_metadata(root)


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
