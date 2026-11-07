#!/usr/bin/python3
"""Write systemd-sysupdate transfer definitions and matching A/B update payloads."""

import argparse
import functools
import hashlib
import json
import lzma
import os
import runpy
import shutil
import uuid
from pathlib import Path

_load_sibling = runpy.run_path(str(Path(__file__).with_name("sibling_loader.py")))["load_sibling"]
gpt = _load_sibling(__file__, "gpt_partitions")
file_hashing = _load_sibling(__file__, "file_hashing")

_TRANSFER = """\
[Transfer]
ProtectVersion=%A
Verify={verify}

[Source]
{source}
MatchPattern={pattern}

[Target]
{target}
"""

# The directory is chosen at run time with --transfer-source=.
_DIRECTORY_SOURCE = """\
Type=regular-file
Path=/
PathRelativeTo=explicit"""

# systemd-sysupdate downloads SHA256SUMS and, with Verify=yes, SHA256SUMS.gpg from Path, and then the matching files.
_URL_SOURCE = """\
Type=url-file
Path={url}"""


def root_name(image_id, version, partition_uuid):
    return "{}_{}.root.{}.raw".format(image_id, version, partition_uuid)


def verity_name(image_id, version, partition_uuid):
    return "{}_{}.root-verity.{}.raw".format(image_id, version, partition_uuid)


def uki_name(image_id, version):
    return "{}_{}.efi".format(image_id, version)


_PARTITION_TARGET = """\
Type=partition
Path=auto
MatchPattern={label}
MatchPartitionType={partition_type}
ReadOnly=yes
InstancesMax={instances}"""

_UKI_TARGET = """\
Type=regular-file
Path=/EFI/Linux
PathRelativeTo=boot
MatchPattern={patterns}
Mode=0444
InstancesMax={instances}"""


def _uki_target(image_id, boot_attempts, instances):
    counted = ["{}_@v+@l-@d.efi".format(image_id), "{}_@v+@l.efi".format(image_id)]
    uncounted = ["{}_@v.efi".format(image_id)]
    target = _UKI_TARGET.format(
        patterns=" ".join(counted + uncounted if boot_attempts else uncounted + counted),
        instances=instances,
    )
    if boot_attempts:
        target += "\nTriesLeft={}\nTriesDone=0".format(boot_attempts)
    return target


def _compressed_or_plain(pattern):
    """Returns source patterns that match a partition file with or without compression."""
    return " ".join(pattern + suffix for suffix in sorted(COMPRESSION_SUFFIXES.values(), reverse=True))


def transfers(image_id, boot_attempts, instances, url=None):
    """Returns transfer file names and contents for the root, verity and UKI resources.

    File names sort so that both partitions are written before the UKI that references them, and partition sources
    match every payload compression.
    systemd-sysupdate names a new UKI after the first target MatchPattern and gives it TriesLeft=3 unless
    configured otherwise, so boot counting is disabled by listing the counter-free pattern first.
    Without url, the source is a directory; with url, an HTTP(S) directory whose SHA256SUMS must be signed.
    """
    transfer = functools.partial(
        _TRANSFER.format,
        verify="yes" if url else "no",
        source=_URL_SOURCE.format(url=url) if url else _DIRECTORY_SOURCE,
    )
    partitions = (
        ("10-root.transfer", root_name, "", "root-x86-64"),
        ("20-root-verity.transfer", verity_name, "_verity", "root-x86-64-verity"),
    )
    result = {
        name: transfer(
            pattern=_compressed_or_plain(source_name(image_id, "@v", "@u")),
            target=_PARTITION_TARGET.format(
                label=image_id + "_@v" + label_suffix,
                partition_type=partition_type,
                instances=instances,
            ),
        )
        for name, source_name, label_suffix, partition_type in partitions
    }
    result["90-uki.transfer"] = transfer(
        pattern=uki_name(image_id, "@v"),
        target=_uki_target(image_id, boot_attempts, instances),
    )
    return result


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

# File name suffixes of the compressions that systemd-import and systemd-pull of systemd 257 decompress; zstd needs
# systemd 258.
COMPRESSION_SUFFIXES = {"none": "", "xz": ".xz"}


def _chunks(source, size):
    """Yields the first size bytes, or all, of source."""
    remaining = os.path.getsize(source) if size is None else size
    with open(source, "rb") as src:
        while remaining and (chunk := src.read(min(_CHUNK_BYTES, remaining))):
            remaining -= len(chunk)
            yield chunk
    if remaining:
        raise ValueError("{} is shorter than its dm-verity geometry".format(source))


def _write_sparse(chunks, destination):
    """Writes chunks and yields them, keeping all-zero chunks sparse."""
    for chunk in chunks:
        if chunk == _ZERO_CHUNK[: len(chunk)]:
            destination.seek(len(chunk), os.SEEK_CUR)
        else:
            destination.write(chunk)
        yield chunk
    destination.truncate()


def _write_xz(chunks, destination):
    """Writes chunks as one xz stream and yields its bytes.

    A single-threaded compressor with fixed settings makes the output a function of the input and the liblzma version.
    """
    compressor = lzma.LZMACompressor(format=lzma.FORMAT_XZ, check=lzma.CHECK_CRC64, preset=6)
    for chunk in chunks:
        compressed = compressor.compress(chunk)
        destination.write(compressed)
        yield compressed
    compressed = compressor.flush()
    destination.write(compressed)
    yield compressed


