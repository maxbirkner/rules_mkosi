"""Tests of offline OpenPGP signing of sysupdate manifests with the Debian tools' openssl and sqv."""

import base64
import hashlib
import json
import pathlib
import subprocess
import sys
import unittest

from mkosi.private import openpgp

TOOL, DEBIAN_TOOLS = sys.argv[1:3]


def _armor(binary, label):
    body = base64.b64encode(binary).decode()
    lines = [body[index : index + 64] for index in range(0, len(body), 64)]
    checksum = base64.b64encode(openpgp.crc24(binary).to_bytes(3, "big")).decode()
    return "-----BEGIN PGP {0}-----\n\n{1}\n={2}\n-----END PGP {0}-----\n".format(
        label, "\n".join(lines), checksum
    ).encode()


class OpenPgpTest(unittest.TestCase):
    def test_new_format_lengths_round_trip_at_their_boundaries(self):
        for length in (0, 191, 192, 8383, 8384):
            with self.subTest(length=length):
                body = bytes(range(256)) * (length // 256) + bytes(length % 256)
                self.assertEqual([(openpgp.TAG_USER_ID, body)], openpgp.packets(openpgp.packet(13, body)))

    def test_old_format_packets_are_read(self):
        self.assertEqual([(openpgp.TAG_USER_ID, b"abc")], openpgp.packets(b"\xb4\x03abc"))
        self.assertEqual([(openpgp.TAG_USER_ID, b"abc")], openpgp.packets(b"\xb5\x00\x03abc"))

    def test_malformed_packets_are_rejected(self):
        for data, message in (
            (b"", "no OpenPGP packets"),
            (b"\x00", "invalid OpenPGP packet header"),
            (b"\xcd\x05abc", "truncated OpenPGP packet"),
            (b"\xcd", "truncated OpenPGP packet header"),
            (b"\xcd\xe0abc", "partial OpenPGP packet lengths"),
            (b"\xb7abc", "indeterminate OpenPGP packet lengths"),
        ):
            with self.subTest(data=data), self.assertRaisesRegex(ValueError, message):
                openpgp.packets(data)

    def test_armor_checksum_is_checked(self):
        armored = _armor(b"\xb4\x03abc", "SIGNATURE")
        self.assertEqual(b"\xb4\x03abc", openpgp.dearmor(armored, "SIGNATURE"))
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            # The body of b"\xb4\x03abd" with the checksum of b"\xb4\x03abc".
            openpgp.dearmor(armored.replace(b"tANhYmM=", b"tANhYmQ="), "SIGNATURE")
        with self.assertRaisesRegex(ValueError, "'PGP PUBLIC KEY BLOCK'"):
            openpgp.dearmor(armored, "PUBLIC KEY BLOCK")

    def test_certificate_rejects_secret_keys_and_several_certificates(self):
        public = openpgp.packet(openpgp.TAG_PUBLIC_KEY, openpgp.rsa_public_key(0xC5, 3, 0))
        for data, message in (
            (openpgp.packet(openpgp.TAG_SECRET_KEY, b"\x04"), "secret key material"),
            (public + openpgp.packet(openpgp.TAG_SECRET_SUBKEY, b"\x04"), "secret key material"),
            (public + public, "exactly one OpenPGP certificate"),
            (openpgp.packet(openpgp.TAG_USER_ID, b"a") + public, "exactly one OpenPGP certificate"),
            (public + openpgp.packet(11, b"literal"), "do not belong in an OpenPGP certificate"),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                openpgp.certificate(data)
        self.assertEqual(public, openpgp.certificate(_armor(public, "PUBLIC KEY BLOCK"))[0])

    def test_detached_signature_rejects_signed_messages(self):
        with self.assertRaisesRegex(ValueError, "detached OpenPGP signature"):
            openpgp.detached_signature(openpgp.packet(openpgp.TAG_SIGNATURE, b"") + openpgp.packet(11, b""))
        with self.assertRaisesRegex(ValueError, "exactly one OpenPGP signature, found 2"):
            openpgp.detached_signature(openpgp.packet(openpgp.TAG_SIGNATURE, b"") * 2)


def _run_tool(command, *arguments, check=True):
    return subprocess.run(
        [sys.executable, TOOL, command, *(str(argument) for argument in arguments)],
        capture_output=True,
        text=True,
        check=check,
    )


class SigningTest(unittest.TestCase):
    """Signs two payload manifests with each of two ephemeral keys once, since every key takes seconds to generate."""

    @classmethod
    def setUpClass(cls):
        cls.shared = pathlib.Path("sysupdate-signing-work") / "shared"
        cls.shared.mkdir(parents=True, exist_ok=True)
        cls.payloads = []
        for index in range(2):
            payload = cls.shared / "payload-{}".format(index)
            payload.mkdir(exist_ok=True)
            (payload / "SHA256SUMS").write_text(
                "{}  os_{}.efi\n".format(hashlib.sha256(str(index).encode()).hexdigest(), index + 1)
            )
            cls.payloads.append(payload)
        cls.public_key, cls.signatures = cls.fixture("fixture")
        cls.other_key, cls.other_signatures = cls.fixture("other")

    @classmethod
    def fixture(cls, name):
        signatures = [cls.shared / "{}-{}.gpg".format(name, index) for index in range(len(cls.payloads))]
        sign = []
        for payload, signature in zip(cls.payloads, signatures, strict=True):
            sign += ["--sign", payload, signature]
        public_key = cls.shared / "{}.pgp".format(name)
        keyring = cls.shared / "{}.keyring".format(name)
        scratch = cls.shared / ".{}-private".format(name)
        _run_tool(
            "ephemeral-fixture",
            "--openssl",
            DEBIAN_TOOLS,
            "--public-key",
            public_key,
            "--keyring-dir",
            keyring,
            "--scratch",
            scratch,
            *sign,
        )
        assert not scratch.exists()
        assert public_key.read_bytes() == (keyring / "import-pubring.gpg").read_bytes()
        return public_key, signatures

    def setUp(self):
        self.work = pathlib.Path("sysupdate-signing-work") / self._testMethodName
        self.work.mkdir(parents=True, exist_ok=True)

    def run_tool(self, command, *arguments, check=True):
        return _run_tool(command, *arguments, check=check)

    def request(self, payload, public_key):
        outputs = self.work / "request"
        outputs.mkdir(exist_ok=True)
        self.run_tool(
            "request",
            "--payload",
            payload,
            "--public-key",
            public_key,
            "--manifest-output",
            outputs / "SHA256SUMS",
            "--public-key-output",
            outputs / "signer.pgp",
            "--output",
            outputs / "request.json",
        )
        return outputs

    def verify(self, request, *signatures, check=True):
        arguments = []
        for signature in signatures:
            arguments += ["--signature", signature]
        return self.run_tool(
            "verify",
            "--sqv",
            DEBIAN_TOOLS,
            "--request",
            request / "request.json",
            "--manifest",
            request / "SHA256SUMS",
            "--public-key",
            request / "signer.pgp",
            "--output",
            self.work / "SHA256SUMS.gpg",
            *arguments,
            check=check,
        )

    def test_request_binds_manifest_files_and_signer(self):
        request = self.request(self.payloads[0], self.public_key)
        content = json.loads((request / "request.json").read_text())
        manifest = (self.payloads[0] / "SHA256SUMS").read_bytes()
        self.assertEqual(manifest, (request / "SHA256SUMS").read_bytes())
        self.assertEqual(hashlib.sha256(manifest).hexdigest(), content["manifest_sha256"])
        self.assertEqual({"os_1.efi": hashlib.sha256(b"0").hexdigest()}, content["files"])
        self.assertEqual(openpgp.certificate(self.public_key.read_bytes())[1], content["signer_fingerprint"])
        self.assertEqual("mkosi-sysupdate-signing-request-v1", content["format_version"])

    def test_import_selects_the_signature_of_the_requested_manifest(self):
        request = self.request(self.payloads[1], self.public_key)
        self.verify(request, *self.signatures)
        self.assertEqual(self.signatures[1].read_bytes(), (self.work / "SHA256SUMS.gpg").read_bytes())

    def test_import_accepts_an_armored_signature_and_writes_it_binary(self):
        request = self.request(self.payloads[0], self.public_key)
        armored = self.work / "armored.asc"
        armored.write_bytes(_armor(self.signatures[0].read_bytes(), "SIGNATURE"))
        self.verify(request, armored)
        self.assertEqual(self.signatures[0].read_bytes(), (self.work / "SHA256SUMS.gpg").read_bytes())

    def test_import_rejects_a_signature_of_another_manifest(self):
        request = self.request(self.payloads[0], self.public_key)
        result = self.verify(request, self.signatures[1], check=False)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("SYSUPDATE_SIGNING_INVALID: no signature verifies SHA256SUMS", result.stderr)
        self.assertFalse((self.work / "SHA256SUMS.gpg").exists())

    def test_import_rejects_a_valid_signature_next_to_one_by_another_key(self):
        # sqv accepts this, but gpg on the device fails for the signature whose key it does not have.
        request = self.request(self.payloads[0], self.public_key)
        combined = self.work / "combined.gpg"
        combined.write_bytes(self.signatures[0].read_bytes() + self.other_signatures[0].read_bytes())
        result = self.verify(request, combined, check=False)
        self.assertIn("expected exactly one OpenPGP signature, found 2", result.stderr)
        self.assertFalse((self.work / "SHA256SUMS.gpg").exists())

    def test_import_rejects_a_signature_by_another_key(self):
        request = self.request(self.payloads[0], self.public_key)
        result = self.verify(request, self.other_signatures[0], check=False)
        self.assertIn("no signature verifies SHA256SUMS", result.stderr)

    def test_import_rejects_a_manifest_or_key_that_does_not_match_the_request(self):
        request = self.request(self.payloads[0], self.public_key)
        (request / "SHA256SUMS").write_bytes((self.payloads[1] / "SHA256SUMS").read_bytes())
        result = self.verify(request, self.signatures[1], check=False)
        self.assertIn("SHA256SUMS does not match the signing request", result.stderr)
        request = self.request(self.payloads[0], self.public_key)
        (request / "signer.pgp").write_bytes(self.other_key.read_bytes())
        result = self.verify(request, self.signatures[0], check=False)
        self.assertIn("is not the requested signer", result.stderr)

    def test_request_rejects_a_secret_key(self):
        secret = self.work / "secret.pgp"
        secret.write_bytes(openpgp.packet(openpgp.TAG_SECRET_KEY, b"\x04"))
        with self.assertRaises(subprocess.CalledProcessError) as raised:
            self.request(self.payloads[0], secret)
        self.assertIn("secret key material", raised.exception.stderr)


if __name__ == "__main__":
    unittest.main(argv=sys.argv[:1])
