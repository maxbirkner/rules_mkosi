"""Checks content produced by the config include, extra tree, and build source."""

import pathlib
import sys


def main():
    content = pathlib.Path(sys.argv[1]).read_bytes()
    for marker in (b"declared extra", b"declared source", b"rules-mkosi-staged"):
        if marker not in content:
            raise AssertionError("image is missing staged marker {!r}".format(marker))
    print("image contains config-tree and BuildSources markers")


if __name__ == "__main__":
    main()
