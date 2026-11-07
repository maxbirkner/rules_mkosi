"""Runs the production Debian tools launcher with runfiles, scratch, and bind paths that need escaping.

Bazel writes a runfiles-manifest entry in its escaped form when a path contains a space, newline, or backslash. The test
rewrites its own runfiles into such a manifest whose targets all pass through a directory with these characters, keeps
the launcher scratch and bind sources below that directory, and mounts a writable tmpfs inside the read-only source.
"""

import ctypes
import os
import pathlib
import re
import subprocess
import sys
import unittest

_SPECIAL_NAME = "space \\backslash\ttab\nnewline"
_CLONE_NEWNS = 0x00020000
_CLONE_NEWUSER = 0x10000000
_MS_REC = 0x4000
_MS_PRIVATE = 1 << 18
_NESTED_MARKER = "nested-writable\n"
_LAUNCHER_RLOCATION = ""
# Runfiles that the launcher itself resolves, as (repository, path). rules_cc falls back to the runfiles directory when
# a manifest lookup misses, so their tree links point to a missing decoy: only the decoded escaped manifest finds them.
_LAUNCHER_RUNFILES = {
    ("mkosi_debian_python", "python"),
    ("mkosi_debian_tools", "launcher_cli"),
    ("mkosi_debian_tools", "flat.tar"),
    ("mkosi_debian_tools", "launcher_config.json"),
    ("mkosi_debian_tools", "namespace_runner"),
    ("_main", "mkosi/debian/extract_tree.py"),
}

# The shell runs inside the namespace runner, and every check prints why it failed.
_PROBE = r"""
IFS= read -r value < /inputs/source/marker || { echo "read-only bind is unreadable" >&2; exit 1; }
[ "$value" = read-only-input ] || { echo "read-only bind has wrong contents: $value" >&2; exit 1; }
IFS= read -r value < /inputs/source/nested/marker || { echo "nested mount is not visible" >&2; exit 1; }
[ "$value" = nested-writable ] || { echo "nested mount has wrong contents: $value" >&2; exit 1; }
if (printf "x\n" > /inputs/source/written) 2>/dev/null; then echo "read-only bind is writable" >&2; exit 1; fi
if (printf "x\n" > /inputs/source/nested/written) 2>/dev/null; then
    echo "nested writable mount bypassed the read-only bind" >&2
    exit 1
fi
printf "written-output\n" > /outputs/destination/result
"""


def _unescape(text):
    return re.sub(r"\\([snb])", lambda match: {"s": " ", "n": "\n", "b": "\\"}[match.group(1)], text)


def _manifest_entries(manifest):
    """Yields (runfiles path, target) for each entry of a Bazel runfiles manifest, decoding escaped entries."""
    for line in manifest.read_text(encoding="utf-8").split("\n"):
        if not line:
            continue
        if line.startswith(" "):
            link, target = line[1:].split(" ", 1)
            yield _unescape(link), _unescape(target)
        else:
            link, target = line.split(" ", 1)
            yield link, target


def _escaped_entry(link, target):
    link = link.replace("\\", "\\b").replace(" ", "\\s").replace("\n", "\\n")
    target = target.replace("\\", "\\b").replace("\n", "\\n")
    return " %s %s\n" % (link, target)


def _own_runfiles():
    """Yields (runfiles path, target) for each runfile of this test, in manifest or directory mode."""
    manifest = os.environ.get("RUNFILES_MANIFEST_FILE")
    if manifest:
        yield from _manifest_entries(pathlib.Path(manifest))
        return
    root = os.environ["RUNFILES_DIR"]
    for directory, subdirectories, files in os.walk(root):
        linked_directories = [name for name in subdirectories if os.path.islink(os.path.join(directory, name))]
        for name in files + linked_directories:
            path = os.path.join(directory, name)
            if os.path.relpath(path, root) == "MANIFEST":
                continue
            target = os.path.join(directory, os.readlink(path)) if os.path.islink(path) else path
            yield os.path.relpath(path, root), target


def _is_launcher_runfile(link):
    repository, _, path = link.partition("/")
    return any(
        (repository == name or repository.endswith("+" + name)) and path == expected
        for name, expected in _LAUNCHER_RUNFILES
    )


