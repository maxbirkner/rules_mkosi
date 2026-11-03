import unittest

import raw_image_validator
import raw_image_validator_cases


class RawImageValidatorTest(raw_image_validator_cases.RawImageValidatorCases, unittest.TestCase):
    def test_fabricated_sparse_pseudo_gpt_has_no_allocated_root(self):
        image = raw_image_validator_cases.fake_ext4_root(raw_image_validator_cases.gpt_image(), include_data=False)
        partition_offset = 34 * 512
        block_size = 4096
        physical_ranges = [
            (0, 34 * 512),
            ((4096 - 33) * 512, len(image)),
            (partition_offset + 1024, partition_offset + 2048),
            (partition_offset + block_size, partition_offset + 5 * block_size),
        ]
        with self.assertRaisesRegex(AssertionError, "not physically allocated"):
            raw_image_validator.validate_bytes(image, physical_ranges=physical_ranges)


if __name__ == "__main__":
    unittest.main()
