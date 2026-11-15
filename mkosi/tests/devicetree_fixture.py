"""Encodes small flattened device tree (FDT) blobs for tests, without a device tree compiler.

As a script, it writes a blob whose root node has the given compatible strings and string properties.
"""

import argparse
import struct
from collections.abc import Mapping, Sequence
from pathlib import Path

_FDT_MAGIC = 0xD00DFEED
_HEADER_SIZE = 40
_MEMORY_RESERVATION_MAP = bytes(16)
_BEGIN_NODE, _END_NODE, _PROP, _END = 1, 2, 3, 9


def encode_device_tree(compatible: Sequence[str], properties: Mapping[str, bytes] | None = None) -> bytes:
    """Returns a version 17 FDT blob whose root node has the compatible strings and other properties.

    An empty compatible omits the property.
    """
    values = dict(properties or {})
    if compatible:
        values = {"compatible": encode_strings(compatible), **values}
    strings = b""
    structure = struct.pack(">I", _BEGIN_NODE) + _padded(b"\0")
    for name, value in values.items():
        structure += struct.pack(">III", _PROP, len(value), len(strings)) + _padded(value)
        strings += name.encode("ascii") + b"\0"
    structure += struct.pack(">II", _END_NODE, _END)
    structure_offset = _HEADER_SIZE + len(_MEMORY_RESERVATION_MAP)
    strings_offset = structure_offset + len(structure)
    size = strings_offset + len(strings)
    header = struct.pack(
        ">10I",
        _FDT_MAGIC,
        size,
        structure_offset,
        strings_offset,
        _HEADER_SIZE,
        17,
        16,
        0,
        len(strings),
        len(structure),
    )
    return header + _MEMORY_RESERVATION_MAP + structure + strings


def encode_strings(values: Sequence[str]) -> bytes:
    """Returns a device tree string list property value."""
    return b"".join(value.encode("ascii") + b"\0" for value in values)


def _padded(value: bytes) -> bytes:
    return value + bytes(-len(value) % 4)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compatible", action="append", required=True)
    parser.add_argument("--string-property", action="append", default=[], metavar="NAME=VALUE")
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    properties = dict(item.split("=", 1) for item in arguments.string_property)
    blob = encode_device_tree(
        arguments.compatible, {name: encode_strings([value]) for name, value in properties.items()}
    )
    arguments.output.write_bytes(blob)


if __name__ == "__main__":
    main()
