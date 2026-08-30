import hashlib
import importlib.util
import io
import os
import pathlib
import re
import shutil
import sys
import tarfile
import unittest
from unittest import mock


_HERE = pathlib.Path(__file__).resolve().parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


extract_tree = _load("extract_tree")
debian_launcher = _load("debian_launcher")


class DebianToolsSecurityTest(unittest.TestCase):
    def setUp(self):
        self.work = pathlib.Path(os.environ.get("TEST_TMPDIR", ".")) / (
            "debian-tools-security-%s" % os.getpid()
        )
        shutil.rmtree(self.work, ignore_errors=True)
        self.work.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def _archive(self, members):
        archive = self.work / "tree.tar"
        with tarfile.open(archive, "w") as output:
            for member, data in members:
                output.addfile(member, io.BytesIO(data) if data is not None else None)
        return archive

    def test_digest_is_checked_before_tar_open(self):
        archive = self._archive([(tarfile.TarInfo("safe"), b"safe")])
        tampered = self.work / "tampered.tar"
        shutil.copyfile(archive, tampered)
        with tampered.open("r+b") as output:
            output.seek(0)
            output.write(b"x")
        with mock.patch.object(extract_tree.tarfile, "open", side_effect=AssertionError("tar opened")):
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                extract_tree.extract(str(tampered), str(self.work / "root"), "0" * 64)
        self.assertFalse((self.work / "root").exists())

    def test_launcher_rejects_tampered_archive_before_scratch(self):
        archive = self._archive([(tarfile.TarInfo("safe"), b"safe")])
        tampered = self.work / "tampered-launcher.tar"
        shutil.copyfile(archive, tampered)
        with tampered.open("r+b") as output:
            output.seek(0)
            output.write(b"!")
        scratch = self.work / "launcher-scratch"
        with mock.patch.dict(
            os.environ,
            {
                "MKOSI_DEBIAN_TOOLS_SCRATCH": str(scratch),
                "DEBIAN_TOOLS_EXTRACTOR": str(_HERE / "extract_tree.py"),
            },
        ):
            with self.assertRaisesRegex(RuntimeError, "digest mismatch"):
                debian_launcher._extract_root(
                    str(tampered),
                    hashlib.sha256(archive.read_bytes()).hexdigest(),
                    "/usr/bin/dpkg",
                    ([], []),
                )
        self.assertFalse(scratch.exists())

    def test_forward_symlink_and_hardlink_graphs(self):
        directory = tarfile.TarInfo("usr")
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o755
        usr_bin = tarfile.TarInfo("usr/bin")
        usr_bin.type = tarfile.DIRTYPE
        usr_bin.mode = 0o755
        usr_lib = tarfile.TarInfo("usr/lib")
        usr_lib.type = tarfile.DIRTYPE
        usr_lib.mode = 0o755
        one = tarfile.TarInfo("usr/bin/one")
        one.type = tarfile.SYMTYPE
        one.linkname = "two"
        two = tarfile.TarInfo("usr/bin/two")
        two.type = tarfile.SYMTYPE
        two.linkname = "../lib/real"
        hard = tarfile.TarInfo("usr/bin/hard")
        hard.type = tarfile.LNKTYPE
        hard.linkname = "usr/bin/base"
        chain = tarfile.TarInfo("usr/bin/chain")
        chain.type = tarfile.LNKTYPE
        chain.linkname = "usr/bin/hard"
        base = tarfile.TarInfo("usr/bin/base")
        base.mode = 0o755
        base.size = 4
        real = tarfile.TarInfo("usr/lib/real")
        real.size = 4
        archive = self._archive([
            (directory, None),
            (usr_bin, None),
            (usr_lib, None),
            (one, None),
            (two, None),
            (hard, None),
            (chain, None),
            (base, b"base"),
            (real, b"real"),
        ])
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        root = self.work / "root"
        extract_tree.extract(str(archive), str(root), digest)
        self.assertEqual((root / "usr/bin/one").resolve(), root / "usr/lib/real")
        self.assertEqual(os.stat(root / "usr/bin/hard").st_ino, os.stat(root / "usr/bin/base").st_ino)
        self.assertEqual(os.stat(root / "usr/bin/chain").st_ino, os.stat(root / "usr/bin/base").st_ino)

    def test_directory_symlink_prefix_chain_is_order_independent(self):
        real_directory = tarfile.TarInfo("realdir")
        real_directory.type = tarfile.DIRTYPE
        real_directory.mode = 0o755
        real_file = tarfile.TarInfo("realdir/file")
        real_file.mode = 0o644
        real_file.size = 4
        alias = tarfile.TarInfo("alias")
        alias.type = tarfile.SYMTYPE
        alias.linkname = "realdir"
        leaf = tarfile.TarInfo("leaf")
        leaf.type = tarfile.SYMTYPE
        leaf.linkname = "alias/file"
        archive = self._archive(
            [(leaf, None), (alias, None), (real_file, b"data"), (real_directory, None)]
        )
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        root = self.work / "prefix-root"
        extract_tree.extract(str(archive), str(root), digest)
        self.assertEqual((root / "leaf").resolve(), root / "realdir/file")

    def test_hardlink_target_is_archive_root_relative(self):
        directory = tarfile.TarInfo("usr")
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o755
        target = tarfile.TarInfo("usr/base")
        target.mode = 0o644
        target.size = 1
        link = tarfile.TarInfo("usr/bin-link")
        link.type = tarfile.LNKTYPE
        link.linkname = "usr/base"
        archive = self._archive([(link, None), (directory, None), (target, b"x")])
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        root = self.work / "root"
        extract_tree.extract(str(archive), str(root), digest)
        self.assertEqual(os.stat(root / "usr/base").st_ino, os.stat(root / "usr/bin-link").st_ino)

    def test_rejects_link_cycle_and_unexpected_dangling(self):
        first = tarfile.TarInfo("first")
        first.type = tarfile.SYMTYPE
        first.linkname = "second"
        second = tarfile.TarInfo("second")
        second.type = tarfile.SYMTYPE
        second.linkname = "first"
        archive = self._archive([(first, None), (second, None)])
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "cycle"):
            extract_tree.extract(str(archive), str(self.work / "cycle"), digest)

        dangling = tarfile.TarInfo("unexpected")
        dangling.type = tarfile.SYMTYPE
        dangling.linkname = "missing"
        archive = self._archive([(dangling, None)])
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "dangling"):
            extract_tree.extract(str(archive), str(self.work / "dangling"), digest)

    def test_preserves_documented_masks_and_environment_link(self):
        mask = tarfile.TarInfo("usr/lib/systemd/system/hwclock.service")
        mask.type = tarfile.SYMTYPE
        mask.linkname = "/dev/null"
        environment = tarfile.TarInfo("usr/lib/environment.d/99-environment.conf")
        environment.type = tarfile.SYMTYPE
        environment.linkname = "/etc/environment"
        archive = self._archive([(mask, None), (environment, None)])
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        root = self.work / "root"
        extract_tree.extract(str(archive), str(root), digest)
        self.assertTrue((root / "usr/lib/systemd/system/hwclock.service").is_symlink())
        self.assertTrue((root / "usr/lib/environment.d/99-environment.conf").is_symlink())
        self.assertTrue((root / "usr/lib/systemd/system/hwclock.service").resolve().exists())

    def test_authenticated_pinned_archive_preserves_documented_links(self):
        runfiles_root = pathlib.Path(os.environ.get("RUNFILES_DIR", ""))
        mapping = runfiles_root / "_repo_mapping"
        self.assertTrue(mapping.is_file())
        repository = None
        for line in mapping.read_text(encoding="utf-8").splitlines():
            fields = line.split(",", 2)
            if len(fields) == 3 and fields[1] == "mkosi_debian_packages":
                repository = fields[2]
                break
        self.assertIsNotNone(repository)
        archive = runfiles_root / repository / "flat.tar"
        self.assertTrue(archive.is_file())
        provenance = (_HERE / "provenance.bzl").read_text(encoding="utf-8")
        digest = re.search(
            r'DEBIAN_TOOLS_ARCHIVE_SHA256 = "([0-9a-f]{64})"', provenance
        ).group(1)
        self.assertEqual(digest, hashlib.sha256(archive.read_bytes()).hexdigest())
        root = self.work / "pinned-root"
        extract_tree.extract(str(archive), str(root), digest)
        for relative in (
            "usr/lib/environment.d/99-environment.conf",
            "usr/lib/systemd/system/cryptdisks-early.service",
            "usr/lib/systemd/system/cryptdisks.service",
            "usr/lib/systemd/system/hwclock.service",
            "usr/lib/systemd/system/x11-common.service",
        ):
            self.assertTrue((root / relative).is_symlink(), relative)
        links = sum(
            os.path.islink(os.path.join(directory, name))
            for directory, dirnames, names in os.walk(root)
            for name in dirnames + names
        )
        self.assertEqual(641, links)

    def test_mount_roles_canonical_paths_and_collisions(self):
        source = self.work / "input"
        source.write_text("input")
        cases = [
            (["--ro-bind", "%s:/workspace/input" % source], "read-only"),
            (["--rw-bind", "%s:/inputs/output" % source], "read-write"),
            (["--ro-bind", "%s:/inputs/../workspace" % source], "canonical"),
            (["--ro-bind", "%s:/inputs/x" % source, "--rw-bind", "%s:/inputs/x/y" % source], "overlap"),
        ]
        for arguments, message in cases:
            with self.subTest(message=message):
                with self.assertRaises(RuntimeError):
                    debian_launcher._validate_binds(arguments)
        for destination in ("/etc", "/usr/bin/tool", "/lib/x", "/etc/ssl/certs"):
            with self.subTest(destination=destination):
                with self.assertRaises(RuntimeError):
                    debian_launcher._validate_binds(
                        ["--rw-bind", "%s:/workspace/x" % source, "--ro-bind", "%s:%s" % (source, destination)]
                    )
        with self.assertRaisesRegex(RuntimeError, "overlap"):
            debian_launcher._validate_binds(
                [
                    "--ro-bind",
                    "%s:/inputs/x" % source,
                    "--ro-bind",
                    "%s:/inputs/x/y" % source,
                ]
            )
        with self.assertRaises(FileNotFoundError):
            debian_launcher._validate_binds(
                ["--ro-bind", "%s:/inputs/missing" % (self.work / "missing")]
            )

    def test_missing_mapping_and_executable_fail_precisely(self):
        original_argv = sys.argv
        original_environment = os.environ.copy()
        try:
            sys.argv = ["debian_launcher.py", "/usr/bin/not-mapped"]
            os.environ.clear()
            self.assertEqual(debian_launcher.main(), 2)
            sys.argv = ["debian_launcher.py", "/usr/bin/dpkg"]
            self.assertEqual(debian_launcher.main(), 1)
        finally:
            sys.argv = original_argv
            os.environ.clear()
            os.environ.update(original_environment)
        with self.assertRaises(RuntimeError):
            debian_launcher._require_executable(str(self.work), "/usr/bin/missing", "test executable")

    def test_preseeded_and_symlink_scratch_are_rejected(self):
        preseed = self.work / "preseed"
        preseed.mkdir()
        (preseed / "root").mkdir()
        with mock.patch.dict(os.environ, {"MKOSI_DEBIAN_TOOLS_SCRATCH": str(preseed)}):
            with self.assertRaisesRegex(RuntimeError, "empty"):
                debian_launcher._private_scratch()

        target = self.work / "target"
        target.mkdir()
        linked = self.work / "linked"
        linked.symlink_to(target, target_is_directory=True)
        with mock.patch.dict(os.environ, {"MKOSI_DEBIAN_TOOLS_SCRATCH": str(linked)}):
            with self.assertRaisesRegex(RuntimeError, "invalid"):
                debian_launcher._private_scratch()

        stale = self.work / "stale"
        stale.mkdir()
        (stale / ".complete").write_text("stale\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"MKOSI_DEBIAN_TOOLS_SCRATCH": str(stale)}):
            with self.assertRaisesRegex(RuntimeError, "empty"):
                debian_launcher._private_scratch()

        wrong_type = self.work / "wrong-type"
        wrong_type.write_text("not a directory", encoding="utf-8")
        with mock.patch.dict(os.environ, {"MKOSI_DEBIAN_TOOLS_SCRATCH": str(wrong_type)}):
            with self.assertRaisesRegex(RuntimeError, "invalid"):
                debian_launcher._private_scratch()

    def test_concurrent_scratch_claim_is_rejected(self):
        archive = self._archive([(tarfile.TarInfo("safe"), b"safe")])
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        scratch = self.work / "concurrent"
        scratch.mkdir()
        (scratch / ".in-use").mkdir()
        with mock.patch.dict(
            os.environ,
            {
                "MKOSI_DEBIAN_TOOLS_SCRATCH": str(scratch),
                "DEBIAN_TOOLS_EXTRACTOR": str(_HERE / "extract_tree.py"),
            },
        ):
            with self.assertRaisesRegex(RuntimeError, "already in use"):
                debian_launcher._extract_root(
                    str(archive), digest, "/usr/bin/dpkg", ([], [])
                )


if __name__ == "__main__":
    unittest.main()
