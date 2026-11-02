import pathlib
import struct
import sys
import unittest

_PT_DYNAMIC = 2
_PT_INTERP = 3


class BootstrapStaticTest(unittest.TestCase):
    def test_bootstrap_binaries_are_fully_static(self):
        for argument in sys.argv[1:]:
            with self.subTest(executable=argument):
                data = pathlib.Path(argument).resolve().read_bytes()
                self.assertEqual(data[:4], b"\x7fELF")
                header = struct.unpack_from("<16sHHIQQQIHHHHHH", data)
                offset, size, count = header[5], header[9], header[10]
                segment_types = {struct.unpack_from("<I", data, offset + index * size)[0] for index in range(count)}
                self.assertNotIn(_PT_INTERP, segment_types)
                self.assertNotIn(_PT_DYNAMIC, segment_types)


if __name__ == "__main__":
    unittest.main(argv=sys.argv[:1])
