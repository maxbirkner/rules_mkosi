#!/usr/bin/python3
"""Write systemd-sysupdate transfer definitions and matching A/B update payloads."""

import argparse
import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path

ROOT_X86_64 = "4f68bce3-e8cd-4db1-96e7-fbcaf984b709"
ROOT_X86_64_VERITY = "2c7357ed-ebd2-46d9-aec1-23d437ec2bf5"

_TRANSFER = """\
[Transfer]
ProtectVersion=%A
Verify=no

[Source]
Type=regular-file
Path=/
PathRelativeTo=explicit
MatchPattern={source}

[Target]
{target}
"""


def root_name(image_id, version, partition_uuid):
    return "{}_{}.root.{}.raw".format(image_id, version, partition_uuid)


def verity_name(image_id, version, partition_uuid):
    return "{}_{}.root-verity.{}.raw".format(image_id, version, partition_uuid)


def uki_name(image_id, version):
    return "{}_{}.efi".format(image_id, version)


def transfers(image_id, boot_attempts, instances):
    """Returns transfer file names and contents for the root, verity and UKI resources.

    File names sort so that both partitions are written before the UKI that references them.
    systemd-sysupdate names a new UKI after the first target MatchPattern and gives it TriesLeft=3 unless
    configured otherwise, so boot counting is disabled by listing the counter-free pattern first.
    """
    partition = """\
Type=partition
Path=auto
MatchPattern={label}
MatchPartitionType={partition_type}
ReadOnly=yes
InstancesMax={instances}"""
    counted = ["{}_@v+@l-@d.efi".format(image_id), "{}_@v+@l.efi".format(image_id)]
    uncounted = ["{}_@v.efi".format(image_id)]
    uki_target = """\
Type=regular-file
Path=/EFI/Linux
PathRelativeTo=boot
MatchPattern={patterns}
Mode=0444
InstancesMax={instances}""".format(
        patterns=" ".join(counted + uncounted if boot_attempts else uncounted + counted),
        instances=instances,
    )
    if boot_attempts:
        uki_target += "\nTriesLeft={}\nTriesDone=0".format(boot_attempts)
    return {
        "10-root.transfer": _TRANSFER.format(
            source=root_name(image_id, "@v", "@u"),
            target=partition.format(
                label=image_id + "_@v",
                partition_type="root-x86-64",
                instances=instances,
            ),
        ),
        "20-root-verity.transfer": _TRANSFER.format(
            source=verity_name(image_id, "@v", "@u"),
            target=partition.format(
                label=image_id + "_@v_verity",
                partition_type="root-x86-64-verity",
                instances=instances,
            ),
        ),
        "90-uki.transfer": _TRANSFER.format(
            source=uki_name(image_id, "@v"),
            target=uki_target,
        ),
    }


def verity_partition_uuids(root_hash):
    """Returns the data and hash partition UUIDs systemd-repart derives from a SHA-256 root hash."""
    digest = bytes.fromhex(root_hash)
    if len(digest) != 32:
        raise ValueError("root hash must be a SHA-256 digest")
    return str(uuid.UUID(bytes=digest[:16])), str(uuid.UUID(bytes=digest[16:]))


def _populated(partitions, type_guid, label):
    matches = [p for p in partitions if p["type_guid"] == type_guid and p["label"] == label]
    if len(matches) != 1:
        raise ValueError("expected one partition labelled {!r}".format(label))
    return matches[0]


_CHUNK_BYTES = 1024 * 1024
_ZERO_CHUNK = bytes(_CHUNK_BYTES)


def _copy(source, destination):
    """Copies source to a new read-only file, keeping all-zero chunks sparse, and returns its SHA-256."""
    digest = hashlib.sha256()
    with open(source, "rb") as src, open(destination, "xb") as dst:
        while chunk := src.read(_CHUNK_BYTES):
            digest.update(chunk)
            if chunk == _ZERO_CHUNK[: len(chunk)]:
                dst.seek(len(chunk), os.SEEK_CUR)
            else:
                dst.write(chunk)
        dst.truncate()
    os.chmod(destination, 0o444)
    return digest.hexdigest()


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        while chunk := source.read(_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _release_uki(args):
    """Returns the UKI to ship, rejecting a signed UKI whose signing request names another unsigned UKI."""
    if (args.signed_uki is None) != (args.signing_request is None):
        raise ValueError("--signed-uki and --signing-request must be given together")
    if args.signed_uki is None:
        return args.uki
    requested = json.loads(Path(args.signing_request).read_text(encoding="utf-8"))["unsigned_uki_sha256"]
    actual = _sha256(args.uki)
    if requested != actual:
        raise ValueError(
            "signed UKI was requested for unsigned UKI {} but the image's UKI is {}".format(requested, actual)
        )
    return args.signed_uki


def payload(args):
    uki = _release_uki(args)
    root_hash = Path(args.root_hash).read_text(encoding="ascii").strip().lower()
    root_uuid, verity_uuid = verity_partition_uuids(root_hash)
    partitions = json.loads(Path(args.partition_metadata).read_text(encoding="utf-8"))["partitions"]
    slot = "{}_{}".format(args.image_id, args.image_version)
    for type_guid, label, expected in (
        (ROOT_X86_64, slot, root_uuid),
        (ROOT_X86_64_VERITY, slot + "_verity", verity_uuid),
    ):
        actual = _populated(partitions, type_guid, label).get("uuid")
        if actual != expected:
            raise ValueError(
                "partition {!r} UUID {} does not match root-hash-derived UUID {}".format(label, actual, expected)
            )
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    digests = {}
    for name, source in (
        (root_name(args.image_id, args.image_version, root_uuid), args.root_image),
        (verity_name(args.image_id, args.image_version, verity_uuid), args.verity_image),
        (uki_name(args.image_id, args.image_version), uki),
    ):
        digests[name] = _copy(source, output / name)
    (output / "SHA256SUMS").write_text(
        "".join("{}  {}\n".format(digests[name], name) for name in sorted(digests)),
        encoding="ascii",
    )


def write_transfers(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    for name, content in transfers(args.image_id, args.boot_attempts, args.instances).items():
        (output / name).write_text(content, encoding="ascii")


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    transfer_parser = commands.add_parser("transfers")
    transfer_parser.add_argument("--image-id", required=True)
    transfer_parser.add_argument("--boot-attempts", type=int, required=True)
    transfer_parser.add_argument("--instances", type=int, required=True)
    transfer_parser.add_argument("--output", required=True)
    transfer_parser.set_defaults(handler=write_transfers)
    payload_parser = commands.add_parser("payload")
    payload_parser.add_argument("--image-id", required=True)
    payload_parser.add_argument("--image-version", required=True)
    payload_parser.add_argument("--root-hash", required=True)
    payload_parser.add_argument("--partition-metadata", required=True)
    payload_parser.add_argument("--root-image", required=True)
    payload_parser.add_argument("--verity-image", required=True)
    payload_parser.add_argument("--uki", required=True)
    payload_parser.add_argument("--signed-uki")
    payload_parser.add_argument("--signing-request")
    payload_parser.add_argument("--output", required=True)
    payload_parser.set_defaults(handler=payload)
    args = parser.parse_args()
    try:
        args.handler(args)
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as error:
        shutil.rmtree(args.output, ignore_errors=True)
        raise SystemExit("SYSUPDATE_INVALID: {}".format(error))


if __name__ == "__main__":
    main()
