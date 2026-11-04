"""Validates release provenance in the normalized image metadata."""

import json
import os
import pathlib
import sys


def main() -> None:
    metadata = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    assert metadata["format_version"] == "mkosi-image-build-metadata-v3"
    assert metadata["mode"] == "release"
    assert metadata["artifacts"]["partition_metadata"] is True
    assert metadata["debian_snapshot"] == {
        "architecture": "amd64",
        "codename": "trixie",
        "components": ["main"],
        "format_version": "debian-snapshot-v1",
        "lock_sha256": os.environ["DEBIAN_TOOLS_LOCK_SHA256"],
        "snapshot": os.environ["DEBIAN_TOOLS_SNAPSHOT"],
        "snapshot_url": os.environ["DEBIAN_TOOLS_SNAPSHOT_URL"],
    }
    assert metadata["reproducibility"] == {
        "seed": "00000000-0000-4000-8000-000000000007",
        "source_date_epoch": 0,
    }


if __name__ == "__main__":
    main()
