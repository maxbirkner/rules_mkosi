"""Checks that a finalized A/B release records and installs the extra package of its base."""

import hashlib
import json
import pathlib
import sys


def main() -> None:
    metadata_path, manifest_path, package_path = (pathlib.Path(argument) for argument in sys.argv[1:4])
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    package = package_path.read_bytes()
    assert metadata == {
        "architecture": "amd64",
        "format_version": "mkosi-extra-packages-v1",
        "packages": [
            {
                "architecture": "amd64",
                "filename": "hello_2.10-5_amd64.deb",
                "name": "hello",
                "sha256": hashlib.sha256(package).hexdigest(),
                "size": len(package),
                "version": "2.10-5",
            }
        ],
    }, metadata

    # mkosi's manifest lists what dpkg installed into the base.
    installed = json.loads(manifest_path.read_text(encoding="utf-8"))["packages"]
    hello = [entry for entry in installed if entry["name"] == "hello"]
    assert len(hello) == 1 and hello[0]["version"] == "2.10-5", hello


if __name__ == "__main__":
    main()
