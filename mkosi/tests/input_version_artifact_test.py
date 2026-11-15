"""Checks that an image built with image_version_from_inputs carries its derived version in os-release."""

import json
import re
import struct
import sys
from pathlib import Path


def pe_section(path, name):
    """Returns the raw content of the named section of a PE file such as a UKI."""
    data = Path(path).read_bytes()
    (header,) = struct.unpack_from("<I", data, 0x3C)
    if data[header : header + 4] != b"PE\0\0":
        raise ValueError("{} is not a PE file".format(path))
    sections, optional_header_size = struct.unpack_from("<H12xH", data, header + 6)
    table = header + 24 + optional_header_size
    for index in range(sections):
        entry = table + 40 * index
        virtual_size, raw_size, raw_offset = struct.unpack_from("<I4xII", data, entry + 8)
        if data[entry : entry + 8].rstrip(b"\0") == name.encode("ascii"):
            return data[raw_offset : raw_offset + min(virtual_size, raw_size)]
    raise ValueError("{} has no {} section".format(path, name))


def os_release(content):
    """Returns the KEY=value assignments of os-release content."""
    text = content.rstrip(b"\0").decode("utf-8")
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line and not line.startswith("#"))


def main() -> None:
    version_file, digest_file, uki, build_metadata, inputs_manifest = sys.argv[1:6]
    version = Path(version_file).read_text(encoding="ascii")
    digest = Path(digest_file).read_text(encoding="ascii")
    assert re.fullmatch(r"[0-9a-f]{16}\n", version), version
    assert re.fullmatch(r"[0-9a-f]{64}\n", digest), digest
    version = version.removesuffix("\n")
    assert digest.startswith(version), (version, digest)

    release = os_release(pe_section(uki, ".osrel"))
    assert release["IMAGE_ID"].strip('"') == "rules-mkosi-ab", release
    assert release["IMAGE_VERSION"].strip('"') == version, (release, version)
    metadata = json.loads(Path(build_metadata).read_text(encoding="utf-8"))
    assert metadata["image"] == {"id": "rules-mkosi-ab", "version": version}, metadata["image"]

    # The manifest lists the base that the image finalizes among the inputs of the version.
    manifest = json.loads(Path(inputs_manifest).read_text(encoding="ascii"))
    assert (manifest["image_version"], manifest["input_digest"] + "\n") == (version, digest), manifest["image_version"]
    base = manifest["inputs"]["bazel-out/bin/mkosi/tests/two_stage_base.initrd"]
    assert base["kind"] == "file" and re.fullmatch(r"[0-9a-f]{64}", base["sha256"]), base


if __name__ == "__main__":
    main()
