"""Prove a release image retaining apt has no persistent network source."""

import os
import pathlib
import sys

from mkosi.tests.release_root import extract_root_partition, run_debugfs_request
from mkosi.tests.runfile_paths import resolve_runfile


def main() -> None:
    image = resolve_runfile(sys.argv[1])
    launcher = resolve_runfile(sys.argv[2])
    root = pathlib.Path(os.environ["TEST_TMPDIR"]) / "release-root.ext4"
    extract_root_partition(image, root)
    result = run_debugfs_request(launcher, root, "cat /etc/apt/sources.list.d/debian.sources", "release-apt-sources")
    assert "File not found" in result.stdout + result.stderr, result.stdout + result.stderr


if __name__ == "__main__":
    main()
