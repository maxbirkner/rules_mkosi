import hashlib
import importlib.util
import io
import os
import pathlib
import shutil
import tarfile
import unittest

spec = importlib.util.spec_from_file_location(
    "extract_tree", os.path.join(os.path.dirname(__file__), "extract_tree.py")
)
extract_tree = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract_tree)


class ExtractTreeSecurityTest(unittest.TestCase):
    def setUp(self):
        self.directory = pathlib.Path(os.environ.get("TEST_TMPDIR", ".")) / (
            "extract-tree-security-%s" % os.getpid()
        )
        shutil.rmtree(self.directory, ignore_errors=True)
        self.directory.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_rejects_member_traversal(self):
        for name in ("../escape", "usr/../../escape", "/etc/passwd"):
            with self.assertRaises(ValueError):
                extract_tree._member_path(name)

    def test_rejects_symlink_escape(self):
        with self.assertRaises(ValueError):
            extract_tree._link_target("usr/bin/tool", "../../../outside")

    def test_allows_in_root_relative_link(self):
        self.assertEqual(extract_tree._link_target("usr/bin/sh", "../lib/sh"), "usr/lib/sh")

    def test_preserves_debian_empty_directory_symlink_target(self):
        target = tarfile.TarInfo("etc/systemd/user")
        target.type = tarfile.DIRTYPE
        target.mode = 0o755
        link = tarfile.TarInfo("etc/xdg/systemd/user")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../systemd/user"
        archive = self.directory / "systemd-user.tar"
        with tarfile.open(archive, "w") as output:
            output.addfile(target)
            output.addfile(link)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        root = self.directory / "root"
        extract_tree.extract(str(archive), str(root), digest)
        self.assertTrue((root / "etc/xdg/systemd/user").is_symlink())
        self.assertEqual(
            os.readlink(root / "etc/xdg/systemd/user"),
            "../../systemd/user",
        )
        self.assertTrue((root / "etc/xdg/systemd/user").exists())
        self.assertTrue((root / "etc/systemd/user/.rules_mkosi_empty_directory").is_file())

    def test_rejects_symlink_parent_archive(self):
        archive = self.directory / "bad.tar"
        root = self.directory / "root"
        outside = self.directory / "outside"
        with tarfile.open(archive, "w") as output:
            link = tarfile.TarInfo("usr/bin")
            link.type = tarfile.SYMTYPE
            link.linkname = "../../../outside"
            output.addfile(link)
            file_info = tarfile.TarInfo("usr/bin/escaped")
            file_info.size = 1
            output.addfile(file_info, io.BytesIO(b"x"))
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        with self.assertRaises(ValueError):
            extract_tree.extract(str(archive), str(root), digest)
        self.assertFalse(outside.exists())


if __name__ == "__main__":
    unittest.main()
