#!/usr/bin/python3
"""Verify dm-verity split artifacts and project normalized integrity geometry."""

import argparse
import hashlib
import json
import os
import struct
import tempfile
from pathlib import Path

ROOT = "4f68bce3-e8cd-4db1-96e7-fbcaf984b709"
ROOT_VERITY = "2c7357ed-ebd2-46d9-aec1-23d437ec2bf5"
ROOT_VERITY_SIG = "41092b05-9fc8-4523-994f-2def0408b176"
MAX_ARTIFACT_BYTES = 16 * 1024**3
MAX_BLOCKS = 1 << 32
MAX_LEVELS = 64
MAX_SPOOL_BYTES = 2 * 1024**3
SUPERBLOCK_SIZE = 512


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_superblock(path):
    with open(path, "rb") as source:
        value = source.read(SUPERBLOCK_SIZE)
    if len(value) != SUPERBLOCK_SIZE or value[:8] != b"verity\0\0":
        raise ValueError("hash artifact has no complete dm-verity superblock")
    version, hash_type = struct.unpack_from("<II", value, 8)
    algorithm = value[32:64].split(b"\0", 1)[0].decode("ascii")
    data_block_size, hash_block_size = struct.unpack_from("<II", value, 64)
    data_blocks = struct.unpack_from("<Q", value, 72)[0]
    salt_size = struct.unpack_from("<H", value, 80)[0]
    if version != 1 or hash_type != 1:
        raise ValueError("only dm-verity format 1 with normal salt placement is supported")
    try:
        digest_size = hashlib.new(algorithm).digest_size
    except ValueError as error:
        raise ValueError("unsupported dm-verity hash algorithm") from error
    if data_block_size < 512 or data_block_size > 1024 * 1024 or data_block_size & (data_block_size - 1):
        raise ValueError("invalid dm-verity data block size")
    if hash_block_size < digest_size or hash_block_size > 1024 * 1024 or hash_block_size & (hash_block_size - 1):
        raise ValueError("invalid dm-verity hash block size")
    slot_size = 1 << (digest_size - 1).bit_length()
    if slot_size > hash_block_size or hash_block_size % slot_size:
        raise ValueError("dm-verity digest slots do not divide the hash block")
    if not data_blocks or data_blocks > MAX_BLOCKS:
        raise ValueError("invalid dm-verity data block count")
    if salt_size > 256:
        raise ValueError("invalid dm-verity salt size")
    return {
        "algorithm": algorithm,
        "data_block_size": data_block_size,
        "data_blocks": data_blocks,
        "digest_size": digest_size,
        "hash_block_size": hash_block_size,
        "slot_size": slot_size,
        "salt": value[88:88 + salt_size],
        "superblock": value,
    }


def _leaf_digests(source_path, geometry, output):
    algorithm = geometry["algorithm"]
    salt = geometry["salt"]
    block_size = geometry["data_block_size"]
    with open(source_path, "rb") as source:
        for _ in range(geometry["data_blocks"]):
            block = source.read(block_size)
            if len(block) != block_size:
                raise ValueError("root artifact is truncated within declared data blocks")
            digest = hashlib.new(algorithm)
            digest.update(salt)
            digest.update(block)
            output.write(digest.digest())


def _level_counts(data_blocks, per_block):
    counts = []
    digests = data_blocks
    while digests > 1:
        blocks = (digests + per_block - 1) // per_block
        counts.append(blocks)
        digests = blocks
        if len(counts) > MAX_LEVELS:
            raise ValueError("dm-verity tree exceeds the level limit")
    return counts


def _temporary():
    return tempfile.NamedTemporaryFile(prefix=".verity-digests-", dir=".", delete=False)


def _verify_tree(root_image_path, hash_image_path, geometry, tree_offset):
    digest_size = geometry["digest_size"]
    slot_size = geometry["slot_size"]
    block_size = geometry["hash_block_size"]
    per_block = block_size // slot_size
    counts = _level_counts(geometry["data_blocks"], per_block)
    leaf_bytes = geometry["data_blocks"] * digest_size
    next_bytes = counts[0] * digest_size if counts else 0
    if leaf_bytes + next_bytes > MAX_SPOOL_BYTES:
        raise ValueError("dm-verity digest spools exceed the resource limit")
    paths = []
    try:
        leaf = _temporary()
        paths.append(leaf.name)
        with leaf:
            _leaf_digests(root_image_path, geometry, leaf)
        current_path = leaf.name
        current_digests = geometry["data_blocks"]
        level_offsets = []
        preceding = 0
        for count in reversed(counts):
            level_offsets.append(tree_offset + preceding * block_size)
            preceding += count
        level_offsets.reverse()
        with open(hash_image_path, "rb") as emitted:
            for level, (block_count, emitted_offset) in enumerate(zip(counts, level_offsets)):
                next_file = _temporary()
                paths.append(next_file.name)
                with open(current_path, "rb") as current, next_file:
                    emitted.seek(emitted_offset)
                    consumed = 0
                    for block_index in range(block_count):
                        block = bytearray()
                        for _ in range(min(per_block, current_digests - consumed)):
                            digest = current.read(digest_size)
                            if len(digest) != digest_size:
                                raise ValueError("dm-verity digest spool is truncated")
                            block.extend(digest)
                            block.extend(b"\0" * (slot_size - digest_size))
                            consumed += 1
                        block.extend(b"\0" * (block_size - len(block)))
                        actual = emitted.read(block_size)
                        if actual != block:
                            raise ValueError(
                                "dm-verity hash mismatch at level {} block {}".format(
                                    level, block_index
                                )
                            )
                        digest = hashlib.new(geometry["algorithm"])
                        digest.update(geometry["salt"])
                        digest.update(block)
                        next_file.write(digest.digest())
                os.unlink(current_path)
                paths.remove(current_path)
                current_path = next_file.name
                current_digests = block_count
            with open(current_path, "rb") as root:
                verified_root = root.read(digest_size)
                if len(verified_root) != digest_size or root.read(1):
                    raise ValueError("dm-verity root digest spool has invalid size")
            return counts, verified_root, preceding * block_size
    finally:
        for path in paths:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass


