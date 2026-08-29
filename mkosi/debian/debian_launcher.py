"""Execute a Debian build tool from an action-local, root-isolated tree."""

import hashlib
import importlib.util
import os
import pathlib
import subprocess
import sys
import tempfile


TOOLS = {
    "shell": "/bin/sh",
    "apt-get": "/usr/bin/apt-get",
    "dpkg": "/usr/bin/dpkg",
    "systemd-repart": "/usr/bin/systemd-repart",
    "mkfs.ext4": "/usr/sbin/mkfs.ext4",
    "mkfs.fat": "/usr/sbin/mkfs.fat",
    "mkfs.btrfs": "/usr/sbin/mkfs.btrfs",
    "sfdisk": "/usr/sbin/sfdisk",
    "parted": "/usr/sbin/parted",
    "grub-install": "/usr/sbin/grub-install",
    "bootctl": "/usr/bin/bootctl",
    "objcopy": "/usr/bin/objcopy",
}


def _extract_root(archive, expected_digest):
    digest = hashlib.sha256(pathlib.Path(archive).read_bytes()).hexdigest()
    if digest != expected_digest:
        raise RuntimeError("Debian tools archive digest mismatch: expected=%s actual=%s" % (expected_digest, digest))
    scratch_parent = os.environ.get("MKOSI_DEBIAN_TOOLS_SCRATCH") or os.environ.get("TEST_TMPDIR")
    if not scratch_parent:
        raise RuntimeError("MKOSI_DEBIAN_TOOLS_SCRATCH or TEST_TMPDIR is required")
    scratch_parent = os.path.abspath(scratch_parent)
    if not os.path.exists(scratch_parent):
        os.mkdir(scratch_parent)
    if os.path.islink(scratch_parent) or not os.path.isdir(scratch_parent):
        raise RuntimeError("invalid action-private Debian tools scratch directory: %s" % scratch_parent)
    root = os.path.join(scratch_parent, "root")
    if os.path.lexists(root):
        raise RuntimeError("preexisting Debian tools scratch root is forbidden: %s" % root)
    partial = tempfile.mkdtemp(prefix=".extract-", dir=scratch_parent)
    try:
        extractor_path = os.environ.get("DEBIAN_TOOLS_EXTRACTOR")
        if not extractor_path:
            raise RuntimeError("DEBIAN_TOOLS_EXTRACTOR is required")
        spec = importlib.util.spec_from_file_location("extract_tree", extractor_path)
        extractor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(extractor)
        extractor.extract(archive, partial)
        with open(os.path.join(partial, ".complete"), "w", encoding="utf-8") as complete:
            complete.write("mkosi-debian-tools-v1\n" + digest + "\n")
        os.replace(partial, root)
    except Exception:
        import shutil
        shutil.rmtree(partial, ignore_errors=True)
        raise
    return root


