"""Prepare bind-test objects with the Bazel-managed Python runtime."""

import os
import sys


def main():
    directory = sys.argv[1]
    os.makedirs(directory, mode=0o700, exist_ok=True)
    for name, contents in (
        ("debian-tools-input", "packaged-input\n"),
        ("debian-tools-output", ""),
        ("debian-tools-counter", ""),
    ):
        with open(os.path.join(directory, name), "w", encoding="utf-8") as output:
            output.write(contents)


if __name__ == "__main__":
    main()
