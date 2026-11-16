"""Unit tests for the validation and indexing of extra_packages."""

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import pathlib
import shutil
import types
import unittest
from collections.abc import Mapping, Sequence

_HERE = pathlib.Path(__file__).resolve().parent


def _load(name: str, path: pathlib.Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


deb_fixture = _load("deb_fixture", _HERE / "deb_fixture.py")
extra_packages = _load("extra_packages", _HERE.parent / "private/extra_packages.py")


def _control(name: str, version: str = "1.0", architecture: str = "all", **fields: str) -> list[tuple[str, str]]:
    return [
        ("Package", name),
        ("Version", version),
        ("Architecture", architecture),
        *fields.items(),
        ("Description", "test package\n second line"),
    ]


class ExtraPackagesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.work = pathlib.Path(os.environ.get("TEST_TMPDIR", ".")) / self._testMethodName
        shutil.rmtree(self.work, ignore_errors=True)
        self.work.mkdir(parents=True)

    def _write(self, filename: str, content: bytes) -> pathlib.Path:
        path = self.work / filename
        path.write_bytes(content)
        return path

    def _deb(
        self,
        filename: str,
        control: Sequence[tuple[str, str]],
        compression: str = "xz",
        files: Mapping[str, str] | None = None,
    ) -> pathlib.Path:
        content = deb_fixture.build_deb(control, files or {"/usr/share/test/file": "content\n"}, None, compression)
        return self._write(filename, content)

    def _assert_rejected(self, paths: Sequence[pathlib.Path], message: str, architecture: str = "amd64") -> None:
        with self.assertRaisesRegex(extra_packages.ExtraPackageError, message):
            extra_packages.read_packages(paths, architecture)

    def test_every_control_archive_compression_is_read(self) -> None:
        for compression in ("none", "gz", "xz", "zst"):
            with self.subTest(compression=compression):
                path = self._deb(compression + ".deb", _control("pkg-" + compression), compression)
                package = extra_packages.read_package(path, "amd64")
                self.assertEqual(
                    ("pkg-" + compression, "1.0", "all"), (package.name, package.version, package.architecture)
                )

    def test_index_entry_extends_the_control_file_with_the_repository_file(self) -> None:
        path = self._deb("downloaded", _control("vendor-kernel", "2:6.12-1", "amd64", Depends="kmod"))
        package = extra_packages.read_package(path, "amd64")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual("vendor-kernel_6.12-1_amd64.deb", package.filename)
        self.assertEqual(
            "Package: vendor-kernel\nVersion: 2:6.12-1\nArchitecture: amd64\nDepends: kmod\n"
            "Description: test package\n second line\n"
            "Filename: ./vendor-kernel_6.12-1_amd64.deb\nSize: {}\nSHA256: {}\n".format(path.stat().st_size, digest),
            package.index_entry(),
        )

    def test_index_and_manifest_list_the_packages_by_name(self) -> None:
        paths = [self._deb("b.deb", _control("zeta", "1")), self._deb("a.deb", _control("alpha", "3", "amd64"))]
        packages = extra_packages.read_packages(paths, "amd64")
        repository = self.work / "repository"
        extra_packages.write_index(packages, repository)
        index = (repository / "Packages").read_bytes()
        # The build places the .deb files next to the index, so the index holds no copy of them.
        self.assertEqual(["Packages", "Release"], sorted(entry.name for entry in repository.iterdir()))
        self.assertLess(index.index(b"Package: alpha"), index.index(b"Package: zeta"))
        self.assertIn(b"\n\nPackage: zeta\n", index)
        self.assertEqual(
            "Origin: rules_mkosi\nLabel: rules-mkosi-extra-packages\nDate: Thu, 01 Jan 1970 00:00:00 UTC\nSHA256:\n"
            " {} {} Packages\n".format(hashlib.sha256(index).hexdigest(), len(index)),
            (repository / "Release").read_text(),
        )
        manifest = extra_packages.manifest(packages, "amd64")
        self.assertEqual("mkosi-extra-packages-v1", manifest["format_version"])
        self.assertEqual(
            {
                "architecture": "amd64",
                "filename": "alpha_3_amd64.deb",
                "name": "alpha",
                "sha256": hashlib.sha256(paths[1].read_bytes()).hexdigest(),
                "size": paths[1].stat().st_size,
                "version": "3",
            },
            manifest["packages"][0],
        )

    def test_architecture_must_match_the_snapshot_or_be_all(self) -> None:
        arm64 = self._deb("arm64.deb", _control("board-firmware", architecture="arm64"))
        self._assert_rejected([arm64], "built for architecture arm64, but the image's Debian snapshot is amd64")
        self.assertEqual("arm64", extra_packages.read_package(arm64, "arm64").architecture)

    def test_duplicate_package_names_are_rejected(self) -> None:
        first = self._deb("first.deb", _control("firmware", "1"))
        second = self._deb("second.deb", _control("firmware", "2"))
        self._assert_rejected([first, second], "contain package firmware twice: .*first.deb and .*second.deb")

    def test_files_that_are_not_debian_binary_packages_are_rejected(self) -> None:
        valid = self._deb("valid.deb", _control("valid")).read_bytes()
        cases = {
            "text": (b"not a package\n", "not an ar archive"),
            "archive": (
                b"!<arch>\n" + deb_fixture._ar_member("data.tar", b""),
                "debian-binary is not its first member",
            ),
            "format": (valid.replace(b"2.0\n", b"3.0\n", 1), "unsupported Debian binary package format"),
            "truncated": (valid[:80], "truncated"),
            "compression": (valid.replace(b"control.tar.xz", b"control.tar.bz", 1), "unsupported control archive"),
            "corrupt": (valid.replace(b"\xfd7zXZ", b"\x00" * 5, 1), "unreadable control archive"),
        }
        for name, (content, message) in cases.items():
            with self.subTest(name=name):
                self._assert_rejected([self._write(name + ".deb", content)], message)
        self._assert_rejected([self.work], "it is not a file")

    def test_invalid_control_files_are_rejected(self) -> None:
        cases = {
            "version": (_control("pkg", "1.0/../x"), "invalid version"),
            "name": (_control("Pkg"), "invalid package name"),
            "missing": ([("Package", "pkg"), ("Architecture", "all")], "has no Version field"),
            "index": (_control("pkg", SHA256="0" * 64), "sets Packages index fields in its control file: SHA256"),
        }
        for name, (control, message) in cases.items():
            with self.subTest(name=name):
                self._assert_rejected([self._deb(name + ".deb", control)], message)

    def test_main_reports_a_classified_failure(self) -> None:
        output = io.StringIO()
        arguments = ["--architecture", "amd64", "--index", "index", "--manifest", "manifest.json"]
        with contextlib.redirect_stderr(output), self.assertRaises(SystemExit):
            extra_packages.main([*arguments, os.fspath(self._write("text.deb", b"text"))])
        self.assertIn("EXTRA_PACKAGE_FAILURE: ", output.getvalue())

    def test_main_writes_the_index_and_the_manifest(self) -> None:
        path = self._deb("downloaded", _control("pkg"))
        index, manifest = self.work / "index", self.work / "manifest.json"
        arguments = ["--architecture", "amd64", "--index", os.fspath(index), "--manifest", os.fspath(manifest)]
        extra_packages.main([*arguments, os.fspath(path)])
        self.assertIn(b"Filename: ./pkg_1.0_all.deb\n", (index / "Packages").read_bytes())
        self.assertEqual(["Packages", "Release"], sorted(entry.name for entry in index.iterdir()))
        self.assertEqual(["pkg"], [package["name"] for package in json.loads(manifest.read_text())["packages"]])


if __name__ == "__main__":
    unittest.main()