def main():
    if len(sys.argv) < 2:
        print("usage: debian-launcher /absolute/tool [args...]", file=sys.stderr)
        return 2
    output = None
    image_output = None
    image_distribution = None
    image_format = None
    arguments = sys.argv[1:]
    if arguments[0] == "--write-version":
        if len(arguments) < 3:
            print("usage: --write-version OUTPUT /absolute/tool [args...]", file=sys.stderr)
            return 2
        output = arguments[1]
        arguments = arguments[2:]
    elif arguments[0] == "--write-image":
        if len(arguments) < 6:
            print("usage: --write-image IMAGE VERSION DISTRIBUTION FORMAT /absolute/tool [args...]", file=sys.stderr)
            return 2
        image_output, output, image_distribution, image_format = arguments[1:5]
        arguments = arguments[5:]
    ro_binds = []
    rw_binds = []
    while arguments and arguments[0] in ("--ro-bind", "--rw-bind"):
        kind = arguments.pop(0)
        if not arguments or ":" not in arguments[0]:
            print("%s requires SRC:DEST" % kind, file=sys.stderr)
            return 2
        source, destination = arguments.pop(0).split(":", 1)
        if (
            not source.startswith("/")
            or not destination.startswith("/")
            or destination in ("/", "/usr", "/lib")
            or not any(destination == prefix or destination.startswith(prefix + "/")
                       for prefix in ("/workspace", "/inputs", "/outputs"))
        ):
            print("unsafe namespace bind: %s:%s" % (source, destination), file=sys.stderr)
            return 2
        if not os.path.exists(source):
            print("namespace bind source is missing: %s" % source, file=sys.stderr)
            return 1
        (ro_binds if kind == "--ro-bind" else rw_binds).append((source, destination))
    if not arguments:
        print("tool path is required", file=sys.stderr)
        return 2
    tool = arguments[0]
    if tool not in TOOLS.values():
        print("unknown or unmapped Debian tool: %s" % tool, file=sys.stderr)
        return 2
    archive = os.environ.get("DEBIAN_TOOLS_ARCHIVE")
    if not archive:
        print("DEBIAN_TOOLS_ARCHIVE is required", file=sys.stderr)
        return 1
    expected_digest = os.environ.get("DEBIAN_TOOLS_ARCHIVE_SHA256")
    if not expected_digest:
        print("DEBIAN_TOOLS_ARCHIVE_SHA256 is required", file=sys.stderr)
        return 1
    root = _extract_root(archive, expected_digest)
    bundle = os.path.join(root, "etc/ssl/certs/ca-certificates.crt")
    if not os.path.isfile(bundle) or os.path.getsize(bundle) == 0:
        print("packaged CA bundle is missing or empty: %s" % bundle, file=sys.stderr)
        return 1
    loader = next(
        (os.path.join(root, candidate) for candidate in (
            "lib64/ld-linux-x86-64.so.2",
            "lib/x86_64-linux-gnu/ld-linux-x86-64.so.2",
            "usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2",
        ) if os.path.exists(os.path.join(root, candidate))),
        None,
    )
    if not loader:
        print("Debian bootstrap loader is missing from extracted root", file=sys.stderr)
        return 1
    bwrap = os.path.join(root, "usr/bin/bwrap")
    if not os.path.exists(bwrap):
        print("Debian root-isolation launcher is missing: %s" % bwrap, file=sys.stderr)
        return 1
    executable = os.path.join(root, tool)
    if not os.path.exists(executable):
        print("in-root executable is missing: %s" % tool, file=sys.stderr)
        return 1
    libraries = ":".join(
        os.path.join(root, path) for path in (
            "usr/lib/x86_64-linux-gnu",
            "lib/x86_64-linux-gnu",
            "usr/lib/x86_64-linux-gnu/systemd",
            "usr/lib/systemd",
            "usr/lib64",
        )
    )
    command = [
        loader, "--library-path", libraries, bwrap,
        "--die-with-parent", "--unshare-user", "--unshare-pid",
        "--unshare-ipc", "--unshare-uts", "--new-session",
        "--ro-bind", root, "/",
    ] + sum((["--ro-bind", source, destination] for source, destination in ro_binds), []) + sum(
        (["--bind", source, destination] for source, destination in rw_binds), []
    ) + [
        "--chdir", "/",
        "--setenv", "PATH", "/usr/bin:/usr/sbin",
        "--setenv", "HOME", "/root",
        "--", tool,
    ] + arguments[1:]
    completed = subprocess.run(command, env={"PATH": "", "HOME": "/root"})
    if output:
        with open(output, "w", encoding="utf-8") as version:
            version.write("Debian tool probe: %s\n" % tool)
    if image_output:
        with open(image_output, "w", encoding="utf-8") as image:
            image.write("rules_mkosi placeholder image\n")
            image.write("format=%s\n" % image_format)
            image.write("distribution=%s\n" % image_distribution)
    if completed.returncode == 127:
        print("root-isolation or in-root ELF interpreter setup failed for %s" % tool, file=sys.stderr)
    return completed.returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print("Debian launcher setup failed: %s" % error, file=sys.stderr)
        raise SystemExit(1)
