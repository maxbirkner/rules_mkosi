"""Tests for the command that refreshes the built-in Debian tools snapshot."""

import hashlib
import os
import pathlib
import stat
import sys
import unittest
import urllib.parse
from unittest import mock

# The runfiles path, not the source tree that it links to, so that bytecode caches stay out of the source tree.
sys.path.insert(0, str(pathlib.Path(__file__).parent))

import refresh_debian_tools

_HERE = pathlib.Path(__file__).resolve().parent
_OLD, _NEW = "20250814T000000Z", "20260912T080811Z"
_PROVENANCE = """DEBIAN_TOOLS_SNAPSHOT = "{0}"
DEBIAN_TOOLS_SNAPSHOT_URL = "https://snapshot.debian.org/archive/debian/{0}"
DEBIAN_TOOLS_LOCK_SHA256 = "old-lock"
DEBIAN_TOOLS_ARCHIVE_SHA256 = "old-archive"
DEBIAN_TOOLS_REQUIRED_COMPONENTS = ["apt-get"]
"""
# Answers the build, cquery and info commands that the refresh runs, from the fake workspace.
_FAKE_BAZEL = """#!/bin/sh
case "$1" in
  cquery) echo bazel-out/flat.tar ;;
  info) pwd ;;
esac
"""


def _snapshot_url(snapshot):
    return "https://snapshot.debian.org/archive/debian/" + snapshot


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class RefreshTest(unittest.TestCase):
    def setUp(self):
        self.workspace = pathlib.Path(os.environ["TEST_TMPDIR"]) / self._testMethodName
        _write(self.workspace / refresh_debian_tools.PROVENANCE, _PROVENANCE.format(_OLD))
        _write(self.workspace / refresh_debian_tools.SPEC, '"url": "%s"' % _snapshot_url(_OLD))
        _write(self.workspace / "README.md", "Snapshot=%s, epoch 1755129600\n" % _OLD)
        _write(self.workspace / "e2e/smoke/testdata/minimal.conf", "Snapshot=%s\n" % _OLD)
        _write(self.workspace / "bazel-out/flat.tar", "archive")
        bazel = self.workspace / "bazel"
        _write(bazel, _FAKE_BAZEL)
        bazel.chmod(bazel.stat().st_mode | stat.S_IXUSR)
        self.enterContext(mock.patch.dict(os.environ, {"BAZEL": str(bazel)}))
        self.enterContext(mock.patch.object(refresh_debian_tools.generate_lock, "main", side_effect=self._lock))

    def _lock(self, argv):
        self.assertEqual(["--spec", refresh_debian_tools.SPEC, "--output", refresh_debian_tools.LOCK], argv)
        _write(self.workspace / refresh_debian_tools.LOCK, "lock")
        return 0

    def _text(self, name):
        return (self.workspace / name).read_text()

    def test_refresh_moves_provenance_and_test_configurations_to_the_snapshot(self):
        values = refresh_debian_tools.refresh(self.workspace, _NEW)
        provenance = refresh_debian_tools.read_provenance(self._text(refresh_debian_tools.PROVENANCE))
        self.assertEqual(
            {
                "DEBIAN_TOOLS_SNAPSHOT": _NEW,
                "DEBIAN_TOOLS_SNAPSHOT_URL": _snapshot_url(_NEW),
                "DEBIAN_TOOLS_LOCK_SHA256": hashlib.sha256(b"lock").hexdigest(),
                "DEBIAN_TOOLS_ARCHIVE_SHA256": hashlib.sha256(b"archive").hexdigest(),
            },
            values,
        )
        self.assertEqual(values, {name: provenance[name] for name in values})
        self.assertIn('DEBIAN_TOOLS_REQUIRED_COMPONENTS = ["apt-get"]', self._text(refresh_debian_tools.PROVENANCE))
        self.assertEqual('"url": "%s"' % _snapshot_url(_NEW), self._text(refresh_debian_tools.SPEC))
        self.assertEqual("Snapshot=%s, epoch 1789200491\n" % _NEW, self._text("README.md"))
        self.assertEqual("Snapshot=%s\n" % _NEW, self._text("e2e/smoke/testdata/minimal.conf"))

    def test_failed_lock_generation_leaves_provenance_unchanged(self):
        refresh_debian_tools.generate_lock.main.side_effect = None
        refresh_debian_tools.generate_lock.main.return_value = 1
        with self.assertRaisesRegex(SystemExit, "Debian lock generation failed"):
            refresh_debian_tools.refresh(self.workspace, _NEW)
        self.assertEqual(_PROVENANCE.format(_OLD), self._text(refresh_debian_tools.PROVENANCE))


class PythonPinTest(unittest.TestCase):
    def setUp(self):
        provenance = refresh_debian_tools.read_provenance((_HERE / "provenance.bzl").read_text())
        self.pin = {name: value for name, value in provenance.items() if name.startswith("DEBIAN_TOOLS_PYTHON_")}
        url = self.pin["DEBIAN_TOOLS_PYTHON_URL"]
        self.release = url.split("/")[-2]
        asset = urllib.parse.unquote(url.split("/")[-1])
        self.sums = "{}  {}\n{}  {}\n".format(
            "0" * 64, asset.replace("+static", ""), provenance["DEBIAN_TOOLS_PYTHON_SHA256"], asset
        )

    def test_pin_reproduces_the_checked_in_static_python(self):
        version = self.pin["DEBIAN_TOOLS_PYTHON_VERSION"]
        self.assertEqual(self.pin, refresh_debian_tools.python_pin(self.release, version, self.sums))

    def test_missing_asset_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "does not list cpython-3.0.0"):
            refresh_debian_tools.python_pin(self.release, "3.0.0", self.sums)


class ProvenanceTest(unittest.TestCase):
    def test_unknown_constant_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "DEBIAN_TOOLS_MISSING"):
            refresh_debian_tools.rewrite_provenance(_PROVENANCE.format(_OLD), {"DEBIAN_TOOLS_MISSING": "x"})

    def test_snapshot_epoch_is_the_snapshot_time(self):
        self.assertEqual(1789200491, refresh_debian_tools.snapshot_epoch(_NEW))


if __name__ == "__main__":
    unittest.main()
