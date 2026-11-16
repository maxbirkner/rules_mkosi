"""Refreshes the built-in Debian tools snapshot of rules_mkosi.

Run it from the root module:

    bazel run //mkosi/debian:refresh_debian_tools -- --snapshot 20260912T080811Z \\
        [--python-release 20261026 --python-version 3.14.10]

It points the amd64 and arm64 specifications at the snapshot, regenerates both locks, and rewrites the snapshot, the
lock and archive digests, and optionally the static Python pins of both CPUs in provenance.bzl. It also moves the test
configurations and README examples from the old snapshot to the new one. The archive digests are the SHA-256 of
@mkosi_debian_tools//:tree and @mkosi_debian_tools//arm64:tree, which the command builds with Bazel after it has
written the new locks; building the arm64 archive only unpacks packages, so any host can do it.
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
from collections.abc import Callable, Iterator, Mapping, Sequence

# The runfiles path, not the source tree that it links to, so that bytecode caches stay out of the source tree.
sys.path.insert(0, str(pathlib.Path(__file__).parent))

import generate_lock
import http_download

PROVENANCE = "mkosi/debian/provenance.bzl"
SPEC = "mkosi/debian/debian13.spec.json"
LOCK = "mkosi/debian/debian13.lock.json"
ARM64_SPEC = "mkosi/debian/debian13.arm64.spec.json"
ARM64_LOCK = "mkosi/debian/debian13.arm64.lock.json"
# Each built-in specification, its lock, and the provenance.bzl constant that pins the lock's digest.
LOCKS = (
    (SPEC, LOCK, "DEBIAN_TOOLS_LOCK_SHA256"),
    (ARM64_SPEC, ARM64_LOCK, "DEBIAN_TOOLS_ARM64_LOCK_SHA256"),
)
# Each Debian tools archive and the provenance.bzl constant that pins its digest.
ARCHIVES = (
    ("@mkosi_debian_tools//:tree", "DEBIAN_TOOLS_ARCHIVE_SHA256"),
    ("@mkosi_debian_tools//arm64:tree", "DEBIAN_TOOLS_ARM64_ARCHIVE_SHA256"),
)
# Files and directories whose snapshot references follow the built-in snapshot.
SNAPSHOT_USERS = ("README.md", "mkosi/tests/testdata", "e2e/smoke/testdata")

_SNAPSHOT = re.compile(r"[0-9]{8}T[0-9]{6}Z")
_SNAPSHOT_URL = "https://snapshot.debian.org/archive/debian/{}"
_PYTHON_RELEASES = "https://github.com/astral-sh/python-build-standalone/releases/download/{}/"
_PYTHON_ASSET = "cpython-{version}+{release}-{cpu}-unknown-linux-musl-lto+static-full.tar.zst"
# The static interpreter of each CPU and the infix of its provenance.bzl constants.
_PYTHON_CPUS = (("x86_64", ""), ("aarch64", "_AARCH64"))


def snapshot_epoch(snapshot: str) -> int:
    """Returns the Unix time of a snapshot timestamp such as 20260912T080811Z."""
    moment = datetime.datetime.strptime(snapshot, "%Y%m%dT%H%M%SZ").replace(tzinfo=datetime.timezone.utc)
    return int(moment.timestamp())


def read_provenance(text: str) -> dict[str, str]:
    """Returns the string constants of provenance.bzl."""
    return dict(re.findall(r'^(DEBIAN_TOOLS_[A-Z0-9_]+) = "([^"]*)"$', text, re.MULTILINE))


def rewrite_provenance(text: str, values: Mapping[str, str]) -> str:
    """Returns provenance.bzl with the string constants in values replaced; every name must already exist."""
    for name, value in values.items():
        text, count = re.subn(r'^{} = "[^"]*"$'.format(name), '{} = "{}"'.format(name, value), text, flags=re.M)
        if count != 1:
            raise ValueError("provenance.bzl does not define {} exactly once".format(name))
    return text


def replace_snapshot(text: str, old: str, new: str) -> str:
    """Returns text with the old snapshot timestamp and its Unix time replaced by the new ones."""
    return text.replace(old, new).replace(str(snapshot_epoch(old)), str(snapshot_epoch(new)))


def python_pin(release: str, version: str, sums: str) -> dict[str, str]:
    """Returns the provenance constants of a python-build-standalone release given its SHA256SUMS text."""
    values = {"DEBIAN_TOOLS_PYTHON_VERSION": version}
    for cpu, infix in _PYTHON_CPUS:
        asset = _PYTHON_ASSET.format(version=version, release=release, cpu=cpu)
        digests = [line.split()[0] for line in sums.splitlines() if line.split()[1:] == [asset]]
        if len(digests) != 1:
            raise ValueError("SHA256SUMS of python-build-standalone {} does not list {}".format(release, asset))
        values["DEBIAN_TOOLS_PYTHON{}_URL".format(infix)] = _PYTHON_RELEASES.format(release) + urllib.parse.quote(asset)
        values["DEBIAN_TOOLS_PYTHON{}_SHA256".format(infix)] = digests[0]
    return values


def _download_python_pin(release: str, version: str) -> dict[str, str]:
    sums = http_download.download(_PYTHON_RELEASES.format(release) + "SHA256SUMS", "rules_mkosi-refresh", timeout=60)
    return python_pin(release, version, sums.decode("utf-8"))


def _update(path: pathlib.Path, transform: Callable[[str], str]) -> None:
    text = path.read_text(encoding="utf-8")
    updated = transform(text)
    if updated != text:
        path.write_text(updated, encoding="utf-8")


def _snapshot_files(workspace: pathlib.Path, snapshot: str) -> Iterator[pathlib.Path]:
    """Yields the regular files of SNAPSHOT_USERS that mention snapshot."""
    for name in SNAPSHOT_USERS:
        path = workspace / name
        for file in sorted(path.rglob("*")) if path.is_dir() else (path,):
            if file.is_file() and not file.is_symlink() and snapshot.encode() in file.read_bytes():
                yield file


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bazel(workspace: pathlib.Path, *arguments: str) -> str:
    command = [os.environ.get("BAZEL", "bazel"), *arguments]
    return subprocess.run(command, cwd=workspace, check=True, stdout=subprocess.PIPE, text=True).stdout


def _archive_sha256(workspace: pathlib.Path, target: str) -> str:
    _bazel(workspace, "build", target)
    archive = _bazel(workspace, "cquery", "--output=files", target).split()
    return _sha256(pathlib.Path(_bazel(workspace, "info", "execution_root").strip(), archive[0]))


def _write_locks(workspace: pathlib.Path, snapshot: str) -> dict[str, str]:
    url = _SNAPSHOT_URL.format(snapshot)
    values = {"DEBIAN_TOOLS_SNAPSHOT": snapshot, "DEBIAN_TOOLS_SNAPSHOT_URL": url}
    for spec, lock, constant in LOCKS:
        _update(
            workspace / spec, lambda text: re.sub(re.escape(_SNAPSHOT_URL.format("")) + _SNAPSHOT.pattern, url, text)
        )
        if generate_lock.main(["--spec", spec, "--output", lock]) != 0:
            raise SystemExit("Debian lock generation failed for {}".format(spec))
        values[constant] = _sha256(workspace / lock)
    return values


def refresh(workspace: pathlib.Path, snapshot: str, python: tuple[str, str] | None = None) -> dict[str, str]:
    """Refreshes the snapshot in workspace and returns the provenance values it wrote."""
    provenance = workspace / PROVENANCE
    old_snapshot = read_provenance(provenance.read_text(encoding="utf-8"))["DEBIAN_TOOLS_SNAPSHOT"]
    values = _write_locks(workspace, snapshot)
    if python:
        values |= _download_python_pin(*python)
    _update(provenance, lambda text: rewrite_provenance(text, values))
    for path in _snapshot_files(workspace, old_snapshot):
        _update(path, lambda text: replace_snapshot(text, old_snapshot, snapshot))
    archive = {constant: _archive_sha256(workspace, target) for target, constant in ARCHIVES}
    _update(provenance, lambda text: rewrite_provenance(text, archive))
    return values | archive


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--snapshot", required=True, help="snapshot.debian.org timestamp, such as 20260912T080811Z")
    parser.add_argument("--python-release", help="python-build-standalone release of the static Python, a date")
    parser.add_argument("--python-version", help="CPython version in that release, such as 3.14.10")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
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
