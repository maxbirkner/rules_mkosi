"""Unit tests for Debian snapshot authentication and validation."""

import importlib.util
import hashlib
import lzma
import os
import pathlib
import types
import unittest
from unittest import mock


_HERE = pathlib.Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location(
    "debian_snapshot", _HERE.parent / "private/debian_snapshot.py"
)
debian_snapshot = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(debian_snapshot)


class DebianSnapshotUnitTest(unittest.TestCase):
    def setUp(self):
        self.work = pathlib.Path(os.environ.get("TEST_TMPDIR", ".")) / (
            "debian-snapshot-%s" % os.getpid()
        )
        self.work.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        for path in sorted(self.work.rglob("*"), reverse=True):
            if path.is_dir():
                path.rmdir()
            else:
                path.unlink()
        self.work.rmdir()

    def test_changed_content_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            debian_snapshot._verify_digest(__file__, "0" * 64, "InRelease")

    def test_downloaded_package_size_is_rejected(self):
        package = self.work / "package.deb"
        package.write_bytes(b"package")
        digest = hashlib.sha256(package.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "size mismatch"):
            debian_snapshot._verify_package(package, digest, package.stat().st_size + 1, "package")

    def test_metadata_normalization_ignores_umask(self):
        for value in (0o022, 0o077):
            root = self.work / ("mode-%03o" % value)
            previous = os.umask(value)
            try:
                (root / "nested").mkdir(parents=True)
                (root / "nested/file").write_bytes(b"x")
            finally:
                os.umask(previous)
            debian_snapshot._set_deterministic_metadata(root)
            self.assertEqual(0o755, root.stat().st_mode & 0o777)
            self.assertEqual(0o755, (root / "nested").stat().st_mode & 0o777)
            self.assertEqual(0o644, (root / "nested/file").stat().st_mode & 0o777)
            self.assertEqual(0, (root / "nested/file").stat().st_mtime_ns)

    def test_release_must_list_locked_packages_index(self):
        with self.assertRaisesRegex(ValueError, "absent|exactly one"):
            debian_snapshot._release_hash(
                b"SHA256:\n " + b"d" * 64 + b" 1 main/binary-amd64/Other.xz\n",
                "main/binary-amd64/Packages.xz",
                1,
                "d" * 64,
            )

    def test_release_uses_named_sha256_section(self):
        release = (
            b"MD5Sum:\n"
            b" deadbeef 1 main/binary-amd64/Packages.xz\n"
            b"SHA256:\n"
            b" " + b"a" * 64 + b" 1 main/binary-amd64/Packages.xz\n"
        )
        debian_snapshot._release_hash(
            release,
            "dists/trixie/main/binary-amd64/Packages.xz",
            1,
            "a" * 64,
        )

    def test_release_rejects_duplicate_sha256_path(self):
        release = (
            b"SHA256:\n"
            b" " + b"a" * 64 + b" 1 main/binary-amd64/Packages.xz\n"
            b" " + b"a" * 64 + b" 1 main/binary-amd64/Packages.xz\n"
        )
        with self.assertRaisesRegex(ValueError, "duplicate"):
            debian_snapshot._release_hash(
                release,
                "dists/trixie/main/binary-amd64/Packages.xz",
                1,
                "a" * 64,
            )

    def test_invalid_signature_fails_explicitly(self):
        with mock.patch.object(
            debian_snapshot.subprocess,
            "run",
            return_value=mock.Mock(returncode=1),
        ):
            with self.assertRaisesRegex(ValueError, "signature verification failed"):
                debian_snapshot._verify_signature(
                    "/declared/launcher",
                    "/declared/InRelease",
                    "/declared/Release",
                    "/declared/Release.gpg",
                    "/declared/output",
                    "/declared/scratch",
                )

    def test_package_metadata_rejects_duplicate_fields(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            debian_snapshot._paragraphs(b"Package: one\nPackage: two\n")

    def test_package_path_must_be_under_pool(self):
        self.assertEqual(
            "pool/main/a/a.deb",
            str(debian_snapshot._safe_package_path("pool/main/a/a.deb")),
        )
        with self.assertRaisesRegex(ValueError, "unsafe package path"):
            debian_snapshot._safe_package_path("../pool/a.deb")

    def test_identical_all_architecture_duplicates_are_accepted(self):
        first = self.work / "amd64"
        second = self.work / "all"
        paragraph = (
            b"Package: demo\nVersion: 1\nArchitecture: all\n"
            b"Filename: pool/main/d/demo.deb\nSize: 3\n"
            b"SHA256: abc\n\n"
        )
        first.write_bytes(paragraph)
        second.write_bytes(paragraph)
        expected = {("demo", "1", "all"): ("pool/main/d/demo.deb", 3, "abc")}
        self.assertEqual(
            expected,
            debian_snapshot._read_package_metadata(
                ((str(first), "amd64"), (str(second), "all")), expected
            ),
        )

    def test_conflicting_all_architecture_duplicates_are_rejected(self):
        first = self.work / "amd64"
        second = self.work / "all"
        first.write_text(
            "Package: demo\nVersion: 1\nArchitecture: all\n"
            "Filename: pool/main/d/demo.deb\nSize: 3\nSHA256: abc\n\n"
        )
        second.write_text(
            "Package: demo\nVersion: 1\nArchitecture: all\n"
            "Filename: pool/main/d/other.deb\nSize: 3\nSHA256: abc\n\n"
        )
        expected = {("demo", "1", "all"): ("pool/main/d/demo.deb", 3, "abc")}
        with self.assertRaisesRegex(ValueError, "conflicting"):
            debian_snapshot._read_package_metadata(
                ((str(first), "amd64"), (str(second), "all")), expected
            )

    def test_stages_exact_layout_with_deterministic_metadata(self):
        package = self.work / "pkg.deb"
        package.write_bytes(b"representative package")
        package_digest = hashlib.sha256(package.read_bytes()).hexdigest()
        package_index = (
            "Package: demo\nVersion: 1\nArchitecture: amd64\n"
            "Filename: pool/main/d/demo_1_amd64.deb\n"
            "Size: %d\n"
            "SHA256: %s\n\n" % (package.stat().st_size, package_digest)
        ).encode()
        package_all = b""
        packages_xz = self.work / "Packages.xz"
        packages_all_xz = self.work / "Packages-all.xz"
        with lzma.open(packages_xz, "wb") as output:
            output.write(package_index)
        with lzma.open(packages_all_xz, "wb") as output:
            output.write(package_all)
        packages_digest = hashlib.sha256(packages_xz.read_bytes()).hexdigest()
        packages_all_digest = hashlib.sha256(packages_all_xz.read_bytes()).hexdigest()
        release = (
            "SHA256:\n %s %d main/binary-amd64/Packages.xz\n"
            " %s %d main/binary-all/Packages.xz\n"
            % (
                packages_digest,
                packages_xz.stat().st_size,
                packages_all_digest,
                packages_all_xz.stat().st_size,
            )
        ).encode()
        inrelease = self.work / "InRelease"
        release_path = self.work / "Release"
        release_gpg = self.work / "Release.gpg"
        inrelease.write_bytes(b"signed")
        release_path.write_bytes(release)
        release_gpg.write_bytes(b"signature")
        output = self.work / "out"
        scratch = self.work / "scratch"
        args = types.SimpleNamespace(
            inrelease=str(inrelease),
            release=str(release_path),
            release_gpg=str(release_gpg),
            packages_xz=str(packages_xz),
            packages_all_xz=str(packages_all_xz),
            output=str(output),
            scratch=str(scratch),
            launcher="launcher",
            inrelease_sha256=hashlib.sha256(inrelease.read_bytes()).hexdigest(),
            release_sha256=hashlib.sha256(release).hexdigest(),
            release_gpg_sha256=hashlib.sha256(release_gpg.read_bytes()).hexdigest(),
            packages_xz_sha256=packages_digest,
            packages_all_xz_sha256=packages_all_digest,
            packages_path="dists/trixie/main/binary-amd64/Packages.xz",
            packages_all_path="dists/trixie/main/binary-all/Packages.xz",
            package_records=[
                "demo|1|amd64|pool/main/d/demo_1_amd64.deb|%d|%s|pkg_000.deb"
                % (package.stat().st_size, package_digest)
            ],
            package_names=["pkg_000.deb"],
            packages=[str(package)],
        )

        def verify(*_):
            verified = output / "verified-release"
            verified.parent.mkdir(parents=True)
            verified.write_bytes(release)

        with mock.patch.object(debian_snapshot, "_verify_signature", side_effect=verify):
            debian_snapshot.stage(args)
        repository = output
        self.assertEqual(
            b"representative package",
            (repository / "pool/main/d/demo_1_amd64.deb").read_bytes(),
        )
        self.assertEqual(0, (repository / "dists/trixie/Release").stat().st_mtime_ns)


if __name__ == "__main__":
    unittest.main()
