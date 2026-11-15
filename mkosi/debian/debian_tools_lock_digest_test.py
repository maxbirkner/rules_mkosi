import hashlib
import json
import os
import pathlib
import re
import unittest

_DIRECTORY = pathlib.Path(__file__).resolve().parent
# Each built-in lock, the provenance.bzl constant that pins its digest, and its package repository.
_LOCKS = (
    ("debian13.lock.json", "DEBIAN_TOOLS_LOCK_SHA256", "mkosi_debian_package_inputs"),
    ("debian13.arm64.lock.json", "DEBIAN_TOOLS_ARM64_LOCK_SHA256", "mkosi_debian_package_inputs_arm64"),
)


def _canonical_repository(apparent: str) -> str:
    runfiles = pathlib.Path(os.environ["RUNFILES_DIR"])
    return next(
        fields[2]
        for fields in (
            line.split(",", 2) for line in (runfiles / "_repo_mapping").read_text(encoding="utf-8").splitlines()
        )
        if len(fields) == 3 and fields[1] == apparent
    )


class DebianToolsLockDigestTest(unittest.TestCase):
    def test_checked_in_lock_digest(self) -> None:
        provenance = (_DIRECTORY / "provenance.bzl").read_text(encoding="utf-8")
        for lock, constant, _ in _LOCKS:
            with self.subTest(lock=lock):
                match = re.search(r'%s = "([0-9a-f]{64})"' % constant, provenance)
                if match is None:
                    self.fail("provenance.bzl does not set %s" % constant)
                self.assertEqual(match.group(1), hashlib.sha256((_DIRECTORY / lock).read_bytes()).hexdigest())

    def test_package_manifest_matches_lock_exactly_once(self) -> None:
        runfiles = pathlib.Path(os.environ["RUNFILES_DIR"])
        for lock_name, _, repository in _LOCKS:
            with self.subTest(lock=lock_name):
                lock = json.loads((_DIRECTORY / lock_name).read_text(encoding="utf-8"))
                manifest = runfiles / _canonical_repository(repository) / "package_manifest.txt"
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

    def test_arm64_lock_resolves_the_amd64_package_set_at_the_same_snapshot(self) -> None:
        amd64 = json.loads((_DIRECTORY / "debian13.lock.json").read_text(encoding="utf-8"))
        arm64 = json.loads((_DIRECTORY / "debian13.arm64.lock.json").read_text(encoding="utf-8"))
        self.assertEqual("arm64", arm64["repository"]["architecture"])
        for field in ("snapshot", "snapshot_url", "codename", "components", "release"):
            self.assertEqual(amd64["repository"][field], arm64["repository"][field], field)
        self.assertEqual({"all", "arm64"}, {package["arch"] for package in arm64["packages"]})


if __name__ == "__main__":
    unittest.main()
