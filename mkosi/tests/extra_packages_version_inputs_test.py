"""Checks that a version derived from the inputs of an image covers the content of its extra packages."""

import hashlib
import json
import sys
from pathlib import Path


def main() -> None:
    manifest_path, *packages = sys.argv[1:]
    inputs = json.loads(Path(manifest_path).read_text(encoding="ascii"))["inputs"]
    repository = "bazel-out/bin/mkosi/tests/extra_packages_release.extra-packages/"
    filenames = ("rules-mkosi-hello_1.0_all.deb", "netbase_0~rules.mkosi1_all.deb")
    for package, filename in zip(packages, filenames, strict=True):
        entry = inputs[repository + filename]
        # The version hashes this digest, so any change to the package changes the version.
        assert entry["sha256"] == hashlib.sha256(Path(package).read_bytes()).hexdigest(), (filename, entry)
    for index in ("Packages", "Release"):
        assert repository + index in inputs, index


if __name__ == "__main__":
    main()
