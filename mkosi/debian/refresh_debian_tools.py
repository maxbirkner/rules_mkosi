"""Refreshes the built-in Debian tools snapshot of rules_mkosi.

Run it from the root module:

    bazel run //mkosi/debian:refresh_debian_tools -- --snapshot 20260912T080811Z \\
        [--python-release 20261026 --python-version 3.14.10]

It points the specification at the snapshot, regenerates the lock, and rewrites the snapshot, the lock and archive
digests, and optionally the static Python pin in provenance.bzl. It also moves the test configurations and README
examples from the old snapshot to the new one. The archive digest is the SHA-256 of
@mkosi_debian_tools//:tree, which the command builds with Bazel after it has written the new lock.
"""

import argparse
import datetime
import hashlib
import os
import pathlib
import re
import subprocess
import sys
import urllib.parse

# The runfiles path, not the source tree that it links to, so that bytecode caches stay out of the source tree.
sys.path.insert(0, str(pathlib.Path(__file__).parent))

import generate_lock
import http_download

PROVENANCE = "mkosi/debian/provenance.bzl"
SPEC = "mkosi/debian/debian13.spec.json"
LOCK = "mkosi/debian/debian13.lock.json"
ARCHIVE_TARGET = "@mkosi_debian_tools//:tree"
# Files and directories whose snapshot references follow the built-in snapshot.
SNAPSHOT_USERS = ("README.md", "mkosi/tests/testdata", "e2e/smoke/testdata")

_SNAPSHOT = re.compile(r"[0-9]{8}T[0-9]{6}Z")
_SNAPSHOT_URL = "https://snapshot.debian.org/archive/debian/{}"
_PYTHON_RELEASES = "https://github.com/astral-sh/python-build-standalone/releases/download/{}/"
_PYTHON_ASSET = "cpython-{version}+{release}-x86_64-unknown-linux-musl-lto+static-full.tar.zst"


def snapshot_epoch(snapshot):
    """Returns the Unix time of a snapshot timestamp such as 20260912T080811Z."""
    moment = datetime.datetime.strptime(snapshot, "%Y%m%dT%H%M%SZ").replace(tzinfo=datetime.timezone.utc)
    return int(moment.timestamp())


def read_provenance(text):
    """Returns the string constants of provenance.bzl."""
    return dict(re.findall(r'^(DEBIAN_TOOLS_[A-Z0-9_]+) = "([^"]*)"$', text, re.MULTILINE))


def rewrite_provenance(text, values):
    """Returns provenance.bzl with the string constants in values replaced; every name must already exist."""
    for name, value in values.items():
        text, count = re.subn(r'^{} = "[^"]*"$'.format(name), '{} = "{}"'.format(name, value), text, flags=re.M)
        if count != 1:
            raise ValueError("provenance.bzl does not define {} exactly once".format(name))
    return text


def replace_snapshot(text, old, new):
    """Returns text with the old snapshot timestamp and its Unix time replaced by the new ones."""
    return text.replace(old, new).replace(str(snapshot_epoch(old)), str(snapshot_epoch(new)))


def python_pin(release, version, sums):
    """Returns the provenance constants of a python-build-standalone release given its SHA256SUMS text."""
    asset = _PYTHON_ASSET.format(version=version, release=release)
    digests = [line.split()[0] for line in sums.splitlines() if line.split()[1:] == [asset]]
    if len(digests) != 1:
        raise ValueError("SHA256SUMS of python-build-standalone {} does not list {}".format(release, asset))
    return {
        "DEBIAN_TOOLS_PYTHON_VERSION": version,
        "DEBIAN_TOOLS_PYTHON_URL": _PYTHON_RELEASES.format(release) + urllib.parse.quote(asset),
        "DEBIAN_TOOLS_PYTHON_SHA256": digests[0],
    }


def _download_python_pin(release, version):
    sums = http_download.download(_PYTHON_RELEASES.format(release) + "SHA256SUMS", "rules_mkosi-refresh", timeout=60)
    return python_pin(release, version, sums.decode("utf-8"))


def _update(path, transform):
    text = path.read_text(encoding="utf-8")
    updated = transform(text)
    if updated != text:
        path.write_text(updated, encoding="utf-8")


def _snapshot_files(workspace, snapshot):
    """Yields the regular files of SNAPSHOT_USERS that mention snapshot."""
    for name in SNAPSHOT_USERS:
        path = workspace / name
        for file in sorted(path.rglob("*")) if path.is_dir() else (path,):
            if file.is_file() and not file.is_symlink() and snapshot.encode() in file.read_bytes():
                yield file


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bazel(workspace, *arguments):
    command = [os.environ.get("BAZEL", "bazel"), *arguments]
    return subprocess.run(command, cwd=workspace, check=True, stdout=subprocess.PIPE, text=True).stdout


def _archive_sha256(workspace):
    _bazel(workspace, "build", ARCHIVE_TARGET)
    archive = _bazel(workspace, "cquery", "--output=files", ARCHIVE_TARGET).split()
    return _sha256(pathlib.Path(_bazel(workspace, "info", "execution_root").strip(), archive[0]))


def _write_lock(workspace, snapshot):
    url = _SNAPSHOT_URL.format(snapshot)
    _update(workspace / SPEC, lambda text: re.sub(re.escape(_SNAPSHOT_URL.format("")) + _SNAPSHOT.pattern, url, text))
    if generate_lock.main(["--spec", SPEC, "--output", LOCK]) != 0:
        raise SystemExit("Debian lock generation failed")
    return {
        "DEBIAN_TOOLS_SNAPSHOT": snapshot,
        "DEBIAN_TOOLS_SNAPSHOT_URL": url,
        "DEBIAN_TOOLS_LOCK_SHA256": _sha256(workspace / LOCK),
    }


def refresh(workspace, snapshot, python=None):
    """Refreshes the snapshot in workspace and returns the provenance values it wrote."""
    provenance = workspace / PROVENANCE
    old_snapshot = read_provenance(provenance.read_text(encoding="utf-8"))["DEBIAN_TOOLS_SNAPSHOT"]
    values = _write_lock(workspace, snapshot)
    if python:
        values |= _download_python_pin(*python)
    _update(provenance, lambda text: rewrite_provenance(text, values))
    for path in _snapshot_files(workspace, old_snapshot):
        _update(path, lambda text: replace_snapshot(text, old_snapshot, snapshot))
    archive = {"DEBIAN_TOOLS_ARCHIVE_SHA256": _archive_sha256(workspace)}
    _update(provenance, lambda text: rewrite_provenance(text, archive))
    return values | archive


def _parser():
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--snapshot", required=True, help="snapshot.debian.org timestamp, such as 20260912T080811Z")
    parser.add_argument("--python-release", help="python-build-standalone release of the static Python, a date")
    parser.add_argument("--python-version", help="CPython version in that release, such as 3.14.10")
    return parser


def main(argv=None):
    parser = _parser()
    args = parser.parse_args(argv)
    if not _SNAPSHOT.fullmatch(args.snapshot):
        parser.error("--snapshot must look like 20260912T080811Z")
    if (args.python_release is None) != (args.python_version is None):
        parser.error("--python-release and --python-version must be given together")
    python = (args.python_release, args.python_version) if args.python_release else None
    workspace = pathlib.Path(os.environ["BUILD_WORKSPACE_DIRECTORY"])
    for name, value in sorted(refresh(workspace, args.snapshot, python).items()):
        print('{} = "{}"'.format(name, value))
    return 0


if __name__ == "__main__":
    sys.exit(main())
