"""Checks the public MkosiImageInfo metadata projection in a consumer module."""

import json
import os
import pathlib
import sys


def main() -> None:
    metadata = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    assert metadata["format_version"] == "mkosi-image-build-metadata-v3"
    immutable = len(sys.argv) > 3 and sys.argv[3] == "immutable"
    assert metadata["mkosi"] == {
        "compression": "none",
        "format": "disk",
        "split_artifacts": immutable,
        "version": "27.1",
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
        "uki_metadata": immutable,
        "verity_metadata": immutable,
    }
    assert metadata["mode"] == sys.argv[2]
    # Both the release and the tracer image install packages from the built-in snapshot.
    assert metadata["debian_snapshot"] == json.loads(os.environ["DEBIAN_TOOLS_SNAPSHOT_METADATA"])
    if sys.argv[2] == "release":
        assert metadata["artifacts"]["uki"] is immutable
        assert metadata["reproducibility"] == {
            "seed": "00000000-0000-4000-8000-000000000015",
            "source_date_epoch": 0,
        }
    else:
        assert "reproducibility" not in metadata


if __name__ == "__main__":
    main()
