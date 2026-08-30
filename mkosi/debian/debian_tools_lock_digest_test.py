import hashlib
import json
import os
import pathlib
import re
import unittest


class DebianToolsLockDigestTest(unittest.TestCase):
    def test_checked_in_lock_digest(self):
        directory = pathlib.Path(__file__).resolve().parent
        lock = directory / "debian13.lock.json"
        provenance = (directory / "provenance.bzl").read_text(encoding="utf-8")
        expected = re.search(r'DEBIAN_TOOLS_LOCK_SHA256 = "([0-9a-f]{64})"', provenance).group(1)
        actual = hashlib.sha256(lock.read_bytes()).hexdigest()
        self.assertEqual(expected, actual)

    def test_package_manifest_matches_lock_exactly_once(self):
        directory = pathlib.Path(__file__).resolve().parent
        lock = json.loads((directory / "debian13.lock.json").read_text(encoding="utf-8"))
        runfiles = pathlib.Path(os.environ["RUNFILES_DIR"])
        repository = next(
            fields[2]
            for fields in (
                line.split(",", 2)
                for line in (runfiles / "_repo_mapping").read_text(encoding="utf-8").splitlines()
            )
            if len(fields) == 3 and fields[1] == "mkosi_debian_package_inputs"
        )
        manifest = runfiles / repository / "package_manifest.txt"
        entries = [line.rstrip("\n").split("|", 2) for line in manifest.read_text().splitlines()]
        packages = sorted(lock["packages"], key=lambda package: package["key"])
        self.assertEqual(len(packages), len(entries))
        self.assertEqual(
            [(entry[0], entry[1], entry[2]) for entry in entries],
            [
                ("pkg_%03d.deb" % index, package["sha256"], package["key"])
                for index, package in enumerate(packages)
            ],
        )


if __name__ == "__main__":
    unittest.main()
