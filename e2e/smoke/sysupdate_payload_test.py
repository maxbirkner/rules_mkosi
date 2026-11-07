"""Checks the versioned A/B release contract through public providers in a consumer module."""

import hashlib
import json
import pathlib
import struct
import sys

ROOT = "4f68bce3-e8cd-4db1-96e7-fbcaf984b709"
ROOT_VERITY = "2c7357ed-ebd2-46d9-aec1-23d437ec2bf5"
EROFS_MAGIC = struct.pack("<I", 0xE0F5E1E2)


def _check_minimized_erofs(path: pathlib.Path, slot_size: int) -> None:
    """Checks that the payload holds an erofs file system, not padded to the size of its slot."""
    with path.open("rb") as root:
        root.seek(1024)
        assert root.read(4) == EROFS_MAGIC, "{} is not an erofs file system".format(path.name)
    assert 0 < path.stat().st_size < slot_size // 2, (path.stat().st_size, slot_size)


def main() -> None:
    payload, partitions, build_metadata, transfers, manifest = (pathlib.Path(argument) for argument in sys.argv[1:6])

    metadata = json.loads(build_metadata.read_text(encoding="utf-8"))
    assert metadata["image"] == {"id": "rules-mkosi-ab", "version": "2"}, metadata["image"]
    assert metadata["artifacts"]["manifest"] is True

    # The release finalizes a base, which installed every package of the image.
    packages = json.loads(manifest.read_text(encoding="utf-8"))
    assert packages["config"]["name"] == "rules-mkosi-ab", packages["config"]
    assert packages["config"]["version"] == "2", packages["config"]
    names = {package["name"] for package in packages["packages"]}
    assert {"linux-image-amd64", "systemd", "systemd-boot"} <= names, sorted(names)

    slots = json.loads(partitions.read_text(encoding="utf-8"))["partitions"]
    labels = {(slot["type_guid"], slot["label"]): slot for slot in slots}
    root = labels[(ROOT, "rules-mkosi-ab_2")]
    verity = labels[(ROOT_VERITY, "rules-mkosi-ab_2_verity")]
    assert sorted(slot["label"] for slot in slots if slot["type_guid"] in (ROOT, ROOT_VERITY)) == [
        "_empty",
        "_empty",
        "rules-mkosi-ab_2",
        "rules-mkosi-ab_2_verity",
    ]

    expected = {
        "rules-mkosi-ab_2.efi",
        "rules-mkosi-ab_2.root.{}.raw".format(root["uuid"]),
        "rules-mkosi-ab_2.root-verity.{}.raw".format(verity["uuid"]),
    }
    assert {path.name for path in payload.iterdir()} == expected | {"SHA256SUMS"}
    _check_minimized_erofs(payload / "rules-mkosi-ab_2.root.{}.raw".format(root["uuid"]), root["size_bytes"])
    sums = {}
    for line in (payload / "SHA256SUMS").read_text(encoding="ascii").splitlines():
        digest, name = line.split("  ", 1)
        sums[name] = digest
    assert set(sums) == expected
    for name, digest in sums.items():
        assert hashlib.sha256((payload / name).read_bytes()).hexdigest() == digest, name

    assert sorted(path.name for path in transfers.iterdir()) == [
        "10-root.transfer",
        "20-root-verity.transfer",
        "90-uki.transfer",
    ]
    uki = (transfers / "90-uki.transfer").read_text(encoding="ascii")
    assert "TriesLeft=1\n" in uki, uki


if __name__ == "__main__":
    main()