_WRITERS = {"none": _write_sparse, "xz": _write_xz}


def _copy(source, destination, size=None, compression="none"):
    """Copies the first size bytes, or all, of source to a new read-only file and returns the file's SHA-256."""
    digest = hashlib.sha256()
    with open(destination, "xb") as dst:
        for written in _WRITERS[compression](_chunks(source, size), dst):
            digest.update(written)
    os.chmod(destination, 0o444)
    return digest.hexdigest()


def verity_extents(verity_metadata):
    """Returns the bytes of the root and verity partitions that dm-verity covers, from mkosi_image's metadata.

    The root partition of an A/B slot may be larger than a minimized read-only file system, and the verity partition
    larger than its hash tree; systemd-sysupdate writes a smaller file into the slot and dm-verity reads no further.
    """
    return (
        verity_metadata["data_blocks"] * verity_metadata["data_block_size"],
        verity_metadata["tree_offset"] + verity_metadata["tree_size"],
    )


def _release_uki(args):
    """Returns the UKI to ship, rejecting a signed UKI whose signing request names another unsigned UKI."""
    if (args.signed_uki is None) != (args.signing_request is None):
        raise ValueError("--signed-uki and --signing-request must be given together")
    if args.signed_uki is None:
        return args.uki
    requested = json.loads(Path(args.signing_request).read_text(encoding="utf-8"))["unsigned_sha256"]
    actual = file_hashing.sha256_file(args.uki)
    if requested != actual:
        raise ValueError(
            "signed UKI was requested for unsigned UKI {} but the image's UKI is {}".format(requested, actual)
        )
    return args.signed_uki


def _read_image_version(path, image_id):
    """Returns the validated version in path using the sibling image_version.py helper."""
    return _load_sibling(__file__, "image_version").read_image_version(path, image_id)


def _check_slot_uuids(partitions, slot, root_uuid, verity_uuid):
    for type_guid, label, expected in (
        (gpt.ROOT_X86_64, slot, root_uuid),
        (gpt.ROOT_X86_64_VERITY, slot + "_verity", verity_uuid),
    ):
        actual = _populated(partitions, type_guid, label).get("uuid")
        if actual != expected:
            raise ValueError(
                "partition {!r} UUID {} does not match root-hash-derived UUID {}".format(label, actual, expected)
            )


def payload(args):
    if args.image_version_file is not None:
        args.image_version = _read_image_version(args.image_version_file, args.image_id)
    uki = _release_uki(args)
    root_hash = Path(args.root_hash).read_text(encoding="ascii").strip().lower()
    root_uuid, verity_uuid = verity_partition_uuids(root_hash)
    partitions = json.loads(Path(args.partition_metadata).read_text(encoding="utf-8"))["partitions"]
    _check_slot_uuids(partitions, "{}_{}".format(args.image_id, args.image_version), root_uuid, verity_uuid)
    root_size, verity_size = verity_extents(json.loads(Path(args.verity_metadata).read_text(encoding="utf-8")))
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    version, suffix, compression = args.image_version, COMPRESSION_SUFFIXES[args.compression], args.compression
    files = (
        (root_name(args.image_id, version, root_uuid) + suffix, args.root_image, root_size, compression),
        (verity_name(args.image_id, version, verity_uuid) + suffix, args.verity_image, verity_size, compression),
        (uki_name(args.image_id, version), uki, None, "none"),
    )
    digests = {name: _copy(source, output / name, size, method) for name, source, size, method in files}
    (output / "SHA256SUMS").write_text(
        "".join("{}  {}\n".format(digests[name], name) for name in sorted(digests)),
        encoding="ascii",
    )


def write_transfers(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    for name, content in transfers(args.image_id, args.boot_attempts, args.instances, args.url).items():
        (output / name).write_text(content, encoding="ascii")


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    transfer_parser = commands.add_parser("transfers")
    transfer_parser.add_argument("--image-id", required=True)
    transfer_parser.add_argument("--boot-attempts", type=int, required=True)
    transfer_parser.add_argument("--instances", type=int, required=True)
    transfer_parser.add_argument("--url")
    transfer_parser.add_argument("--output", required=True)
    transfer_parser.set_defaults(handler=write_transfers)
    payload_parser = commands.add_parser("payload")
    payload_parser.add_argument("--image-id", required=True)
    version = payload_parser.add_mutually_exclusive_group(required=True)
    version.add_argument("--image-version")
    version.add_argument("--image-version-file")
    payload_parser.add_argument("--root-hash", required=True)
    payload_parser.add_argument("--partition-metadata", required=True)
    payload_parser.add_argument("--root-image", required=True)
    payload_parser.add_argument("--verity-image", required=True)
    payload_parser.add_argument("--verity-metadata", required=True)
    payload_parser.add_argument("--uki", required=True)
    payload_parser.add_argument("--signed-uki")
    payload_parser.add_argument("--signing-request")
    payload_parser.add_argument("--compression", choices=sorted(COMPRESSION_SUFFIXES), default="none")
    payload_parser.add_argument("--output", required=True)
    payload_parser.set_defaults(handler=payload)
    args = parser.parse_args()
    try:
        args.handler(args)
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as error:
        shutil.rmtree(args.output, ignore_errors=True)
        raise SystemExit("SYSUPDATE_INVALID: {}".format(error)) from error


if __name__ == "__main__":
    main()
