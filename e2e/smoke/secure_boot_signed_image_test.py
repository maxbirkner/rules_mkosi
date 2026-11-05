"""Checks the ESP changes that secure_boot_signed_image recorded for the signed A/B release disk image."""

import hashlib
import json
import sys
import unittest
from pathlib import Path


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _one(paths, suffix):
    matches = [path for path in paths if path.endswith(suffix)]
    if len(matches) != 1:
        raise AssertionError("expected one {} in {}".format(suffix, paths))
    return matches[0]


class SignedImageTest(unittest.TestCase):
    def test_boot_binaries_are_replaced_by_their_signed_imports(self):
        replaced = {entry["esp_path"]: entry["signed_sha256"] for entry in METADATA["replaced"]}
        boot_loader = _sha256(_one(SYSTEMD_BOOT, ".signed.efi"))
        self.assertEqual(replaced.pop("EFI/systemd/systemd-bootx64.efi"), boot_loader)
        self.assertEqual(replaced.pop("EFI/BOOT/BOOTX64.EFI"), boot_loader)
        [(uki_path, uki)] = replaced.items()
        self.assertRegex(uki_path, r"^EFI/Linux/rules-mkosi-ab_1(\+[0-9-]+)?\.efi$")
        self.assertEqual(uki, _sha256(_one(UKI, ".signed.efi")))

    def test_keys_and_enrollment_mode_are_added(self):
        self.assertEqual(METADATA["secure_boot_enroll"], "force")
        keys = {name: _sha256(_one(SIGNER, "/{}.auth".format(name))) for name in ("PK", "KEK", "db")}
        self.assertEqual(METADATA["auto_enroll_keys"], keys)
        for path in ("loader/keys/auto/PK.auth", "loader/keys/auto/KEK.auth", "loader/keys/auto/db.auth"):
            self.assertIn(path, METADATA["changed_esp_paths"])
        self.assertIn("loader/loader.conf", [path.lower() for path in METADATA["changed_esp_paths"]])

    def test_disk_image_keeps_the_unsigned_image_size(self):
        self.assertGreater(Path(_one(IMAGE, ".raw")).stat().st_size, 1 << 30)


if __name__ == "__main__":
    IMAGE, SYSTEMD_BOOT, UKI, SIGNER = (group.split() for group in " ".join(sys.argv[1:]).split(" -- "))
    METADATA = json.loads(Path(_one(IMAGE, ".secure-boot-image.json")).read_text())
    unittest.main(argv=[sys.argv[0]])
