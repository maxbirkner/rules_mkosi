"""Checks that bootstrap executables are fully static ELF executables of one machine type."""

import pathlib
import struct
import sys
import unittest

_MACHINES = {"aarch64": 183, "x86_64": 62}
_PT_DYNAMIC = 2
_PT_INTERP = 3


def read_elf_header(data: bytes) -> tuple[int, set[int]]:
    """Returns the machine type and the program header types of a 64-bit little-endian ELF executable."""
    if data[:4] != b"\x7fELF" or data[4] != 2 or data[5] != 1:
        raise ValueError("not a 64-bit little-endian ELF file")
    header = struct.unpack_from("<16sHHIQQQIHHHHHH", data)
    machine, offset, size, count = header[2], header[5], header[9], header[10]
    return machine, {struct.unpack_from("<I", data, offset + index * size)[0] for index in range(count)}


class BootstrapElfTest(unittest.TestCase):
    def test_executables_are_static_for_the_machine(self) -> None:
        machine = _MACHINES[sys.argv[1]]
        for argument in sys.argv[2:]:
            with self.subTest(executable=argument):
                found, segment_types = read_elf_header(pathlib.Path(argument).resolve().read_bytes())
                self.assertEqual(machine, found)
                self.assertNotIn(_PT_INTERP, segment_types)
                self.assertNotIn(_PT_DYNAMIC, segment_types)


if __name__ == "__main__":
    unittest.main(argv=sys.argv[:1])
