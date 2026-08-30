"""Prepare bind-test objects with the Bazel-managed Python runtime."""

import os
import sys


def main():
    directory = sys.argv[1]
    os.mkdir(directory, 0o700)
    for name, contents in (
        ("debian-tools-input", "packaged-input\n"),
        ("debian-tools-output", ""),
        ("debian-tools-counter", ""),
    ):
        with open(os.path.join(directory, name), "w", encoding="utf-8") as output:
            output.write(contents)


if __name__ == "__main__":
    main()
