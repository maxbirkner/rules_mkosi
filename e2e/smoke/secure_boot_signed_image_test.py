"""Checks the ESP changes that secure_boot_signed_image recorded for the signed A/B release disk image."""

import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import rules_mkosi_esp_manifest

ESP_TYPE_GUID = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
ESP_MANIFEST = "loader/rules_mkosi-secure-boot.json"


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _certificate_sha256(path):
    """Returns the SHA-256 of the DER encoding of the PEM certificate at path."""
    body = "".join(line for line in Path(path).read_text().splitlines() if not line.startswith("-----"))
    return hashlib.sha256(base64.b64decode(body)).hexdigest()


def _read_esp_file(image, partition_metadata, launcher, esp_path):
    """Returns the bytes of esp_path on the ESP of image, read with the pinned mtools as install tooling could."""
    partitions = json.loads(Path(partition_metadata).read_text())["partitions"]
    [esp] = [partition for partition in partitions if partition["type_guid"] == ESP_TYPE_GUID]
    # The launcher needs a new scratch directory for every call.
    scratch = os.path.join(tempfile.mkdtemp(dir=os.environ["TEST_TMPDIR"]), "mtype")
    environment = dict(os.environ, MKOSI_DEBIAN_TOOLS_SCRATCH=scratch)
    image_path = "/inputs/image.raw@@{}".format(esp["start_bytes"])
    command = ["/usr/bin/mtype", "-i", image_path, "::/" + esp_path]
    result = subprocess.run(
        [launcher, "--ro-bind", "{}:/inputs/image.raw".format(Path(image).resolve()), *command],
        capture_output=True,
        check=False,
        env=environment,
    )
    if result.returncode:
        raise AssertionError("mtype {} failed: {}".format(esp_path, result.stderr.decode(errors="replace")))
    return result.stdout


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
        self.assertEqual({key["variable"]: key["sha256"] for key in METADATA["auto_enroll_keys"]}, keys)
        for path in ("loader/keys/auto/PK.auth", "loader/keys/auto/KEK.auth", "loader/keys/auto/db.auth"):
            self.assertIn(path, METADATA["changed_esp_paths"])
        self.assertIn("loader/loader.conf", [path.lower() for path in METADATA["changed_esp_paths"]])

    def test_disk_image_keeps_the_unsigned_image_size(self):
        self.assertGreater(Path(_one(IMAGE, ".raw")).stat().st_size, 1 << 30)

    def test_raw_image_output_group_holds_only_the_disk_image(self):
        self.assertEqual(RAW_IMAGE, [_one(IMAGE, ".raw")])

    def test_esp_manifest_names_the_enrolled_db_certificate_and_the_signers(self):
        [image] = RAW_IMAGE
        manifest = json.loads(_read_esp_file(image, PARTITION_METADATA, LAUNCHER, ESP_MANIFEST))
        self.assertEqual(manifest["format_version"], "mkosi-secure-boot-esp-manifest-v1")
        self.assertEqual(METADATA["esp_manifest"], ESP_MANIFEST)
        for field in ("auto_enroll_keys", "replaced", "secure_boot_enroll"):
            self.assertEqual(manifest[field], METADATA[field], field)
        db = _certificate_sha256(_one(SIGNER, ".certificate.pem"))
        keys = {key["variable"]: key for key in manifest["auto_enroll_keys"]}
        self.assertEqual(keys["db"]["x509_sha256"], [db])
        self.assertEqual(keys["db"]["esp_path"], "loader/keys/auto/db.auth")
        self.assertEqual({entry["signer_sha256"] for entry in manifest["replaced"]}, {db})

    def test_esp_manifest_reader_reads_what_mtools_reads(self):
        [image] = RAW_IMAGE
        expected = json.loads(_read_esp_file(image, PARTITION_METADATA, LAUNCHER, ESP_MANIFEST))
        self.assertEqual(rules_mkosi_esp_manifest.read_esp_manifest(image), expected)
        printed = subprocess.run([ESP_MANIFEST_TOOL, image], capture_output=True, check=True)
        self.assertEqual(json.loads(printed.stdout), expected)
        listed = subprocess.run([ESP_MANIFEST_TOOL, "--list", image], capture_output=True, check=True)
        self.assertLessEqual(set(METADATA["changed_esp_paths"]), set(listed.stdout.decode().splitlines()))
        partitions = json.loads(Path(PARTITION_METADATA).read_text())["partitions"]
        [esp] = [partition for partition in partitions if partition["type_guid"] == ESP_TYPE_GUID]
        self.assertEqual(rules_mkosi_esp_manifest.find_esp(image)[:2], (esp["start_bytes"], esp["size_bytes"]))


if __name__ == "__main__":
    IMAGE, SYSTEMD_BOOT, UKI, SIGNER, RAW_IMAGE, TOOLS = (
        group.split() for group in " ".join(sys.argv[1:]).split(" -- ")
    )
    PARTITION_METADATA, LAUNCHER, ESP_MANIFEST_TOOL = TOOLS
    METADATA = json.loads(Path(_one(IMAGE, ".secure-boot-image.json")).read_text())
    unittest.main(argv=[sys.argv[0]])
