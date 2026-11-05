"""Tests the Secure Boot signed disk image tool and the .auth parser with real FAT images and the Debian tools."""

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import secure_boot_fixtures

SECURE_BOOT_TOOL, IMAGE_TOOL, EFI_AUTH, DEBIAN_TOOLS = sys.argv[1:5]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SECURE_BOOT = _load("secure_boot", SECURE_BOOT_TOOL)
efi_auth = _load("efi_auth", EFI_AUTH)
run_tool = SECURE_BOOT.launcher_tool.run_tool
# Relative, so that the Debian tools launcher maps the paths into its namespace.
WORK = Path("secure-boot-image-work")
BOOT_LOADER = "EFI/systemd/systemd-bootx64.efi"
FALLBACK = "EFI/BOOT/BOOTX64.EFI"
UKI = "EFI/Linux/os_1+3.efi"


def _python(*arguments, check=True):
    result = subprocess.run([sys.executable, *map(str, arguments)], capture_output=True, text=True)
    if check and result.returncode:
        raise AssertionError(result.stderr)
    return result


def _sign(name, pairs):
    """Signs (unsigned, signed) pairs with new ephemeral keys; returns the certificate and the auto-enroll directory."""
    certificate = WORK / (name + ".pem")
    keys = WORK / (name + "-keys")
    arguments = ["--openssl", DEBIAN_TOOLS, "--sbsign", DEBIAN_TOOLS, "--certificate", certificate]
    arguments += ["--scratch", WORK / (name + "-scratch"), "--auto-enroll-dir", keys]
    arguments += [value for pair in pairs for value in ("--sign", *pair)]
    _python(SECURE_BOOT_TOOL, "ephemeral-fixture", *arguments)
    return certificate, keys


def _request(name, unsigned, certificate, esp_path=""):
    """Returns the request and normalized certificate of a signing request for unsigned."""
    request = WORK / (name + ".json")
    normalized = WORK / (name + ".der")
    arguments = [
        "--openssl",
        DEBIAN_TOOLS,
        "--unsigned",
        unsigned,
        "--esp-path",
        esp_path,
        "--certificate",
        certificate,
    ]
    arguments += ["--certificate-output", normalized, "--algorithm", "authenticode-sha256", "--output", request]
    _python(SECURE_BOOT_TOOL, "request", *arguments, "--digest-output", WORK / (name + ".sha256"))
    return request, normalized


def _esp_tree(disk, destination):
    """Copies the ESP files of disk to destination and returns {lowercase ESP path: bytes}."""
    esp = WORK / "check-esp.img"
    data = disk.read_bytes()[secure_boot_fixtures.ESP_OFFSET : -len(secure_boot_fixtures.TRAILER)]
    esp.write_bytes(data)
    shutil.rmtree(destination, ignore_errors=True)
    destination.mkdir()
    run_tool(DEBIAN_TOOLS, "/usr/bin/mcopy", "-s", "-n", "-i", esp, "::*", destination)
    return {
        str(path.relative_to(destination)).lower(): path.read_bytes()
        for path in destination.rglob("*")
        if path.is_file()
    }


class Fixture:
    """Two PE binaries on an ESP, signed with one hierarchy; a second hierarchy's keys do not trust the signer."""

    def __init__(self):
        shutil.rmtree(WORK, ignore_errors=True)
        WORK.mkdir()
        self.boot = WORK / "boot.efi"
        self.boot.write_bytes(secure_boot_fixtures.minimal_pe(b"systemd-boot"))
        self.uki = WORK / "uki.efi"
        self.uki.write_bytes(secure_boot_fixtures.minimal_pe(b"unified kernel image"))
        self.absent = WORK / "absent.efi"
        self.absent.write_bytes(secure_boot_fixtures.minimal_pe(b"not on the ESP"))
        self.signed = {path: WORK / ("signed-" + path.name) for path in (self.boot, self.uki, self.absent)}
        certificate, self.keys = _sign("trusted", self.signed.items())
        _, self.untrusted_keys = _sign("untrusted", [(self.boot, WORK / "untrusted.efi")])
        self.requests = {
            path: _request(path.stem, path, certificate, BOOT_LOADER if path == self.boot else "")
            for path in self.signed
        }
        files = {FALLBACK: self.boot, BOOT_LOADER: self.boot, UKI: self.uki, "loader/loader.conf": b"timeout 3\n"}
        files["loader/loader.conf"] += b"secure-boot-enroll off\n"
        self.disk, self.metadata = secure_boot_fixtures.disk_with_esp(run_tool, DEBIAN_TOOLS, WORK, files)

    def sign_image(self, name, binaries, keys=None, mode="force", disk=None):
        output = WORK / (name + ".raw")
        image, metadata = disk or (self.disk, self.metadata)
        arguments = ["--tools", DEBIAN_TOOLS, "--image", image, "--partition-metadata", metadata]
        for binary in binaries:
            arguments += ["--signed", self.signed[binary], *self.requests[binary]]
        for key in sorted(keys.iterdir()) if keys else []:
            arguments += ["--auto-enroll-key", key]
        arguments += ["--secure-boot-enroll", mode, "--scratch", WORK / (name + "-scratch")]
        result = _python(IMAGE_TOOL, *arguments, "--output", output, "--metadata", WORK / (name + ".json"), check=False)
        return result, output


class SignedImageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = Fixture()

    def test_esp_holds_signed_binaries_keys_and_enroll_mode_and_nothing_else_changes(self):
        result, output = self.fixture.sign_image("signed", [self.fixture.boot, self.fixture.uki], self.fixture.keys)
        self.assertEqual(result.returncode, 0, result.stderr)
        files = _esp_tree(output, WORK / "signed-tree")
        signed_boot = self.fixture.signed[self.fixture.boot].read_bytes()
        self.assertEqual(files[FALLBACK.lower()], signed_boot)
        self.assertEqual(files[BOOT_LOADER.lower()], signed_boot)
        self.assertEqual(files[UKI.lower()], self.fixture.signed[self.fixture.uki].read_bytes())
        for name in ("PK", "KEK", "db"):
            key = (self.fixture.keys / (name + ".auth")).read_bytes()
            self.assertEqual(files["loader/keys/auto/{}.auth".format(name.lower())], key)
        self.assertEqual(files["loader/loader.conf"], b"timeout 3\nsecure-boot-enroll force\n")
        original = self.fixture.disk.read_bytes()
        data = output.read_bytes()
        self.assertEqual(len(data), len(original))
        self.assertEqual(data[: secure_boot_fixtures.ESP_OFFSET], original[: secure_boot_fixtures.ESP_OFFSET])
        self.assertEqual(data[-len(secure_boot_fixtures.TRAILER) :], secure_boot_fixtures.TRAILER)
        metadata = json.loads((WORK / "signed.json").read_text())
        self.assertEqual(metadata["secure_boot_enroll"], "force")
        self.assertEqual(
            sorted(entry["esp_path"] for entry in metadata["replaced"]), sorted([FALLBACK, BOOT_LOADER, UKI])
        )
        _, again = self.fixture.sign_image("again", [self.fixture.uki, self.fixture.boot], self.fixture.keys)
        self.assertEqual(hashlib.sha256(again.read_bytes()).digest(), hashlib.sha256(data).digest())

    def test_without_keys_only_binaries_change(self):
        result, output = self.fixture.sign_image("binaries-only", [self.fixture.boot, self.fixture.uki], mode="if-safe")
        self.assertEqual(result.returncode, 0, result.stderr)
        files = _esp_tree(output, WORK / "binaries-only-tree")
        self.assertEqual(files["loader/loader.conf"], b"timeout 3\nsecure-boot-enroll off\n")
        self.assertFalse(any(path.startswith("loader/keys") for path in files))

    def test_inputs_that_would_not_boot_are_rejected(self):
        fixture = self.fixture
        missing_pk = WORK / "missing-pk"
        missing_pk.mkdir(exist_ok=True)
        for name in ("KEK", "db"):
            shutil.copyfile(fixture.keys / (name + ".auth"), missing_pk / (name + ".auth"))
        truncated = WORK / "truncated"
        shutil.copytree(fixture.keys, truncated, dirs_exist_ok=True)
        (truncated / "db.auth").write_bytes((fixture.keys / "db.auth").read_bytes()[:-1])
        for name, binaries, keys, error in [
            (
                "unsigned-left",
                [fixture.boot],
                fixture.keys,
                "unsigned PE/COFF binaries that Secure Boot firmware refuses",
            ),
            ("absent", [fixture.boot, fixture.uki, fixture.absent], fixture.keys, "holds no unsigned copy"),
            ("untrusted", [fixture.boot, fixture.uki], fixture.untrusted_keys, "db.auth does not trust"),
            ("missing-pk", [fixture.boot, fixture.uki], missing_pk, "auto-enrollment needs PK.auth"),
            ("truncated", [fixture.boot, fixture.uki], truncated, "db.auth: EFI_SIGNATURE_LIST sizes are inconsistent"),
        ]:
            with self.subTest(name):
                result, _ = fixture.sign_image(name, binaries, keys)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(error, result.stderr)

    def test_startable_already_signed_binaries_must_be_trusted_by_db_when_keys_are_enrolled(self):
        fixture = self.fixture
        boot_files = {FALLBACK: fixture.boot, BOOT_LOADER: fixture.boot, UKI: fixture.uki}
        untrusted = WORK / "untrusted.efi"
        extra = {"EFI/tools/extra.efi": untrusted}
        kernel = {"vmlinuz-6": untrusted}
        type1 = kernel | {"loader/entries/os.conf": b"title OS\nlinux /vmlinuz-6\n"}
        type1_tab = kernel | {"loader/entries/os.conf": b"title OS\nlinux\t/vmlinuz-6\n"}
        type1_quoted = kernel | {"loader/entries/os.conf": b'title OS\nlinux "/vmlinuz-6"\n'}
        for name, files, keys, untrusted_path in [
            ("trusted-pre-signed", {"EFI/tools/extra.efi": fixture.signed[fixture.absent]}, fixture.keys, None),
            ("untrusted-pre-signed", extra, fixture.keys, "EFI/tools/extra.efi"),
            ("untrusted-pre-signed-without-keys", extra, None, None),
            ("untrusted-kernel-that-nothing-starts", kernel, fixture.keys, None),
            ("untrusted-kernel-of-a-boot-entry", type1, fixture.keys, "vmlinuz-6"),
            ("untrusted-kernel-of-a-tab-separated-boot-entry", type1_tab, fixture.keys, "vmlinuz-6"),
            ("untrusted-kernel-of-a-quoted-boot-entry", type1_quoted, fixture.keys, "vmlinuz-6"),
        ]:
            with self.subTest(name):
                work = WORK / (name + "-disk")
                work.mkdir(exist_ok=True)
                disk = secure_boot_fixtures.disk_with_esp(run_tool, DEBIAN_TOOLS, work, boot_files | files)
                mode = "force" if keys else "if-safe"
                result, _ = fixture.sign_image(name, [fixture.boot, fixture.uki], keys, mode, disk)
                if untrusted_path:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("db.auth does not trust the certificate that signed " + untrusted_path, result.stderr)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)


