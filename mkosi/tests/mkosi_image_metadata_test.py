"""Validates the stable, reviewable mkosi image build-metadata projection."""

import json
import pathlib
import sys


def main() -> None:
    metadata = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    mode = sys.argv[2]
    assert metadata == {
        "artifacts": {
            "build_metadata": True,
            "manifest": False,
            "partition_metadata": False,
            "raw_image": True,
            "uki": False,
        },
        "format_version": "mkosi-image-build-metadata-v2",
        "firmware": "uefi",
        "mkosi": {
            "compression": "none",
            "format": "disk",
            "split_artifacts": False,
            "version": "27",
        },
        "mode": mode,
    }


if __name__ == "__main__":
    main()
