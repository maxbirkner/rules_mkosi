"""Tests for systemd-sysupdate transfer definitions and A/B update payloads."""

import contextlib
import hashlib
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

from mkosi.private import sysupdate

# A root hash and the partition UUIDs that systemd-repart assigned to the matching data and hash partitions.
ROOT_HASH = "4ff071eebeb8f712c16bc66c438a1ec2e2634a3571cecd9c66c98f1bc76e708e"
ROOT_UUID = "4ff071ee-beb8-f712-c16b-c66c438a1ec2"
VERITY_UUID = "e2634a35-71ce-cd9c-66c9-8f1bc76e708e"


def _section(content, name):
    lines = content.split("[{}]\n".format(name), 1)[1].split("\n\n", 1)[0]
    return dict(line.split("=", 1) for line in lines.splitlines())


class TransferTest(unittest.TestCase):
    def test_partition_transfers_link_payload_uuids_to_versioned_slots(self):
        transfers = sysupdate.transfers("os", boot_attempts=3, instances=2)
        self.assertEqual(["10-root.transfer", "20-root-verity.transfer", "90-uki.transfer"], sorted(transfers))
        for name, pattern, label, partition_type in (
            ("10-root.transfer", "os_@v.root.@u.raw", "os_@v", "root-x86-64"),
            ("20-root-verity.transfer", "os_@v.root-verity.@u.raw", "os_@v_verity", "root-x86-64-verity"),
        ):
            with self.subTest(name=name):
                content = transfers[name]
                self.assertEqual({"ProtectVersion": "%A", "Verify": "no"}, _section(content, "Transfer"))
                self.assertEqual(
                    {
                        "Type": "regular-file",
                        "Path": "/",
                        "PathRelativeTo": "explicit",
                        "MatchPattern": pattern,
                    },
                    _section(content, "Source"),
                )
                self.assertEqual(
                    {
                        "Type": "partition",
                        "Path": "auto",
                        "MatchPattern": label,
                        "MatchPartitionType": partition_type,
                        "ReadOnly": "yes",
                        "InstancesMax": "2",
                    },
                    _section(content, "Target"),
                )

    def test_uki_transfer_enables_boot_counting(self):
        target = _section(sysupdate.transfers("os", boot_attempts=1, instances=3)["90-uki.transfer"], "Target")
        self.assertEqual(
            {
                "Type": "regular-file",
                "Path": "/EFI/Linux",
                "PathRelativeTo": "boot",
                "MatchPattern": "os_@v+@l-@d.efi os_@v+@l.efi os_@v.efi",
                "Mode": "0444",
                "InstancesMax": "3",
                "TriesLeft": "1",
                "TriesDone": "0",
            },
            target,
        )

    def test_zero_boot_attempts_disables_boot_counting(self):
        target = _section(sysupdate.transfers("os", boot_attempts=0, instances=2)["90-uki.transfer"], "Target")
        # systemd-sysupdate names new files after the first pattern and defaults to TriesLeft=3.
        self.assertEqual("os_@v.efi os_@v+@l-@d.efi os_@v+@l.efi", target["MatchPattern"])
        self.assertNotIn("TriesLeft", target)
        self.assertNotIn("TriesDone", target)


class UuidTest(unittest.TestCase):
    def test_uuids_match_systemd_repart_derivation(self):
        self.assertEqual((ROOT_UUID, VERITY_UUID), sysupdate.verity_partition_uuids(ROOT_HASH))

    def test_rejects_non_sha256_root_hash(self):
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            sysupdate.verity_partition_uuids(ROOT_HASH[:40])


class PayloadTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.directory.name)
        self.root_image = self.root / "root.raw"
        self.root_image.write_bytes(b"root" + bytes(3 * 1024 * 1024))
        (self.root / "verity.raw").write_bytes(b"verity")
        (self.root / "image.efi").write_bytes(b"uki")
        (self.root / "signed.efi").write_bytes(b"signed uki")
        (self.root / "roothash").write_text(ROOT_HASH.upper() + "\n")
        self.write_partitions(ROOT_UUID, VERITY_UUID)

    def tearDown(self):
        self.directory.cleanup()

    def write_partitions(self, root_uuid, verity_uuid, root_label="os_7"):
        partitions = [
            {"label": root_label, "type_guid": sysupdate.ROOT_X86_64, "uuid": root_uuid},
            {"label": "os_7_verity", "type_guid": sysupdate.ROOT_X86_64_VERITY, "uuid": verity_uuid},
            {"label": "_empty", "type_guid": sysupdate.ROOT_X86_64, "uuid": "92f2ab90-254e-4065-973c-9d971ad97d58"},
        ]
        (self.root / "partitions.json").write_text(json.dumps({"partitions": partitions}))

    def write_signing_request(self, unsigned_uki):
        request = {"unsigned_uki_sha256": hashlib.sha256(unsigned_uki).hexdigest()}
        (self.root / "request.json").write_text(json.dumps(request))

    def run_payload(self, *extra_args, version_args=("--image-version=7",)):
        output = self.root / "payload"
        argv = [
            "sysupdate.py",
            "payload",
            "--image-id=os",
            *version_args,
            "--root-hash={}".format(self.root / "roothash"),
            "--partition-metadata={}".format(self.root / "partitions.json"),
            "--root-image={}".format(self.root_image),
            "--verity-image={}".format(self.root / "verity.raw"),
            "--uki={}".format(self.root / "image.efi"),
            "--output={}".format(output),
            *extra_args,
        ]
        with mock.patch.object(sys, "argv", argv):
            sysupdate.main()
        return output

    def signed_args(self):
        return [
            "--signed-uki={}".format(self.root / "signed.efi"),
            "--signing-request={}".format(self.root / "request.json"),
        ]

    def test_payload_names_and_checksums(self):
        output = self.run_payload()
        root_name = "os_7.root.{}.raw".format(ROOT_UUID)
        verity_name = "os_7.root-verity.{}.raw".format(VERITY_UUID)
        self.assertEqual(
            sorted(["SHA256SUMS", "os_7.efi", root_name, verity_name]),
            sorted(path.name for path in output.iterdir()),
        )
        self.assertEqual(self.root_image.read_bytes(), (output / root_name).read_bytes())
        self.assertEqual(0o444, (output / root_name).stat().st_mode & 0o777)
        expected = "".join(
            "{}  {}\n".format(hashlib.sha256((output / name).read_bytes()).hexdigest(), name)
            for name in sorted(["os_7.efi", root_name, verity_name])
        )
        self.assertEqual(expected, (output / "SHA256SUMS").read_text())

    def test_payload_version_from_file(self):
        (self.root / "version").write_text("7\n")
        output = self.run_payload(version_args=("--image-version-file={}".format(self.root / "version"),))
        root_name = "os_7.root.{}.raw".format(ROOT_UUID)
        verity_name = "os_7.root-verity.{}.raw".format(VERITY_UUID)
        self.assertEqual(
            sorted(["SHA256SUMS", "os_7.efi", root_name, verity_name]),
            sorted(path.name for path in output.iterdir()),
        )

    def test_invalid_version_file_is_rejected_without_partial_output(self):
        for content in ("", "7_1\n", "7+1", "7\n\n"):
            with self.subTest(content=content):
                (self.root / "version").write_text(content)
                with self.assertRaises(SystemExit) as raised:
                    self.run_payload(version_args=("--image-version-file={}".format(self.root / "version"),))
                message = str(raised.exception)
                self.assertIn("SYSUPDATE_INVALID: invalid image_version_file", message)
                self.assertIn("image_version must be non-empty and use only letters, digits and '.'", message)
                self.assertFalse((self.root / "payload").exists())

    def test_version_and_version_file_are_exclusive(self):
        (self.root / "version").write_text("7")
        version_args = ("--image-version=7", "--image-version-file={}".format(self.root / "version"))
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
            self.run_payload(version_args=version_args)
        self.assertIn("not allowed with argument", stderr.getvalue())

    def test_payload_keeps_zero_runs_sparse(self):
        output = self.run_payload()
        copied = output / "os_7.root.{}.raw".format(ROOT_UUID)
        self.assertEqual(self.root_image.stat().st_size, copied.stat().st_size)
        self.assertLess(copied.stat().st_blocks * 512, os.path.getsize(copied))

    def test_uuid_mismatch_is_rejected_without_partial_output(self):
        self.write_partitions(ROOT_UUID, "07e94c80-f82d-4648-aa81-0b38dd49832a")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            self.run_payload()
        self.assertIn("SYSUPDATE_INVALID", str(raised.exception))
        self.assertIn("does not match root-hash-derived UUID " + VERITY_UUID, str(raised.exception))
        self.assertFalse((self.root / "payload").exists())

    def test_signed_uki_for_this_image_replaces_unsigned_uki(self):
        self.write_signing_request(b"uki")
        output = self.run_payload(*self.signed_args())
        self.assertEqual(b"signed uki", (output / "os_7.efi").read_bytes())

    def test_signed_uki_requested_for_another_image_is_rejected(self):
        self.write_signing_request(b"another uki")
        with self.assertRaises(SystemExit) as raised:
            self.run_payload(*self.signed_args())
        self.assertIn("SYSUPDATE_INVALID", str(raised.exception))
        self.assertIn("signed UKI was requested for unsigned UKI", str(raised.exception))
        self.assertFalse((self.root / "payload").exists())

    def test_signed_uki_without_signing_request_is_rejected(self):
        with self.assertRaisesRegex(SystemExit, "must be given together"):
            self.run_payload(self.signed_args()[0])

    def test_unlabelled_root_slot_is_rejected(self):
        self.write_partitions(ROOT_UUID, VERITY_UUID, root_label="root-x86-64")
        with self.assertRaisesRegex(SystemExit, "expected one partition labelled 'os_7'"):
            self.run_payload()

    def test_transfer_command_writes_definitions(self):
        output = self.root / "transfers"
        argv = [
            "sysupdate.py",
            "transfers",
            "--image-id=os",
            "--boot-attempts=3",
            "--instances=2",
            "--output={}".format(output),
        ]
        with mock.patch.object(sys, "argv", argv):
            sysupdate.main()
        self.assertEqual(
            sysupdate.transfers("os", 3, 2),
            {path.name: path.read_text() for path in output.iterdir()},
        )


if __name__ == "__main__":
    unittest.main()