def _write_escaped_runfiles(directory, root_link, manifest):
    """Writes a runfiles tree and an escaped manifest whose targets all pass through root_link, a link to /.

    Returns the runfiles paths whose tree links are decoys.
    """
    lines = []
    decoys = set()
    for link, target in _own_runfiles():
        path = directory / link
        path.parent.mkdir(parents=True, exist_ok=True)
        if target:
            escaped_target = str(root_link) + target
            if _is_launcher_runfile(link):
                decoys.add(link)
                path.symlink_to(directory / "missing decoy")
            else:
                path.symlink_to(escaped_target)
        else:
            escaped_target = ""
            path.touch()
        lines.append(_escaped_entry(link, escaped_target))
    manifest.write_text("".join(lines), encoding="utf-8")
    return decoys


def _check(result, operation):
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, "%s: %s" % (operation, os.strerror(error)))


def _mount_writable_tmpfs(nested):
    """Enters private user and mount namespaces and mounts a writable tmpfs at nested; runs in the forked child."""
    uid = os.getuid()
    gid = os.getgid()
    libc = ctypes.CDLL(None, use_errno=True)
    _check(libc.unshare(_CLONE_NEWUSER | _CLONE_NEWNS), "unshare")
    pathlib.Path("/proc/self/setgroups").write_text("deny", encoding="ascii")
    pathlib.Path("/proc/self/uid_map").write_text("%d %d 1" % (uid, uid), encoding="ascii")
    pathlib.Path("/proc/self/gid_map").write_text("%d %d 1" % (gid, gid), encoding="ascii")
    _check(libc.mount(None, b"/", None, _MS_REC | _MS_PRIVATE, None), "make mounts private")
    _check(libc.mount(b"tmpfs", os.fsencode(nested), b"tmpfs", 0, b"mode=0755"), "mount nested tmpfs")
    (nested / "marker").write_text(_NESTED_MARKER, encoding="utf-8")


class DebianToolsEscapedPathsTest(unittest.TestCase):
    def setUp(self):
        self.base = pathlib.Path(os.environ["TEST_TMPDIR"]) / _SPECIAL_NAME
        self.base.mkdir()
        root_link = self.base / "root"
        root_link.symlink_to("/")
        # rules_python derives the runfiles root from a manifest named like Bazel's, NAME.runfiles_manifest.
        self.runfiles_dir = self.base / "launcher.runfiles"
        self.runfiles_dir.mkdir()
        self.manifest = self.base / "launcher.runfiles_manifest"
        self.decoys = _write_escaped_runfiles(self.runfiles_dir, root_link, self.manifest)
        self.source = self.base / "read-only source"
        (self.source / "nested").mkdir(parents=True)
        (self.source / "marker").write_text("read-only-input\n", encoding="utf-8")
        self.destination = self.base / "read-write destination"
        self.destination.mkdir()

    def test_nested_writable_mount_stays_read_only_under_escaped_paths(self):
        self.assertIn("\n ", self.manifest.read_text(encoding="utf-8"), "the manifest has no escaped entries")
        self.assertEqual(len(self.decoys), len(_LAUNCHER_RUNFILES), self.decoys)
        launcher = self.runfiles_dir / _LAUNCHER_RLOCATION
        nested = self.source / "nested"
        result = subprocess.run(
            [
                str(launcher),
                "--ro-bind",
                "%s:/inputs/source" % self.source,
                "--rw-bind",
                "%s:/outputs/destination" % self.destination,
                "/bin/sh",
                "-c",
                _PROBE,
            ],
            env={
                "PATH": "",
                "RUNFILES_DIR": str(self.runfiles_dir),
                "RUNFILES_MANIFEST_FILE": str(self.manifest),
                "MKOSI_DEBIAN_TOOLS_SCRATCH": str(self.base / "launcher scratch"),
            },
            preexec_fn=lambda: _mount_writable_tmpfs(nested),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.destination / "result").read_text(encoding="utf-8"), "written-output\n")
        self.assertFalse((nested / "marker").exists(), "nested tmpfs leaked out of the private mount namespace")


if __name__ == "__main__":
    _LAUNCHER_RLOCATION = sys.argv.pop(1)
    unittest.main()
