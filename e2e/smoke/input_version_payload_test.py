"""Checks a consumer release whose version mkosi_image derives from the inputs of its build."""

import json
import pathlib
import re
import sys

ROOT = "4f68bce3-e8cd-4db1-96e7-fbcaf984b709"
ROOT_VERITY = "2c7357ed-ebd2-46d9-aec1-23d437ec2bf5"


def _version_and_digest(paths):
    """Returns the version and the full digest from the image_version output group, told apart by their format."""
    contents = sorted((path.read_text(encoding="ascii") for path in paths), key=len)
    version, digest = (content.removesuffix("\n") for content in contents)
    assert re.fullmatch(r"[0-9a-f]{16}", version), contents
    assert re.fullmatch(r"[0-9a-f]{64}", digest), contents
    assert digest.startswith(version), contents
    return version


def main() -> None:
    *files, payload, partitions, build_metadata = (pathlib.Path(argument) for argument in sys.argv[1:])
    assert len(files) == 2, files
    version = _version_and_digest(files)
    name = "rules-mkosi_" + version

    # The UKI's .osrel section is the os-release that the booted release reports.
    uki = (payload / (name + ".efi")).read_bytes()
    assert set(re.findall(rb"^IMAGE_VERSION=\"?([^\"\n]*)", uki, re.MULTILINE)) == {version.encode()}, version
    assert set(re.findall(rb"^IMAGE_ID=\"?([^\"\n]*)", uki, re.MULTILINE)) == {b"rules-mkosi"}

    metadata = json.loads(build_metadata.read_text(encoding="utf-8"))
    assert metadata["image"] == {"id": "rules-mkosi", "version": version}, metadata["image"]
    slots = json.loads(partitions.read_text(encoding="utf-8"))["partitions"]
    labels = {(slot["type_guid"], slot["label"]) for slot in slots}
    assert {(ROOT, name), (ROOT_VERITY, name + "_verity")} <= labels, labels
    names = {path.name for path in payload.iterdir()}
    assert name + ".efi" in names, names
    assert len([entry for entry in names if entry.startswith(name + ".root")]) == 2, names


if __name__ == "__main__":
    main()
