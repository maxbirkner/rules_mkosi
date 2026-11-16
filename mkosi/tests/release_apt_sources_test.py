"""Prove a release image retaining apt has no persistent network source."""

import os
import pathlib
import sys

import rules_mkosi_disk_image as disk_image

from mkosi.tests.runfile_paths import resolve_runfile


def main() -> None:
    image = resolve_runfile(sys.argv[1])
    launcher = resolve_runfile(sys.argv[2])
    root = pathlib.Path(os.environ["TEST_TMPDIR"]) / "release-root.ext4"
    disk_image.extract_root_partition(image, root)
    try:
        sources = disk_image.read_file(launcher, root, "/etc/apt/sources.list.d/debian.sources")
    except FileNotFoundError:
        return
    raise AssertionError("the release image keeps an APT source: {!r}".format(sources))


if __name__ == "__main__":
    main()
