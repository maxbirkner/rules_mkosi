import importlib.util
import pathlib
import unittest


SPEC = importlib.util.spec_from_file_location(
    "sysupdate_ab",
    pathlib.Path(__file__).parents[1] / "private" / "sysupdate_ab.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def slots():
    mib = 1024 * 1024
    return {
        "a": {
            "version": "1.0.0",
            "root": {"offset": 1 * mib, "size": 8 * mib},
            "verity": {"offset": 9 * mib, "size": 2 * mib},
        },
        "b": {
            "version": "2.0.0",
            "root": {"offset": 11 * mib, "size": 8 * mib},
            "verity": {"offset": 19 * mib, "size": 2 * mib},
        },
    }


class SysupdateAbTest(unittest.TestCase):
    def test_projects_symmetric_layout_and_boot_counting(self):
        result = MODULE.project(slots(), 3)
        self.assertEqual("uefi", result["firmware"])
        self.assertEqual(3, result["boot"]["attempts"])
        self.assertEqual("systemd-bless-boot.service", result["boot"]["success_commit"])
        self.assertEqual(
            MODULE.ROOT_TYPE,
            result["slots"]["a"]["partitions"][0]["type_guid"],
        )

    def test_rejects_asymmetric_root_slots(self):
        value = slots()
        value["b"]["root"]["size"] += 1024 * 1024
        with self.assertRaisesRegex(ValueError, "root slots are not symmetric"):
            MODULE.project(value, 3)

    def test_rejects_overlap(self):
        value = slots()
        value["b"]["root"]["offset"] = 10 * 1024 * 1024
        with self.assertRaisesRegex(ValueError, "overlaps"):
            MODULE.project(value, 3)


if __name__ == "__main__":
    unittest.main()
