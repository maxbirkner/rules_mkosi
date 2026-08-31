"""Exercise the pinned sqv/keyring against mutated signed metadata."""

import pathlib
import os
import shutil
import subprocess
import sys
import unittest
import hashlib
import importlib.util


class DebianSnapshotTrustTest(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(__file__).resolve().parent
        self.inrelease = pathlib.Path(sys.argv[1]).resolve()
        self.release = pathlib.Path(sys.argv[2]).resolve()
        self.release_gpg = pathlib.Path(sys.argv[3]).resolve()
        self.launcher = pathlib.Path(sys.argv[4]).resolve()
        runfiles = os.environ.get("RUNFILES_DIR")
        mapping = pathlib.Path(runfiles or "") / "_repo_mapping"
        if runfiles and mapping.is_file():
            for line in mapping.read_text(encoding="utf-8").splitlines():
                fields = line.split(",", 2)
                if len(fields) == 3 and fields[1] == "mkosi_debian_tools":
                    candidate = pathlib.Path(runfiles) / fields[2] / "launcher"
                    if candidate.is_file():
                        self.launcher = candidate
                    break
        self.packages = pathlib.Path(sys.argv[5]).resolve()
        self.packages_all = pathlib.Path(sys.argv[6]).resolve()
        self.invocation = 0
        spec = importlib.util.spec_from_file_location(
            "debian_snapshot", self.root.parent / "private/debian_snapshot.py"
        )
        self.snapshot = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.snapshot)
        self.work = pathlib.Path(os.environ["TEST_TMPDIR"]) / self._testMethodName
        self.work.mkdir()

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def _run(self, arguments):
        self.invocation += 1
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": "",
                "HOME": "/root",
                "TEST_TMPDIR": str(self.work / ("scratch-%d" % self.invocation)),
            }
        )
        return subprocess.run(
            [str(self.launcher)] + arguments,
            env=environment,
            capture_output=True,
            text=True,
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
        marker = b"Suite: stable"
        self.assertIn(marker, data)
        mutated.write_bytes(data.replace(marker, b"Suite: stablx", 1))
        baseline = self._cleartext(self.inrelease)
        self.assertEqual(0, baseline.returncode, baseline.stderr)
        result = self._cleartext(mutated)
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn("scratch", result.stderr.lower())

    def test_mutated_detached_signature_is_rejected(self):
        mutated = self.work / "Release.gpg"
        data = self.release_gpg.read_bytes()
        header_end = data.index(b"\n", data.index(b"BEGIN PGP SIGNATURE")) + 1
        while data[header_end] in b"\r\n":
            header_end += 1
        replacement = {ord("A"): ord("B"), ord("B"): ord("C")}.get(
            data[header_end], ord("A")
        )
        mutated.write_bytes(data[:header_end] + bytes([replacement]) + data[header_end + 1 :])
        baseline = self._detached(self.release_gpg)
        self.assertEqual(0, baseline.returncode, baseline.stderr)
        result = self._detached(mutated)
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn("scratch", result.stderr.lower())

    def test_mutated_packages_index_is_rejected_by_signed_release(self):
        mutated = self.work / "Packages.xz"
        data = self.packages.read_bytes()
        mutated.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
        output = self.work / "stage-output"
        output.mkdir()
        scratch = self.work / "stage-scratch"
        args = type("Args", (), {
            "inrelease": str(self.inrelease),
            "release": str(self.release),
            "release_gpg": str(self.release_gpg),
            "packages_xz": str(mutated),
            "packages_all_xz": str(self.packages_all),
            "output": str(output),
            "scratch": str(scratch),
            "launcher": str(self.launcher),
            "inrelease_sha256": hashlib.sha256(self.inrelease.read_bytes()).hexdigest(),
            "release_sha256": hashlib.sha256(self.release.read_bytes()).hexdigest(),
            "release_gpg_sha256": hashlib.sha256(self.release_gpg.read_bytes()).hexdigest(),
            "packages_xz_sha256": hashlib.sha256(data[:-1] + bytes([data[-1] ^ 1])).hexdigest(),
            "packages_all_xz_sha256": hashlib.sha256(self.packages_all.read_bytes()).hexdigest(),
            "packages_path": "dists/trixie/main/binary-amd64/Packages.xz",
            "packages_all_path": "dists/trixie/main/binary-all/Packages.xz",
            "package_records": [],
            "package_names": [],
            "packages": [],
        })()
        with self.assertRaisesRegex(ValueError, "Release metadata"):
            self.snapshot.stage(args)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
