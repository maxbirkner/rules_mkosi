"""Checks that a version derived from the inputs of an image covers the content of its extra packages."""

import hashlib
import json
import sys
from pathlib import Path


def main() -> None:
    manifest_path, *packages = sys.argv[1:]
    inputs = json.loads(Path(manifest_path).read_text(encoding="ascii"))["inputs"]
    for package in packages:
        # The build reads each package at its own path, which is the package's root path in the output tree.
        entry = inputs["bazel-out/bin/" + package]
        # The version hashes this digest, so any change to the package changes the version.
        assert entry["sha256"] == hashlib.sha256(Path(package).read_bytes()).hexdigest(), (package, entry)
    index = "bazel-out/bin/mkosi/tests/extra_packages_release.extra-packages/"
    # The index holds no copy of the packages.
    assert sorted(path for path in inputs if path.startswith(index)) == [index + "Packages", index + "Release"]


if __name__ == "__main__":
    main()
