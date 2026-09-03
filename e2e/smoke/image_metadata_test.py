"""Checks the public MkosiImageInfo metadata projection in a consumer module."""

import json
import pathlib
import sys


def main() -> None:
    metadata = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    assert metadata["format_version"] == "mkosi-image-build-metadata-v2"
    assert metadata["mkosi"] == {
        "compression": "none",
        "format": "disk",
        "split_artifacts": False,
        "version": "27",
    }
    assert metadata["artifacts"] == {
        "build_metadata": True,
        "manifest": False,
        "partition_metadata": sys.argv[2] == "release",
        "raw_image": True,
        "uki": False,
    }
    assert metadata["mode"] == sys.argv[2]
    assert metadata["firmware"] == (sys.argv[3] if len(sys.argv) > 3 else "uefi")
    if sys.argv[2] == "release":
        assert metadata["debian_snapshot"] == {
            "architecture": "amd64",
            "codename": "trixie",
            "format_version": "debian-snapshot-v1",
            "lock_sha256": "4feda33b82e94493cf6b80bac6ea1bdbc904afbea6b85bce7820d60f6e233401",
            "snapshot": "20250814T000000Z",
            "snapshot_url": "https://snapshot.debian.org/archive/debian/20250814T000000Z",
        }
        assert metadata["reproducibility"] == {
            "seed": "00000000-0000-4000-8000-000000000015",
            "source_date_epoch": 0,
        }
    else:
        assert "debian_snapshot" not in metadata
        assert "reproducibility" not in metadata


if __name__ == "__main__":
    main()
