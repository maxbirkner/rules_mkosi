"""Extracts the pinned arm64 Debian tools archive and checks it against the launcher's arm64 layout, on any host."""

import importlib.util
import os
import pathlib
import re
import sys
import types
import unittest

from python.runfiles import runfiles


def load_module(name: str, path: pathlib.Path) -> types.ModuleType:
    """Loads a Python file of this package that is not importable by name."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_HERE = pathlib.Path(__file__).parent
debian_launcher = load_module("debian_launcher", _HERE / "debian_launcher.py")
extract_tree = load_module("extract_tree", _HERE / "extract_tree.py")


class DebianToolsArm64TreeTest(unittest.TestCase):
    root: str

    @classmethod
    def setUpClass(cls) -> None:
        resolver = runfiles.Create()
        assert resolver is not None
        archive, provenance = (resolver.Rlocation(path) for path in sys.argv[1:3])
        match = re.search(
            r'^DEBIAN_TOOLS_ARM64_ARCHIVE_SHA256 = "([0-9a-f]{64})"$', pathlib.Path(provenance).read_text(), re.M
        )
        assert match is not None, "provenance.bzl lacks the arm64 archive digest"
        cls.root = os.path.join(os.environ["TEST_TMPDIR"], "arm64-tools")
        # Verifies the archive against its pinned digest before it unpacks anything.
        extract_tree.extract(archive, cls.root, match.group(1))

    def test_tree_satisfies_the_arm64_launcher_layout(self) -> None:
        layout = debian_launcher.select_tools_layout("aarch64")
        for tool in debian_launcher.TOOLS.values():
            with self.subTest(tool=tool):
                loader, executable = debian_launcher._validate_root(self.root, tool, layout)
                self.assertTrue(loader.endswith("ld-linux-aarch64.so.1"), loader)
                self.assertTrue(executable.endswith(tool), executable)

    def test_tree_has_no_x86_64_lib64_link(self) -> None:
        self.assertFalse(os.path.lexists(os.path.join(self.root, "lib64")))

    def test_tree_has_libfaketime_for_signing(self) -> None:
        path = "usr/lib/aarch64-linux-gnu/faketime/libfaketime.so.1"
        self.assertTrue(os.path.isfile(os.path.join(self.root, path)), path)

    def test_other_cpus_have_no_debian_tools(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "no Debian tools for the CPU riscv64"):
            debian_launcher.select_tools_layout("riscv64")


if __name__ == "__main__":
    unittest.main(argv=sys.argv[:1])
