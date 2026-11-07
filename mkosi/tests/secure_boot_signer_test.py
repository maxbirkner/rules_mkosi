"""Tests of the reference signer for secure_boot_signing_manifest."""

import hashlib
import json
import os
import pathlib
import runpy
import shutil
import subprocess
import sys
import time
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import secure_boot_fixtures

SIGNER_TOOL, DEBIAN_TOOLS = (str(pathlib.Path(path).absolute()) for path in sys.argv[1:3])
WORK = pathlib.Path("secure-boot-signer-work")
BIN = "bazel-out/k8-fastbuild/bin"


SIGNER = SimpleNamespace(**runpy.run_path(SIGNER_TOOL))
SECURE_BOOT = SIGNER.secure_boot


def create_key_pair(name):
    """Returns the paths of a new throwaway RSA key and its self-signed certificate."""
    key, certificate = WORK / (name + ".key"), WORK / (name + ".pem")
    SECURE_BOOT.run_tool(
        DEBIAN_TOOLS,
        "/usr/bin/openssl",
        *("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=signer test " + name),
        *("-keyout", key, "-out", certificate),
        capture=True,
    )
    return key, certificate


def openssl_signing_times(signed):
    """Returns the signingTime values that OpenSSL prints for the Authenticode signature of a signed binary."""
    pkcs7 = WORK / (signed.name + ".p7")
    pkcs7.write_bytes(SECURE_BOOT.embedded_authenticode(signed.read_bytes()))
    try:
        printed = SECURE_BOOT.run_tool(
            DEBIAN_TOOLS, "/usr/bin/openssl", "pkcs7", "-print", "-noout", "-inform", "DER", "-in", pkcs7, capture=True
        ).stdout.decode()
    except subprocess.CalledProcessError as error:
        raise AssertionError(error.stderr.decode()) from error
    lines = printed.splitlines()
    return [lines[index + 2].strip() for index, line in enumerate(lines) if "object: signingTime" in line]


def openssl_time(seconds):
    """Returns how OpenSSL prints a UTCTime of Unix time seconds."""
    return "UTCTIME:" + time.strftime("%b %e %H:%M:%S %Y GMT", time.gmtime(seconds))


def create_request(name, esp_path, certificate):
    """Writes the unsigned binary and request files of name below the bin directory and returns its manifest entry."""
    directory = WORK / "template" / BIN
    directory.mkdir(parents=True, exist_ok=True)
    files = {suffix: directory / (name + suffix) for suffix in (".efi", ".json", ".sha256", ".der")}
    files[".efi"].write_bytes(secure_boot_fixtures.minimal_pe(name.encode()))
    SECURE_BOOT.create_request(
        SimpleNamespace(
            algorithm="authenticode-sha256",
            certificate=certificate,
            certificate_output=files[".der"],
            digest_output=files[".sha256"],
            esp_path=esp_path,
            openssl=DEBIAN_TOOLS,
            output=files[".json"],
            unsigned=files[".efi"],
        )
    )
    return {
        "certificate": "{}/{}.der".format(BIN, name),
        "context": "uefi-secure-boot-esp-file" if esp_path else "uefi-secure-boot-uki",
        "esp_path": esp_path,
        "label": "//:" + name,
        "request": "{}/{}.json".format(BIN, name),
        "request_digest": "{}/{}.sha256".format(BIN, name),
        "signed_name": name + ".signed.efi",
        "unsigned_binary": "{}/{}.efi".format(BIN, name),
    }


class SecureBootSignerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        shutil.rmtree(WORK, ignore_errors=True)
        WORK.mkdir()
        cls.key, cls.certificate = create_key_pair("expected")
        cls.other_key, cls.other_certificate = create_key_pair("other")
        cls.entries = [
            create_request("uki", "", cls.certificate),
            create_request("boot", "EFI/BOOT/BOOTX64.EFI", cls.certificate),
        ]

    def setUp(self):
        self.execroot = WORK / self._testMethodName
        shutil.rmtree(self.execroot, ignore_errors=True)
        shutil.copytree(WORK / "template", self.execroot)
        self.output = WORK / (self._testMethodName + "-signed")
        self.manifest = self.write_manifest(self.entries)

    def write_manifest(self, entries, format_version="mkosi-secure-boot-signing-manifest-v1"):
        manifest = self.execroot / BIN / "signing.secure-boot-signing-manifest.json"
        manifest.write_text(json.dumps({"format_version": format_version, "requests": entries}))
        return manifest

    def run_signer(self, *arguments, key=None, certificate=None, output=None, env=None):
        output = output or self.output
        signing = ["--key", key or self.key, "--output-dir", output, "--debian-tools", DEBIAN_TOOLS]
        result = subprocess.run(
            [
                sys.executable,
                SIGNER_TOOL,
                *("--manifest", self.manifest, "--certificate", certificate or self.certificate),
                *("--scratch", WORK.absolute()),
                *(arguments if "--validate-only" in arguments else [*signing, *arguments]),
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        return result

    def assert_rejected(self, message, *arguments, **options):
        result = self.run_signer(*arguments, **options)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(message, result.stderr)
        self.assertFalse(self.output.exists(), "a rejected manifest must not produce signed binaries")

    def assert_import_accepts(self, entry):
        """Runs the verification of secure_boot_import_response on the signed binary of entry."""
        scratch = WORK / (self._testMethodName + "-import")
        scratch.mkdir(exist_ok=True)
        files = {name: scratch / name for name in ("expected.pem", "pkcs7", "content", "signer.pem", "out", "meta")}
        SECURE_BOOT.verify(
            SimpleNamespace(
                certificate=self.execroot / entry["certificate"],
                content=files["content"],
                expected_pem=files["expected.pem"],
                metadata=files["meta"],
                openssl=DEBIAN_TOOLS,
                output=files["out"],
                pkcs7=files["pkcs7"],
                request=self.execroot / entry["request"],
                request_digest=self.execroot / entry["request_digest"],
                signed=[self.output / entry["signed_name"]],
                unsigned=self.execroot / entry["unsigned_binary"],
                verified_signer=files["signer.pem"],
            )
        )

    def test_signs_every_request_with_the_pinned_sbsign_and_the_import_accepts_them(self):
        result = self.run_signer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(path.name for path in self.output.iterdir()), ["boot.signed.efi", "uki.signed.efi"])
        for entry in self.entries:
            self.assert_import_accepts(entry)
        self.assertNotIn("PRIVATE", result.stdout + result.stderr)

    def test_signs_deterministically_at_the_signing_time_or_source_date_epoch(self):
        not_before, _ = SECURE_BOOT.certificate_validity(SECURE_BOOT.certificate_der(self.certificate))
        signing_time = not_before + 1
        result = self.run_signer("--signing-time", str(signing_time))
        self.assertEqual(result.returncode, 0, result.stderr)
        from_epoch = WORK / (self._testMethodName + "-source-date-epoch")
        environment = dict(os.environ, SOURCE_DATE_EPOCH=str(signing_time))
        result = self.run_signer(output=from_epoch, env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        for entry in self.entries:
            signed = self.output / entry["signed_name"]
            self.assertEqual(signed.read_bytes(), (from_epoch / entry["signed_name"]).read_bytes())
            self.assertEqual(openssl_signing_times(signed), [openssl_time(signing_time)])
            self.assert_import_accepts(entry)

    def test_signs_at_the_current_time_without_a_signing_time(self):
        before = int(time.time())
        result = self.run_signer(env={key: value for key, value in os.environ.items() if key != "SOURCE_DATE_EPOCH"})
        self.assertEqual(result.returncode, 0, result.stderr)
        printed = openssl_signing_times(self.output / self.entries[0]["signed_name"])
        self.assertIn(printed, [[openssl_time(moment)] for moment in range(before, int(time.time()) + 1)])

    def test_rejects_invalid_signing_times(self):
        not_before, not_after = SECURE_BOOT.certificate_validity(SECURE_BOOT.certificate_der(self.certificate))
        inside = str(not_before)
        for name, arguments, source_date_epoch, message in (
            ("not a number", ["--signing-time", "yesterday"], None, "is not a Unix time in seconds"),
            ("negative", ["--signing-time", "-1"], None, "is not a Unix time in seconds"),
            ("after year 9999", ["--signing-time", "253402300800"], None, "is not a Unix time in seconds"),
            ("malformed epoch", [], "1.5", "SOURCE_DATE_EPOCH: '1.5' is not a Unix time in seconds"),
            ("before notBefore", ["--signing-time", str(not_before - 1)], None, "outside the validity"),
            ("after notAfter", ["--signing-time", str(not_after + 1)], None, "outside the validity"),
            ("epoch before notBefore", [], str(not_before - 1), "outside the validity"),
            ("option before the epoch", ["--signing-time", str(not_before - 1)], inside, "outside the validity"),
        ):
            with self.subTest(name):
                environment = {key: value for key, value in os.environ.items() if key != "SOURCE_DATE_EPOCH"}
                if source_date_epoch is not None:
                    environment["SOURCE_DATE_EPOCH"] = source_date_epoch
                self.assert_rejected(message, "--validate-only", *arguments, env=environment)
        result = self.run_signer("--validate-only", "--signing-time", inside)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_host_signing_tool_needs_faketime_for_a_signing_time(self):
        empty = WORK / (self._testMethodName + "-path")
        empty.mkdir()
        self.assert_rejected(
            "needs libfaketime's faketime on PATH with --sbsign",
            *("--sbsign", sys.executable, "--signing-time", "0"),
            env=dict(os.environ, PATH=str(empty.absolute())),
        )

    @unittest.skipUnless(shutil.which("sbsign"), "the host has no sbsigntools sbsign")
    def test_rejects_a_signature_at_another_time_than_the_signing_time(self):
        # A faketime that ignores the time it is given, as a static signing tool would ignore libfaketime.
        bin_directory = WORK / (self._testMethodName + "-path")
        bin_directory.mkdir()
        faketime = bin_directory / "faketime"
        faketime.write_text('#!/bin/sh\nshift 2\nexec "$@"\n')
        faketime.chmod(0o755)
        _, not_after = SECURE_BOOT.certificate_validity(SECURE_BOOT.certificate_der(self.certificate))
        environment = dict(os.environ, PATH="{}:{}".format(bin_directory.absolute(), os.environ["PATH"]))
        self.assert_rejected(
            "the signing tool wrote the signingTime",
            *("--sbsign", "sbsign", "--signing-time", str(not_after)),
            env=environment,
        )

    @unittest.skipUnless(shutil.which("sbsign") and shutil.which("faketime"), "the host has no sbsign and faketime")
    def test_host_sbsign_signs_at_the_signing_time(self):
        not_before, _ = SECURE_BOOT.certificate_validity(SECURE_BOOT.certificate_der(self.certificate))
        result = self.run_signer("--sbsign", "sbsign", "--signing-time", str(not_before))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            openssl_signing_times(self.output / self.entries[0]["signed_name"]), [openssl_time(not_before)]
        )

    @unittest.skipUnless(shutil.which("sbsign"), "the host has no sbsigntools sbsign")
    def test_host_sbsign_output_is_accepted_by_the_import(self):
        result = self.run_signer("--sbsign", "sbsign")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_import_accepts(self.entries[0])

    def test_validate_only_needs_no_key(self):
        result = self.run_signer("--validate-only")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(), ["valid: //:uki -> uki.signed.efi", "valid: //:boot -> boot.signed.efi"]
        )

    def test_execroot_defaults_to_the_parent_of_bazel_out(self):
        self.assertEqual(SIGNER.find_execroot(self.manifest), self.execroot.resolve())
        with self.assertRaisesRegex(ValueError, "pass --execroot"):
            SIGNER.find_execroot(pathlib.Path("/signing/manifest.json"))

    def test_rejects_a_substituted_binary(self):
        (self.execroot / self.entries[0]["unsigned_binary"]).write_bytes(secure_boot_fixtures.minimal_pe(b"other"))
        self.assert_rejected("//:uki: unsigned binary does not match its request", "--validate-only")

    def test_rejects_another_certificate(self):
        self.assert_rejected("is not the requested certificate", certificate=self.other_certificate)

    def test_rejects_a_key_file_with_another_certificate(self):
        bundle = WORK / (self._testMethodName + ".bundle")
        bundle.write_bytes(self.key.read_bytes() + self.other_certificate.read_bytes())
        bundle.chmod(0o600)
        self.assert_rejected("the certificate in the key file is not --certificate", key=bundle)

    def test_rejects_a_key_that_does_not_belong_to_the_certificate(self):
        result = self.run_signer(key=self.other_key)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertFalse(self.output.exists())

    def test_rejects_signatures_that_do_not_verify_with_the_certificate(self):
        self.assertEqual(self.run_signer().returncode, 0)
        unsigned = (self.execroot / self.entries[0]["unsigned_binary"]).read_bytes()
        payload = SECURE_BOOT.verify_embedded_digest(unsigned, (self.output / "uki.signed.efi").read_bytes())
        certificate = SECURE_BOOT.certificate_der(self.certificate)
        SIGNER.verify_signature(payload, certificate)
        with self.assertRaisesRegex(ValueError, "does not name --certificate"):
            SIGNER.verify_signature(payload, SECURE_BOOT.certificate_der(self.other_certificate))
        # The signature is the last field of the only SignerInfo.
        corrupted = payload[:-1] + bytes([payload[-1] ^ 1])
        with self.assertRaisesRegex(ValueError, "does not verify with --certificate"):
            SIGNER.verify_signature(corrupted, certificate)

    def test_rejects_malformed_requests(self):
        request_path = self.execroot / self.entries[0]["request"]
        document = json.loads(request_path.read_text())
        for name, change, message in (
            ("extra field", {"comment": "x"}, "invalid signing request schema"),
            ("other format", {"format_version": "mkosi-secure-boot-signing-request-v2"}, "invalid signing request"),
            ("other context", {"context": "uefi-secure-boot-esp-file"}, "signing request digest does not match"),
        ):
            with self.subTest(name):
                request_path.write_text(json.dumps(document | change))
                self.assert_rejected(message, "--validate-only")
        request_path.write_text('{"esp_path": "", "esp_path": ""}')
        self.assert_rejected("duplicate JSON keys", "--validate-only")

    def test_rejects_malformed_manifests(self):
        uki, boot = self.entries
        for name, entries, message in (
            ("duplicate name", [uki, boot | {"signed_name": uki["signed_name"]}], "duplicate signed file name"),
            ("path as name", [uki | {"signed_name": "../uki.efi"}], "invalid or duplicate signed file name"),
            ("missing field", [{key: uki[key] for key in uki if key != "context"}], "must have exactly the fields"),
            ("absolute path", [uki | {"request": str(self.execroot.absolute() / uki["request"])}], "must be relative"),
            ("other esp_path", [boot | {"esp_path": "EFI/x.efi"}], "does not match the esp_path and context"),
            ("no requests", [], "nonempty requests array"),
        ):
            with self.subTest(name):
                self.write_manifest(entries)
                self.assert_rejected(message, "--validate-only")
        self.write_manifest(self.entries, "mkosi-secure-boot-signing-manifest-v0")
        self.assert_rejected("is not a mkosi-secure-boot-signing-manifest-v1 signing manifest", "--validate-only")

    def test_request_certificate_fingerprint_is_the_sha256_of_the_der_certificate(self):
        request = json.loads((self.execroot / self.entries[0]["request"]).read_text())
        der = SECURE_BOOT.certificate_der(self.certificate)
        self.assertEqual(request["certificate_sha256"], hashlib.sha256(der).hexdigest())


if __name__ == "__main__":
    unittest.main(argv=sys.argv[:1])
