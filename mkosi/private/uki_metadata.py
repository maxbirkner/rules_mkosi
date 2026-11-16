#!/usr/bin/python3
"""Project deterministic UKI section metadata and verify its root-hash linkage."""

import argparse
import hashlib
import json
import runpy
from pathlib import Path
from typing import TYPE_CHECKING

import pefile

_load_sibling = runpy.run_path(str(Path(__file__).with_name("sibling_loader.py")))["load_sibling"]
if TYPE_CHECKING:
    from mkosi.private import devicetree
else:
    devicetree = _load_sibling(__file__, "devicetree")

# ukify embeds one device tree as .dtb, which systemd-stub always installs, or several as .dtbauto, of which it installs
# the one whose root compatible string matches the hardware.
_DEVICETREE_SECTIONS = (".dtb", ".dtbauto")


def project(uki_path: str | Path, root_hash_path: str | Path | None = None) -> dict[str, object]:
    data = Path(uki_path).read_bytes()
    pe = pefile.PE(data=data, fast_load=True)
    sections: list[dict[str, str | int]] = []
    section_data: dict[str, bytes] = {}
    devicetrees: list[dict[str, object]] = []
    for section in pe.sections:
        name = section.Name.rstrip(b"\0").decode("ascii")
        content = section.get_data()
        sections.append({"name": name, "sha256": hashlib.sha256(content).hexdigest(), "size": len(content)})
        section_data[name] = content
        if name in _DEVICETREE_SECTIONS:
            devicetrees.append(describe_devicetree_section(name, content))
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
        "devicetrees": devicetrees,
        "format_version": "mkosi-uki-metadata-v2",
        "root_hash": root_hash,
        "sections": sorted(sections, key=lambda item: item["name"]),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def describe_devicetree_section(name: str, content: bytes) -> dict[str, object]:
    """Returns the root compatible strings, size and SHA-256 of the device tree in a UKI section.

    The digest covers the device tree's own bytes, without the section's padding, so it equals the digest of the .dtb
    file that ukify embedded. Raises ValueError for a blob that is not a device tree, or a .dtbauto section that
    systemd-stub could never select because its root node has no compatible string.
    """
    try:
        tree = devicetree.parse_device_tree(content)
    except devicetree.DeviceTreeError as error:
        raise ValueError("UKI {} section: {}".format(name, error)) from error
    if name == ".dtbauto" and not tree.compatible:
        raise ValueError("UKI .dtbauto section has no root compatible string, so systemd-stub never selects it")
    blob = content[: tree.size]
    return {
        "compatible": list(tree.compatible),
        "section": name,
        "sha256": hashlib.sha256(blob).hexdigest(),
        "size": tree.size,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uki", required=True)
    parser.add_argument("--root-hash")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        metadata = project(args.uki, args.root_hash)
    except (OSError, UnicodeError, ValueError, pefile.PEFormatError) as error:
        raise SystemExit("UKI_METADATA_INVALID: {}".format(error)) from error
    Path(args.output).write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
