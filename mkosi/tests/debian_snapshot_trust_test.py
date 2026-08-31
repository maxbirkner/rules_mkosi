"""Exercise the pinned sqv/keyring against mutated signed metadata."""

import pathlib
import os
import shutil
import subprocess
import sys
import unittest


class DebianSnapshotTrustTest(unittest.TestCase):
    def setUp(self):
        self.inrelease = pathlib.Path(sys.argv[1])
        self.release = pathlib.Path(sys.argv[2])
        self.release_gpg = pathlib.Path(sys.argv[3])
        self.launcher = pathlib.Path(sys.argv[4])
        self.work = pathlib.Path(os.environ["TEST_TMPDIR"]) / self._testMethodName
        self.work.mkdir()

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def _run(self, arguments):
        return subprocess.run(
            [str(self.launcher)] + arguments,
            env={"PATH": "", "HOME": "/root", "TEST_TMPDIR": str(self.work / "scratch")},
        )

    def _cleartext(self, source):
        output = self.work / "output"
        output.mkdir(exist_ok=True)
        return self._run(
            [
                "--ro-bind",
                "%s:/inputs/InRelease" % source,
                "--rw-bind",
                "%s:/outputs/result" % output,
                "/usr/bin/sqv",
                "--keyring=/usr/share/keyrings/debian-archive-keyring.gpg",
                "--output=/outputs/result/verified",
                "--cleartext",
                "/inputs/InRelease",
            ]
        )

    def _detached(self, signature):
        return self._run(
            [
                "--ro-bind",
                "%s:/inputs/Release" % self.release,
                "--ro-bind",
                "%s:/inputs/Release.gpg" % signature,
                "/usr/bin/sqv",
                "--keyring=/usr/share/keyrings/debian-archive-keyring.gpg",
                "--signature-file=/inputs/Release.gpg",
                "/inputs/Release",
            ]
        )

    def test_mutated_inrelease_is_rejected(self):
        mutated = self.work / "InRelease"
        data = self.inrelease.read_bytes()
        mutated.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
        self.assertEqual(0, self._cleartext(self.inrelease).returncode)
        result = self._cleartext(mutated)
        self.assertNotEqual(0, result.returncode)

    def test_mutated_detached_signature_is_rejected(self):
        mutated = self.work / "Release.gpg"
        data = self.release_gpg.read_bytes()
        mutated.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
        self.assertEqual(0, self._detached(self.release_gpg).returncode)
        result = self._detached(mutated)
        self.assertNotEqual(0, result.returncode)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
