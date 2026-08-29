import importlib.util
import io
import os
import pathlib
import tarfile
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "extract_tree", os.path.join(os.path.dirname(__file__), "extract_tree.py")
)
extract_tree = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract_tree)


class ExtractTreeSecurityTest(unittest.TestCase):
    def test_rejects_member_traversal(self):
        for name in ("../escape", "usr/../../escape", "/etc/passwd"):
            with self.assertRaises(ValueError):
                extract_tree._member_path(name)

    def test_rejects_symlink_escape(self):
        with self.assertRaises(ValueError):
            extract_tree._link_target("usr/bin/tool", "../../../outside")

    def test_allows_in_root_relative_link(self):
        self.assertEqual(extract_tree._link_target("usr/bin/sh", "../lib/sh"), "usr/lib/sh")

    def test_rejects_symlink_parent_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = pathlib.Path(directory) / "bad.tar"
            root = pathlib.Path(directory) / "root"
            outside = pathlib.Path(directory) / "outside"
            with tarfile.open(archive, "w") as output:
                link = tarfile.TarInfo("usr/bin")
                link.type = tarfile.SYMTYPE
                link.linkname = "../../../outside"
                output.addfile(link)
                file_info = tarfile.TarInfo("usr/bin/escaped")
                file_info.size = 1
                output.addfile(file_info, io.BytesIO(b"x"))
            with self.assertRaises(ValueError):
                extract_tree.extract(str(archive), str(root))
            self.assertFalse(outside.exists())


if __name__ == "__main__":
    unittest.main()
