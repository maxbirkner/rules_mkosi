"""Checks the public MkosiImageInfo metadata projection in a consumer module."""

import json
import pathlib
import sys


def main() -> None:
    metadata = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    assert metadata["format_version"] == "mkosi-image-build-metadata-v2"
    immutable = len(sys.argv) > 3 and sys.argv[3] == "immutable"
    assert metadata["mkosi"] == {
        "compression": "none",
        "format": "disk",
        "split_artifacts": immutable,
        "version": "27",
    }
    assert metadata["artifacts"] == {
        "build_metadata": True,
        "manifest": False,
        "partition_metadata": sys.argv[2] == "release",
        "raw_image": True,
        "uki": immutable,
        "root_image": immutable,
        "root_hash": immutable,
        "root_hash_image": immutable,
        "root_hash_signature": False,
        "uki_metadata": immutable,
        "verity_metadata": immutable,
    }
    assert metadata["mode"] == sys.argv[2]
    if sys.argv[2] == "release":
        assert metadata["artifacts"]["uki"] is immutable
        assert metadata["debian_snapshot"] == {
            "architecture": "amd64",
            "codename": "trixie",
            "format_version": "debian-snapshot-v1",
            "lock_sha256": "815a4413a0780d14631be34078bceb929ccae29754a911aecadc6fca108123eb",
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
