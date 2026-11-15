"""Reads flattened device tree (FDT) blobs, the .dtb files that firmware and systemd-stub hand to the kernel.

The format is specified in chapter 5 of the Devicetree Specification (https://www.devicetree.org/specifications/).
As a script, it validates the device trees of mkosi_image(devicetrees = ...) and stages them for the image build.
"""

import argparse
import shutil
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

FDT_MAGIC = 0xD00DFEED

# magic, totalsize, off_dt_struct, off_dt_strings, off_mem_rsvmap, version, last_comp_version, boot_cpuid_phys,
# size_dt_strings, size_dt_struct; all big-endian.
_HEADER = struct.Struct(">10I")
_TOKEN = struct.Struct(">I")
_PROPERTY = struct.Struct(">II")
_BEGIN_NODE, _END_NODE, _PROP, _NOP = 1, 2, 3, 4
# Version 17 is the current format; it is backwards compatible with version 16, which every reader understands.
_COMPATIBLE_VERSION = 16


class DeviceTreeError(ValueError):
    """A blob is not a well-formed flattened device tree."""


@dataclass(frozen=True)
class DeviceTree:
    """The facts about a device tree blob that boot artifacts record.

    Attributes:
        size: The blob's totalsize; bytes after it, such as section padding, are not part of the device tree.
        compatible: The root node's compatible strings, most specific first, which systemd-stub matches against the
            hardware to select a .dtbauto section.
    """

    size: int
    compatible: tuple[str, ...]


def parse_device_tree(blob: bytes) -> DeviceTree:
    """Returns the size and root compatible strings of an FDT blob.

    Raises DeviceTreeError if blob does not start with the FDT magic 0xd00dfeed or is malformed.
    """
    try:
        return _parse(blob)
    except (struct.error, UnicodeDecodeError) as error:
        raise DeviceTreeError("malformed flattened device tree: {}".format(error)) from error


def _parse(blob: bytes) -> DeviceTree:
    if len(blob) < _HEADER.size:
        raise DeviceTreeError("not a flattened device tree: {} bytes are shorter than its header".format(len(blob)))
    header = _HEADER.unpack_from(blob)
    magic, size, structure_offset, strings_offset = header[:4]
    last_compatible_version, strings_size, structure_size = header[6], header[8], header[9]
    if magic != FDT_MAGIC:
        raise DeviceTreeError(
            "not a flattened device tree: magic 0x{:08x} instead of 0x{:08x}".format(magic, FDT_MAGIC)
        )
    if size > len(blob):
        raise DeviceTreeError("flattened device tree is truncated: {} of {} bytes".format(len(blob), size))
    if last_compatible_version > _COMPATIBLE_VERSION:
        raise DeviceTreeError("flattened device tree format version {} is unsupported".format(last_compatible_version))
    structure = _block(blob, size, structure_offset, structure_size, "structure")
    strings = _block(blob, size, strings_offset, strings_size, "strings")
    return DeviceTree(size=size, compatible=_root_compatible(structure, strings))


def _block(blob: bytes, size: int, offset: int, length: int, name: str) -> bytes:
    if offset + length > size:
        raise DeviceTreeError("flattened device tree {} block ends after the blob".format(name))
    return blob[offset : offset + length]


def _root_compatible(structure: bytes, strings: bytes) -> tuple[str, ...]:
    token, offset = _next_token(structure, 0)
    if token != _BEGIN_NODE:
        raise DeviceTreeError("flattened device tree has no root node")
    name, offset = _string(structure, offset)
    if name:
        raise DeviceTreeError("flattened device tree root node is named {!r}".format(name))
    offset = _aligned(offset)
    while True:
        token, offset = _next_token(structure, offset)
        if token != _PROP:
            # The root's properties precede its first child node and its end.
            if token in (_BEGIN_NODE, _END_NODE):
                return ()
            raise DeviceTreeError("flattened device tree has unexpected token {} in its root node".format(token))
        length, name_offset = _PROPERTY.unpack_from(structure, offset)
        offset += _PROPERTY.size
        value = structure[offset : offset + length]
        if len(value) != length:
            raise DeviceTreeError("flattened device tree property ends after the structure block")
        offset = _aligned(offset + length)
        if _string(strings, name_offset)[0] == "compatible":
            return _string_list(value)


def _next_token(structure: bytes, offset: int) -> tuple[int, int]:
    while True:
        (token,) = _TOKEN.unpack_from(structure, offset)
        offset += _TOKEN.size
        if token != _NOP:
            return token, offset


def _string(block: bytes, offset: int) -> tuple[str, int]:
    end = block.find(b"\0", offset)
    if end < 0:
        raise DeviceTreeError("flattened device tree string at offset {} is not terminated".format(offset))
    return block[offset:end].decode("ascii"), end + 1


def _string_list(value: bytes) -> tuple[str, ...]:
    if not value.endswith(b"\0"):
        raise DeviceTreeError("flattened device tree compatible property is not a list of strings")
    return tuple(item.decode("ascii") for item in value[:-1].split(b"\0"))


def _aligned(offset: int) -> int:
    return (offset + 3) & ~3


def stage_device_trees(sources: Sequence[Path], directory: Path) -> None:
    """Copies device tree blobs into directory by file name, after checking that each one can be selected.

    Raises SystemExit naming the file if one is not a flattened device tree, has no root compatible string, or has the
    file name of another one.
    """
    directory.mkdir(parents=True, exist_ok=True)
    for source in sources:
        try:
            tree = parse_device_tree(source.read_bytes())
        except DeviceTreeError as error:
            raise SystemExit("devicetrees: {}: {}".format(source, error)) from error
        if not tree.compatible:
            raise SystemExit("devicetrees: {}: the root node has no compatible string".format(source))
        target = directory / source.name
        if target.exists():
            raise SystemExit("devicetrees: {}: another device tree has the file name {}".format(source, source.name))
        shutil.copyfile(source, target)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("sources", nargs="+", type=Path)
    arguments = parser.parse_args()
    stage_device_trees(arguments.sources, arguments.output_directory)


if __name__ == "__main__":
    main()
