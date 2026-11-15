"""Encodes and edits small flattened device tree (FDT) blobs for tests, without a device tree compiler.

As a script, it writes a blob whose root node has the given compatible strings and string properties, or, with
--input, a copy of a blob with those root properties replaced or added.
"""

import argparse
import struct
from collections.abc import Mapping, Sequence
from pathlib import Path

_FDT_MAGIC = 0xD00DFEED
_HEADER = struct.Struct(">10I")
_EMPTY_MEMORY_RESERVATION_MAP = bytes(16)
_BEGIN_NODE, _END_NODE, _PROP, _NOP, _END = 1, 2, 3, 4, 9

# A structure block token: (_BEGIN_NODE, node name, b""), (_PROP, property name, value) or (_END_NODE, "", b"").
_Token = tuple[int, str, bytes]


def encode_device_tree(compatible: Sequence[str], properties: Mapping[str, bytes] | None = None) -> bytes:
    """Returns a version 17 FDT blob whose root node has the compatible strings and other properties.

    An empty compatible omits the property.
    """
    values = dict(properties or {})
    if compatible:
        values = {"compatible": encode_strings(compatible), **values}
    tokens = [(_BEGIN_NODE, "", b""), *((_PROP, name, value) for name, value in values.items()), (_END_NODE, "", b"")]
    return _encode(_EMPTY_MEMORY_RESERVATION_MAP, 0, tokens)


def with_root_properties(blob: bytes, properties: Mapping[str, bytes]) -> bytes:
    """Returns a compact copy of an FDT blob whose root node has properties, replacing those of the same name."""
    memory_reservation_map, boot_cpu, tokens = _decode(blob)
    # The root's properties follow its BEGIN_NODE token and precede its first child node or its end.
    end = next(index for index, token in enumerate(tokens[1:], 1) if token[0] != _PROP)
    root = {name: value for _, name, value in tokens[1:end]} | dict(properties)
    edited = [tokens[0], *((_PROP, name, value) for name, value in root.items()), *tokens[end:]]
    return _encode(memory_reservation_map, boot_cpu, edited)


def encode_strings(values: Sequence[str]) -> bytes:
    """Returns a device tree string list property value."""
    return b"".join(value.encode("ascii") + b"\0" for value in values)


def _decode(blob: bytes) -> tuple[bytes, int, list[_Token]]:
    header = _HEADER.unpack_from(blob)
    if header[0] != _FDT_MAGIC:
        raise ValueError("not a flattened device tree")
    structure_offset, strings_offset, reservations_offset, boot_cpu = header[2], header[3], header[4], header[7]
    reservations_end = reservations_offset
    while blob[reservations_end : reservations_end + 16] != bytes(16):
        reservations_end += 16
    tokens: list[_Token] = []
    offset = structure_offset
    while True:
        (kind,) = struct.unpack_from(">I", blob, offset)
        offset += 4
        if kind == _END:
            return blob[reservations_offset : reservations_end + 16], boot_cpu, tokens
        if kind == _BEGIN_NODE:
            name, offset = _string(blob, offset)
            tokens.append((kind, name, b""))
            offset = _aligned(offset)
        elif kind == _PROP:
            length, name_offset = struct.unpack_from(">II", blob, offset)
            offset += 8
            tokens.append((kind, _string(blob, strings_offset + name_offset)[0], blob[offset : offset + length]))
            offset = _aligned(offset + length)
        elif kind == _END_NODE:
            tokens.append((kind, "", b""))
        elif kind != _NOP:
            raise ValueError("unknown flattened device tree token {}".format(kind))


def _encode(memory_reservation_map: bytes, boot_cpu: int, tokens: Sequence[_Token]) -> bytes:
    strings: dict[str, int] = {}
    structure = b""
    for kind, name, value in tokens:
        structure += struct.pack(">I", kind)
        if kind == _BEGIN_NODE:
            structure += _padded(name.encode("ascii") + b"\0")
        elif kind == _PROP:
            name_offset = strings.setdefault(name, sum(len(known) + 1 for known in strings))
            structure += struct.pack(">II", len(value), name_offset) + _padded(value)
    structure += struct.pack(">I", _END)
    string_block = b"".join(name.encode("ascii") + b"\0" for name in strings)
    structure_offset = _HEADER.size + len(memory_reservation_map)
    strings_offset = structure_offset + len(structure)
    size = strings_offset + len(string_block)
    header = _HEADER.pack(
        _FDT_MAGIC,
        size,
        structure_offset,
        strings_offset,
        _HEADER.size,
        17,
        16,
        boot_cpu,
        len(string_block),
        len(structure),
    )
    return header + memory_reservation_map + structure + string_block


def _string(blob: bytes, offset: int) -> tuple[str, int]:
    end = blob.index(b"\0", offset)
    return blob[offset:end].decode("ascii"), end + 1


def _aligned(offset: int) -> int:
    return (offset + 3) & ~3


def _padded(value: bytes) -> bytes:
    return value + bytes(-len(value) % 4)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, help="Blob to copy with the properties, instead of a new one.")
    parser.add_argument("--compatible", action="append", default=[])
    parser.add_argument("--string-property", action="append", default=[], metavar="NAME=VALUE")
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    properties = {
        name: encode_strings([value]) for name, value in (item.split("=", 1) for item in arguments.string_property)
    }
    if arguments.input is None:
        blob = encode_device_tree(arguments.compatible, properties)
    else:
        if arguments.compatible:
            properties["compatible"] = encode_strings(arguments.compatible)
        blob = with_root_properties(arguments.input.read_bytes(), properties)
    arguments.output.write_bytes(blob)


if __name__ == "__main__":
    main()
