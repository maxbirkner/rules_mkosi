"""Unit tests for Debian snapshot authentication and validation."""

import hashlib
import importlib.util
import lzma
import os
import pathlib
import types
import unittest
from unittest import mock

_HERE = pathlib.Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("debian_snapshot", _HERE.parent / "private/debian_snapshot.py")
assert _SPEC is not None and _SPEC.loader is not None
debian_snapshot = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(debian_snapshot)


class DebianSnapshotUnitTest(unittest.TestCase):
    def setUp(self):
        self.work = pathlib.Path(os.environ.get("TEST_TMPDIR", ".")) / ("debian-snapshot-%s" % os.getpid())
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

    def test_sqv_release_payload_may_omit_final_newline(self):
        self.assertTrue(debian_snapshot._authenticated_release_matches(b"Release payload", b"Release payload\n"))
        self.assertFalse(debian_snapshot._authenticated_release_matches(b"Release payload\nX", b"Release payload\n"))

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

    def test_package_metadata_rejects_duplicate_fields(self):
        index = self.work / "duplicate"
        index.write_bytes(b"Package: one\nPackage: two\n")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            debian_snapshot._read_package_metadata(((str(index), "amd64"),), {})

    def test_package_metadata_skips_continuation_lines_of_other_fields(self):
        index = self.work / "continuation"
        index.write_bytes(
            b"Package: demo\nVersion: 1\nArchitecture: amd64\n"
            b"Depends: libc6 (>= 2.36),\n zlib1g\n"
            b"Description: demo\n First line.\n .\n\tLast line.\n"
            b"Filename: pool/main/d/demo.deb\nSize: 3\nSHA256: abc\n"
            b" \n"
            b"Package: other\nVersion: 2\nArchitecture: amd64\n"
            b"Filename: pool/main/o/other.deb\nSize: 4\nSHA256: def\n"
        )
        expected = {
            ("demo", "1", "amd64"): ("pool/main/d/demo.deb", 3, "abc"),
            ("other", "2", "amd64"): ("pool/main/o/other.deb", 4, "def"),
        }
        self.assertEqual(expected, debian_snapshot._read_package_metadata(((str(index), "amd64"),), expected))

    def test_package_path_must_be_under_pool(self):
        self.assertEqual(
            "pool/main/a/a.deb",
            str(debian_snapshot._safe_package_path("pool/main/a/a.deb")),
        )
        with self.assertRaisesRegex(ValueError, "unsafe package path"):
            debian_snapshot._safe_package_path("../pool/a.deb")
        for unsafe in ("pool/./a.deb", "pool//a.deb"):
            with self.assertRaisesRegex(ValueError, "unsafe package path"):
                debian_snapshot._safe_package_path(unsafe)

    def test_identical_all_architecture_duplicates_are_accepted(self):
        first = self.work / "amd64"
        second = self.work / "all"
        paragraph = (
            b"Package: demo\nVersion: 1\nArchitecture: all\nFilename: pool/main/d/demo.deb\nSize: 3\nSHA256: abc\n\n"
        )
        first.write_bytes(paragraph)
        second.write_bytes(paragraph)
        expected = {("demo", "1", "all"): ("pool/main/d/demo.deb", 3, "abc")}
        self.assertEqual(
            expected,
            debian_snapshot._read_package_metadata(((str(first), "amd64"), (str(second), "all")), expected),
        )

    def test_conflicting_all_architecture_duplicates_are_rejected(self):
        first = self.work / "amd64"
        second = self.work / "all"
        first.write_text(
            "Package: demo\nVersion: 1\nArchitecture: all\nFilename: pool/main/d/demo.deb\nSize: 3\nSHA256: abc\n\n"
        )
        second.write_text(
            "Package: demo\nVersion: 1\nArchitecture: all\nFilename: pool/main/d/other.deb\nSize: 3\nSHA256: abc\n\n"
        )
        expected = {("demo", "1", "all"): ("pool/main/d/demo.deb", 3, "abc")}
        with self.assertRaisesRegex(ValueError, "conflicting"):
            debian_snapshot._read_package_metadata(((str(first), "amd64"), (str(second), "all")), expected)

    def _write_index(self, name, content):
        path = self.work / name
        with lzma.open(path, "wb") as output:
            output.write(content)
        return path

    def _package(self, name, component, content):
        package = self.work / ("%s.deb" % name)
        package.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        filename = "pool/%s/%s/%s_1_amd64.deb" % (component, name[0], name)
        paragraph = (
            "Package: %s\nVersion: 1\nArchitecture: amd64\n"
            "Filename: %s\nSize: %d\nSHA256: %s\n\n" % (name, filename, len(content), digest)
        ).encode()
        record = "%s|1|amd64|%s|%d|%s" % (name, filename, len(content), digest)
        return package, paragraph, record

    def _arguments(self, extra_components=()):
        package, paragraph, record = self._package("demo", "main", b"representative package")
        indexes = [
            ("main", "amd64", self._write_index("main-amd64.xz", paragraph)),
            ("main", "all", self._write_index("main-all.xz", b"")),
        ]
        packages = [(package, record + "|pkg_000.deb")]
        for index, component in enumerate(extra_components):
            firmware, firmware_paragraph, firmware_record = self._package(
                "firmware-%d" % index, component, b"firmware payload %d" % index
            )
            indexes.append((component, "amd64", self._write_index(component + "-amd64.xz", firmware_paragraph)))
            indexes.append((component, "all", self._write_index(component + "-all.xz", b"")))
            packages.append((firmware, firmware_record + "|pkg_%03d.deb" % (index + 1)))
        digests = {
            (component, architecture): hashlib.sha256(path.read_bytes()).hexdigest()
            for component, architecture, path in indexes
        }
        release = b"SHA256:\n" + b"".join(
            b" %s %d %s/binary-%s/Packages.xz\n"
            % (
                digests[(component, architecture)].encode(),
                path.stat().st_size,
                component.encode(),
                architecture.encode(),
            )
            for component, architecture, path in indexes
        )
        inrelease = self.work / "InRelease"
        release_path = self.work / "Release"
        release_gpg = self.work / "Release.gpg"
        inrelease.write_bytes(b"signed")
        release_path.write_bytes(release)
        release_gpg.write_bytes(b"signature")
        return types.SimpleNamespace(
            inrelease=str(inrelease),
            release=str(release_path),
            release_gpg=str(release_gpg),
            packages_xz=str(indexes[0][2]),
            packages_all_xz=str(indexes[1][2]),
            output=str(self.work / "out"),
            scratch=str(self.work / "scratch"),
            launcher="launcher",
            inrelease_sha256=hashlib.sha256(inrelease.read_bytes()).hexdigest(),
            release_sha256=hashlib.sha256(release).hexdigest(),
            release_gpg_sha256=hashlib.sha256(release_gpg.read_bytes()).hexdigest(),
            packages_xz_sha256=digests[("main", "amd64")],
            packages_all_xz_sha256=digests[("main", "all")],
            packages_path="dists/trixie/main/binary-amd64/Packages.xz",
            packages_all_path="dists/trixie/main/binary-all/Packages.xz",
            codename="trixie",
            component_indexes=[
                "%s|%s|dists/trixie/%s/binary-%s/Packages.xz|%s"
                % (component, architecture, component, architecture, digests[(component, architecture)])
                for component, architecture, _ in indexes[2:]
            ],
            component_index_files=[str(path) for _, _, path in indexes[2:]],
            package_records=[record for _, record in packages],
            package_names=[record.rsplit("|", 1)[1] for _, record in packages],
            packages=[str(package) for package, _ in packages],
        )

    def _stage(self, args):
        def verify(*_):
            verified = pathlib.Path(args.output) / "verified-release"
            verified.parent.mkdir(parents=True, exist_ok=True)
            verified.write_bytes(pathlib.Path(args.release).read_bytes())

        with mock.patch.object(debian_snapshot, "_verify_signature", side_effect=verify):
            debian_snapshot.stage(args)
        return pathlib.Path(args.output)

    def test_stages_exact_layout_with_deterministic_metadata(self):
        repository = self._stage(self._arguments())
        self.assertEqual(
            b"representative package",
            (repository / "pool/main/d/demo_1_amd64.deb").read_bytes(),
        )
        self.assertEqual(0, (repository / "dists/trixie/Release").stat().st_mtime_ns)

    def test_stages_every_locked_component(self):
        repository = self._stage(self._arguments(("non-free-firmware", "contrib")))
        for component in ("main", "non-free-firmware", "contrib"):
            for architecture in ("amd64", "all"):
                index = repository / "dists/trixie" / component / ("binary-" + architecture) / "Packages"
                self.assertTrue(index.is_file(), index)
        self.assertEqual(
            b"firmware payload 0",
            (repository / "pool/non-free-firmware/f/firmware-0_1_amd64.deb").read_bytes(),
        )
        self.assertEqual(
            b"firmware payload 1",
            (repository / "pool/contrib/f/firmware-1_1_amd64.deb").read_bytes(),
        )

    def test_component_index_must_be_authenticated_by_release(self):
        args = self._arguments(("non-free-firmware",))
        release = pathlib.Path(args.release).read_bytes()
        release = b"\n".join(line for line in release.split(b"\n") if b"non-free-firmware/binary-amd64" not in line)
        pathlib.Path(args.release).write_bytes(release)
        args.release_sha256 = hashlib.sha256(release).hexdigest()
        with self.assertRaisesRegex(ValueError, "exactly one"):
            self._stage(args)

    def test_component_index_digest_is_verified(self):
        args = self._arguments(("non-free-firmware",))
        args.component_indexes[0] = args.component_indexes[0][:-64] + "0" * 64
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self._stage(args)

    def test_component_indexes_must_be_complete_and_placed(self):
        args = self._arguments(("non-free-firmware",))
        del args.component_indexes[1]
        del args.component_index_files[1]
        with self.assertRaisesRegex(ValueError, "binary-amd64 and binary-all"):
            self._stage(args)
        args = self._arguments(("non-free-firmware",))
        args.component_indexes[0] = args.component_indexes[0].replace("dists/trixie", "dists/bookworm")
        with self.assertRaisesRegex(ValueError, "must be staged at"):
            self._stage(args)

    def test_codename_selects_the_staged_suite(self):
        args = self._arguments()
        args.codename = "forky"
        args.packages_path = args.packages_path.replace("trixie", "forky")
        args.packages_all_path = args.packages_all_path.replace("trixie", "forky")
        repository = self._stage(args)
        self.assertTrue((repository / "dists/forky/InRelease").is_file())
        self.assertTrue((repository / "dists/forky/main/binary-amd64/Packages").is_file())

    def test_package_must_be_listed_by_a_locked_component(self):
        args = self._arguments(("non-free-firmware",))
        _, _, record = self._package("unlisted", "non-free-firmware", b"unlisted")
        args.package_records.append(record + "|pkg_009.deb")
        args.package_names.append("pkg_009.deb")
        args.packages.append(str(self.work / "unlisted.deb"))
        with self.assertRaisesRegex(ValueError, "do not match Packages metadata"):
            self._stage(args)


if __name__ == "__main__":
    unittest.main()
