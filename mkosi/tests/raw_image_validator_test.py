import ctypes
import os
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import raw_image_validator
import raw_image_validator_cases


class RawImageValidatorTest(raw_image_validator_cases.RawImageValidatorCases, unittest.TestCase):
    def test_fabricated_sparse_pseudo_gpt_has_no_allocated_root(self):
        image = raw_image_validator_cases.fake_ext4_root(raw_image_validator_cases.gpt_image(), include_data=False)
        libc = ctypes.CDLL(None, use_errno=True)
        libc.memfd_create.argtypes = [ctypes.c_char_p, ctypes.c_uint]
        libc.memfd_create.restype = ctypes.c_int
        fd = libc.memfd_create(b"rules-mkosi-sparse-gpt", 0)
        if fd < 0:
            raise OSError(ctypes.get_errno(), "memfd_create")
        try:
            os.ftruncate(fd, len(image))
            partition_offset = 34 * 512
            block_size = 4096
            ranges = [
                (0, 34 * 512),
                ((4096 - 33) * 512, len(image)),
                (partition_offset + 1024, partition_offset + 2048),
                (partition_offset + block_size, partition_offset + 5 * block_size),
                (partition_offset + 4 * block_size + 256, partition_offset + 4 * block_size + 512),
            ]
            for start, end in ranges:
                os.pwrite(fd, image[start:end], start)
            with os.fdopen(fd, "r+b") as sparse:
                fd = -1
                with self.assertRaisesRegex(AssertionError, "not physically allocated"):
                    raw_image_validator._validate(
                        sparse,
                        len(image),
                    )
        finally:
            if fd >= 0:
                os.close(fd)


if __name__ == "__main__":
    unittest.main()
