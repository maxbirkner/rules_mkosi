#!/usr/bin/python3
"""Project deterministic UKI section metadata and verify its root-hash linkage."""

import argparse
import hashlib
import json
from pathlib import Path

import pefile


def project(uki_path, root_hash_path=None):
    data = Path(uki_path).read_bytes()
    pe = pefile.PE(data=data, fast_load=True)
    sections = []
    section_data = {}
    for section in pe.sections:
        name = section.Name.rstrip(b"\0").decode("ascii")
        content = section.get_data()
        sections.append(
            {"name": name, "sha256": hashlib.sha256(content).hexdigest(), "size": len(content)}
        )
        section_data[name] = content
    required = {".linux", ".initrd", ".cmdline", ".osrel"}
    missing = sorted(required - section_data.keys())
    if missing:
        raise ValueError("UKI is missing required sections: {}".format(", ".join(missing)))
    root_hash = None
    if root_hash_path:
        root_hash = Path(root_hash_path).read_text().strip().lower()
        if not root_hash or any(c not in "0123456789abcdef" for c in root_hash):
            raise ValueError("dm-verity root hash is not lowercase hexadecimal")
        cmdline = section_data[".cmdline"].rstrip(b"\0").decode("utf-8")
        if "roothash={}".format(root_hash) not in cmdline.split():
            raise ValueError("UKI .cmdline does not link the declared dm-verity root hash")
    return {
        "format_version": "mkosi-uki-metadata-v1",
        "root_hash": root_hash,
        "sections": sorted(sections, key=lambda item: item["name"]),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--uki", required=True)
    parser.add_argument("--root-hash")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        metadata = project(args.uki, args.root_hash)
    except (OSError, UnicodeError, ValueError, pefile.PEFormatError) as error:
        raise SystemExit("UKI_METADATA_INVALID: {}".format(error))
    Path(args.output).write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
