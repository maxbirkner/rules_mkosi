"""Unit tests for normalized GPT partition metadata."""

import copy
import unittest

from mkosi.private import partition_metadata


def table():
    return {
        "partitiontable": {
            "label": "gpt",
            "sectorsize": 512,
            "id": "variable-disk-id",
            "partitions": [
                {
                    "node": "/dev/loop7p1",
                    "start": 2048,
                    "size": 4096,
                    "type": partition_metadata.ROOT_X86_64.upper(),
                    "uuid": "variable-partition-id",
                    "name": "root-x86-64",
                }
            ],
        }
    }


class ProjectionTest(unittest.TestCase):
    def test_normalizes_variable_identifiers(self):
        projected = partition_metadata.project(table())
        self.assertNotIn("id", projected)
        self.assertNotIn("uuid", projected["partitions"][0])
        self.assertEqual(partition_metadata.ROOT_X86_64, projected["partitions"][0]["type_guid"])

    def test_missing_partition(self):
        value = table()
        value["partitiontable"]["partitions"] = []
        with self.assertRaisesRegex(ValueError, "exactly one"):
            partition_metadata.project(value)

    def test_overlap_and_reorder(self):
        value = table()
        second = copy.deepcopy(value["partitiontable"]["partitions"][0])
        second["start"] = 2048
        value["partitiontable"]["partitions"].append(second)
        with self.assertRaisesRegex(ValueError, "overlaps or is out of order"):
            partition_metadata.project(value)

    def test_misalignment(self):
        value = table()
        value["partitiontable"]["partitions"][0]["start"] = 2049
        with self.assertRaisesRegex(ValueError, "not 1 MiB aligned"):
            partition_metadata.project(value)

    def test_wrong_type(self):
        value = table()
        value["partitiontable"]["partitions"][0]["type"] = "0fc63daf-8483-4772-8e79-3d69d8477de4"
        with self.assertRaisesRegex(ValueError, "exactly one"):
            partition_metadata.project(value)


if __name__ == "__main__":
    unittest.main()
