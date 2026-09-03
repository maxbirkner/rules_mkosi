"""Validates release provenance in the normalized image metadata."""

import json
import pathlib
import sys


def main() -> None:
    metadata = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    assert metadata["format_version"] == "mkosi-image-build-metadata-v2"
    assert metadata["mode"] == "release"
    assert metadata["firmware"] == "uefi"
    assert metadata["artifacts"]["partition_metadata"] is True
    assert metadata["debian_snapshot"] == {
        "architecture": "amd64",
        "codename": "trixie",
        "format_version": "debian-snapshot-v1",
        "lock_sha256": "4feda33b82e94493cf6b80bac6ea1bdbc904afbea6b85bce7820d60f6e233401",
        "snapshot": "20250814T000000Z",
        "snapshot_url": "https://snapshot.debian.org/archive/debian/20250814T000000Z",
    }
    assert metadata["reproducibility"] == {
        "seed": "00000000-0000-4000-8000-000000000007",
        "source_date_epoch": 0,
    }


if __name__ == "__main__":
    main()
