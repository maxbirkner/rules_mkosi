"""Validates release provenance in the normalized image metadata."""

import json
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
        "lock_sha256": "38c9e6d7e3585c0b6ce5ccd71b03eababc0d6e2a0f0ffce77d1e6843e11fb4d8",
        "snapshot": "20260912T080811Z",
        "snapshot_url": "https://snapshot.debian.org/archive/debian/20260912T080811Z",
    }
    assert metadata["reproducibility"] == {
        "seed": "00000000-0000-4000-8000-000000000007",
        "source_date_epoch": 0,
    }


if __name__ == "__main__":
    main()