def _all_zero(source):
    for chunk in iter(lambda: source.read(1024 * 1024), b""):
        if any(chunk):
            return False
    return True


def project(root_hash_path, partition_metadata_path, root_image_path, hash_image_path):
    root_hash = Path(root_hash_path).read_text().strip().lower()
    partitions = json.loads(Path(partition_metadata_path).read_text())["partitions"]
    by_type = {}
    for partition in partitions:
        by_type.setdefault(partition["type_guid"], []).append(partition)
    roots = by_type.get(ROOT, [])
    hashes = by_type.get(ROOT_VERITY, [])
    if len(roots) not in (1, 2) or len(hashes) not in (1, 2):
        raise ValueError("one or two x86-64 root data and verity hash partitions are required")
    if by_type.get(ROOT_VERITY_SIG):
        raise ValueError("verity signature partitions require signing support tracked by #23")
    root_partition = (
        roots[0]
        if len(roots) == 1
        else next((item for item in roots if item.get("label") != "_empty"), None)
    )
    hash_partition = (
        hashes[0]
        if len(hashes) == 1
        else next((item for item in hashes if item.get("label") != "_empty"), None)
    )
    if root_partition is None or hash_partition is None:
        raise ValueError("A/B layout must retain one populated root and verity partition")
    root_size = os.path.getsize(root_image_path)
    hash_size = os.path.getsize(hash_image_path)
    if root_size > MAX_ARTIFACT_BYTES or hash_size > MAX_ARTIFACT_BYTES:
        raise ValueError("dm-verity artifact exceeds validation resource limit")
    if root_size != root_partition["size_bytes"]:
        raise ValueError("root artifact size does not equal its GPT partition extent")
    if hash_size != hash_partition["size_bytes"]:
        raise ValueError("hash artifact size does not equal its GPT partition extent")
    geometry = _read_superblock(hash_image_path)
    if geometry["data_blocks"] * geometry["data_block_size"] != root_size:
        raise ValueError("dm-verity data geometry does not cover the root artifact exactly")
    tree_offset = geometry["hash_block_size"]
    with open(hash_image_path, "rb") as source:
        header_block = source.read(tree_offset)
        if len(header_block) != tree_offset or any(header_block[SUPERBLOCK_SIZE:]):
            raise ValueError("dm-verity superblock padding is not canonical zero padding")
    levels, verified_root, tree_size = _verify_tree(
        root_image_path, hash_image_path, geometry, tree_offset
    )
    with open(hash_image_path, "rb") as source:
        source.seek(tree_offset + tree_size)
        if not _all_zero(source):
            raise ValueError("hash artifact has nonzero ambiguous trailing bytes")
    verified_root_hex = verified_root.hex()
    if root_hash != verified_root_hex:
        raise ValueError("supplied root hash does not equal the independently verified root")
    return {
        "artifacts": {
            "root": {"sha256": _sha256(root_image_path), "size": root_size},
            "root_hash": {"sha256": _sha256(root_hash_path), "size": os.path.getsize(root_hash_path)},
            "verity": {"sha256": _sha256(hash_image_path), "size": hash_size},
        },
        "data_block_size": geometry["data_block_size"],
        "data_blocks": geometry["data_blocks"],
        "data_partition": root_partition["number"],
        "digest_size": geometry["digest_size"],
        "digest_slot_size": geometry["slot_size"],
        "format_version": "mkosi-verity-metadata-v2",
        "hash_algorithm": geometry["algorithm"],
        "hash_block_size": geometry["hash_block_size"],
        "hash_levels": len(levels),
        "hash_partition": hash_partition["number"],
        "root_hash": root_hash,
        "salt": geometry["salt"].hex(),
        "signature_partition": None,
        "tree_offset": tree_offset,
        "tree_size": tree_size,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root-hash", required=True)
    parser.add_argument("--partition-metadata", required=True)
    parser.add_argument("--root-image", required=True)
    parser.add_argument("--hash-image", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        metadata = project(args.root_hash, args.partition_metadata, args.root_image, args.hash_image)
    except (KeyError, OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit("VERITY_METADATA_INVALID: {}".format(error))
    Path(args.output).write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
