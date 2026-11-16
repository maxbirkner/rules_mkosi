"""Encodes small flattened device tree (FDT) blobs and reads their nodes, for tests that need exact or malformed blobs.

Fixtures that only need a valid device tree compile a source with the devicetree rule instead.
"""

import struct
from collections.abc import Mapping, Sequence

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
    return _encode(tokens)


def read_nodes(blob: bytes) -> dict[str, dict[str, bytes]]:
    """Returns the properties of every node of an FDT blob, keyed by node path such as / or /soc/display@1000."""
    nodes: dict[str, dict[str, bytes]] = {}
    path: list[str] = []
    for kind, name, value in _decode(blob):
        if kind == _BEGIN_NODE:
            path.append(name)
            nodes["/" + "/".join(path[1:])] = {}
        elif kind == _PROP:
            nodes["/" + "/".join(path[1:])][name] = value
        else:
            path.pop()
    return nodes


def encode_strings(values: Sequence[str]) -> bytes:
    """Returns a device tree string list property value."""
    return b"".join(value.encode("ascii") + b"\0" for value in values)


def _decode(blob: bytes) -> list[_Token]:
    header = _HEADER.unpack_from(blob)
    if header[0] != _FDT_MAGIC:
        raise ValueError("not a flattened device tree")
    structure_offset, strings_offset = header[2], header[3]
    tokens: list[_Token] = []
    offset = structure_offset
    while True:
        (kind,) = struct.unpack_from(">I", blob, offset)
        offset += 4
        if kind == _END:
            return tokens
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


def _encode(tokens: Sequence[_Token]) -> bytes:
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
    structure_offset = _HEADER.size + len(_EMPTY_MEMORY_RESERVATION_MAP)
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
        0,
        len(string_block),
        len(structure),
    )
    return header + _EMPTY_MEMORY_RESERVATION_MAP + structure + string_block


def _string(blob: bytes, offset: int) -> tuple[str, int]:
    end = blob.index(b"\0", offset)
    return blob[offset:end].decode("ascii"), end + 1


def _aligned(offset: int) -> int:
    return (offset + 3) & ~3


def _padded(value: bytes) -> bytes:
    return value + bytes(-len(value) % 4)
