"""Checks the layout and contents of a configuration tree assembled from srcs and shared trees."""

import pathlib
import sys
import unittest

TREE = pathlib.Path(sys.argv.pop(1))

EXPECTED = {
    "mkosi.conf": None,
    "mkosi.include.conf": None,
    "mkosi.conf.d/20-extra.conf": "[Output]\nImageId=rules-mkosi-staged\n",
    "mkosi.extra/etc/declared-marker": "declared extra\n",
    "mkosi.extra/opt/shared/hello.txt": "declared source\n",
    "mkosi.extra/opt/shared/mkosi.build": None,
    "mkosi.extra/usr/share/generated-source.txt": "generated",
    "mkosi.initrd.conf/mkosi.extra/opt/shared/hello.txt": "declared source\n",
    "mkosi.initrd.conf/mkosi.extra/opt/shared/mkosi.build": None,
}


class ConfigTreeArtifactTest(unittest.TestCase):
    def test_every_input_is_at_its_destination(self):
        files = sorted(path.relative_to(TREE).as_posix() for path in TREE.rglob("*") if not path.is_dir())
        self.assertEqual(sorted(EXPECTED), files)
        for path, content in EXPECTED.items():
            if content is not None:
                self.assertEqual(content, (TREE / path).read_text(), path)

    def test_shared_tree_is_identical_in_image_and_initrd(self):
        for name in ("hello.txt", "mkosi.build"):
            image = TREE / "mkosi.extra/opt/shared" / name
            initrd = TREE / "mkosi.initrd.conf/mkosi.extra/opt/shared" / name
            self.assertEqual(image.read_bytes(), initrd.read_bytes(), name)


if __name__ == "__main__":
    unittest.main()