class AuthFileTest(unittest.TestCase):
    def setUp(self):
        self.certificate = bytes.fromhex("3003020100")
        self.data = efi_auth.signature_list(self.certificate, efi_auth.EFI_GLOBAL_VARIABLE)
        self.auth = efi_auth.auth_file(efi_auth.efi_time(2026), b"\x30\x00", self.data)

    def test_built_file_parses(self):
        signed_data, lists = efi_auth.parse_auth("PK", self.auth)
        self.assertEqual(signed_data, b"\x30\x00")
        self.assertEqual(efi_auth.x509_certificates(lists), [self.certificate])

    def test_malformed_files_are_rejected(self):
        two_certificates = efi_auth.auth_file(efi_auth.efi_time(2026), b"\x30\x00", self.data + self.data)
        for name, variable, data in [
            ("unknown variable", "MokList", self.auth),
            ("nanoseconds", "PK", self.auth[:8] + b"\x01" + self.auth[9:]),
            ("revision", "PK", self.auth[:20] + b"\x00\x01" + self.auth[22:]),
            ("certificate type", "PK", self.auth[:24] + bytes(16) + self.auth[40:]),
            ("length", "PK", self.auth[:16] + b"\xff\xff\x00\x00" + self.auth[20:]),
            ("two PKs", "PK", two_certificates),
            ("truncated list", "db", self.auth[:-1]),
            ("no X.509 in db", "db", efi_auth.auth_file(efi_auth.efi_time(2026), b"\x30\x00", b"")),
        ]:
            with self.subTest(name), self.assertRaises(ValueError):
                efi_auth.parse_auth(variable, data)

    def test_signed_payload_binds_name_guid_attributes_time_and_data(self):
        payload = efi_auth.signed_payload("db", efi_auth.efi_time(2026), self.data)
        self.assertTrue(payload.startswith("db".encode("utf-16-le") + efi_auth.EFI_IMAGE_SECURITY_DATABASE.bytes_le))
        self.assertTrue(payload.endswith(efi_auth.efi_time(2026) + self.data))


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
