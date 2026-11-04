#!/usr/bin/python3
"""Verify dm-verity split artifacts and project normalized integrity geometry."""

import argparse
import contextlib
import hashlib
import json
import os
import runpy
import struct
import tempfile
from pathlib import Path
from typing import NamedTuple

_load_sibling = runpy.run_path(str(Path(__file__).with_name("sibling_loader.py")))["load_sibling"]
gpt = _load_sibling(__file__, "gpt_partitions")
file_hashing = _load_sibling(__file__, "file_hashing")

MAX_ARTIFACT_BYTES = 16 * 1024**3
MAX_BLOCKS = 1 << 32
MAX_LEVELS = 64
MAX_SPOOL_BYTES = 2 * 1024**3
SUPERBLOCK_SIZE = 512


def _digest_size(algorithm):
    try:
        return hashlib.new(algorithm).digest_size
    except ValueError as error:
        raise ValueError("unsupported dm-verity hash algorithm") from error


def _slot_size(data_block_size, hash_block_size, digest_size):
    """Validates the block sizes and returns the power-of-two slot that holds one digest in a hash block."""
    if data_block_size < 512 or data_block_size > 1024 * 1024 or data_block_size & (data_block_size - 1):
        raise ValueError("invalid dm-verity data block size")
    if hash_block_size < digest_size or hash_block_size > 1024 * 1024 or hash_block_size & (hash_block_size - 1):
        raise ValueError("invalid dm-verity hash block size")
    slot_size = 1 << (digest_size - 1).bit_length()
    if slot_size > hash_block_size or hash_block_size % slot_size:
        raise ValueError("dm-verity digest slots do not divide the hash block")
    return slot_size


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
    digest_size = _digest_size(algorithm)
    slot_size = _slot_size(data_block_size, hash_block_size, digest_size)
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
        "salt": value[88 : 88 + salt_size],
        "superblock": value,
    }


def _salted_digest(geometry, data):
    digest = hashlib.new(geometry["algorithm"])
    digest.update(geometry["salt"])
    digest.update(data)
    return digest.digest()


def _leaf_digests(source_path, geometry, output):
    block_size = geometry["data_block_size"]
    with open(source_path, "rb") as source:
        for _ in range(geometry["data_blocks"]):
            block = source.read(block_size)
            if len(block) != block_size:
                raise ValueError("root artifact is truncated within declared data blocks")
            output.write(_salted_digest(geometry, block))


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


def _check_spool_budget(geometry, counts):
    """Bounds the two digest spools that exist at once: the leaf level and the first hash level."""
    leaf_bytes = geometry["data_blocks"] * geometry["digest_size"]
    next_bytes = counts[0] * geometry["digest_size"] if counts else 0
    if leaf_bytes + next_bytes > MAX_SPOOL_BYTES:
        raise ValueError("dm-verity digest spools exceed the resource limit")


def _level_offsets(counts, tree_offset, block_size):
    """Returns the emitted offset of every level and the tree size; dm-verity stores the top level first."""
    offsets = []
    preceding = 0
    for count in reversed(counts):
        offsets.append(tree_offset + preceding * block_size)
        preceding += count
    offsets.reverse()
    return offsets, preceding * block_size


def _expected_block(current, digests, geometry):
    """Packs the next digests from the current spool into one zero-padded hash block."""
    digest_size = geometry["digest_size"]
    padding = b"\0" * (geometry["slot_size"] - digest_size)
    block = bytearray()
    for _ in range(digests):
        digest = current.read(digest_size)
        if len(digest) != digest_size:
            raise ValueError("dm-verity digest spool is truncated")
        block.extend(digest)
        block.extend(padding)
    block.extend(b"\0" * (geometry["hash_block_size"] - len(block)))
    return block


class _DigestSpool(NamedTuple):
    """A spool file holding the digests of one hash tree level."""

    path: str
    count: int


def _verify_level(level, block_count, below, emitted, geometry, output):
    """Compares one emitted level with the digests of the level below and spools the level's own digests."""
    block_size = geometry["hash_block_size"]
    per_block = block_size // geometry["slot_size"]
    consumed = 0
    with open(below.path, "rb") as current:
        for block_index in range(block_count):
            digests = min(per_block, below.count - consumed)
            block = _expected_block(current, digests, geometry)
            consumed += digests
            if emitted.read(block_size) != block:
                raise ValueError("dm-verity hash mismatch at level {} block {}".format(level, block_index))
            output.write(_salted_digest(geometry, block))


def _read_root_digest(path, digest_size):
    with open(path, "rb") as root:
        verified_root = root.read(digest_size)
        if len(verified_root) != digest_size or root.read(1):
            raise ValueError("dm-verity root digest spool has invalid size")
    return verified_root


def _new_spool(paths):
    spool = _temporary()
    paths.append(spool.name)
    return spool


def _remove_spools(paths):
    for path in paths:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(path)


def _verify_tree(root_image_path, hash_image_path, geometry, tree_offset):
    """Recomputes every hash level from the root artifact and compares it with the emitted hash tree."""
    block_size = geometry["hash_block_size"]
    counts = _level_counts(geometry["data_blocks"], block_size // geometry["slot_size"])
    _check_spool_budget(geometry, counts)
    level_offsets, tree_size = _level_offsets(counts, tree_offset, block_size)
    paths = []
    try:
        leaf = _new_spool(paths)
        with leaf:
            _leaf_digests(root_image_path, geometry, leaf)
        below = _DigestSpool(leaf.name, geometry["data_blocks"])
        with open(hash_image_path, "rb") as emitted:
            for level, (block_count, emitted_offset) in enumerate(zip(counts, level_offsets, strict=True)):
                spool = _new_spool(paths)
                with spool:
                    emitted.seek(emitted_offset)
                    _verify_level(level, block_count, below, emitted, geometry, spool)
                os.unlink(below.path)
                paths.remove(below.path)
                below = _DigestSpool(spool.name, block_count)
        return counts, _read_root_digest(below.path, geometry["digest_size"]), tree_size
    finally:
        _remove_spools(paths)


def _all_zero(source):
    return not any(any(chunk) for chunk in iter(lambda: source.read(1024 * 1024), b""))


def _root_partitions(partition_metadata_path):
    """Returns the populated root data and verity hash partitions; inactive A/B slots are ignored."""
    partitions = json.loads(Path(partition_metadata_path).read_text())["partitions"]
    by_type = {}
    slot_types = (gpt.ROOT_X86_64, gpt.ROOT_X86_64_VERITY)
    for partition in partitions:
        if partition.get("label") == gpt.EMPTY_SLOT_LABEL and partition["type_guid"] in slot_types:
            continue
        by_type.setdefault(partition["type_guid"], []).append(partition)
    if len(by_type.get(gpt.ROOT_X86_64, [])) != 1 or len(by_type.get(gpt.ROOT_X86_64_VERITY, [])) != 1:
        raise ValueError("exactly one x86-64 root data and verity hash partition is required")
    if by_type.get(gpt.ROOT_X86_64_VERITY_SIG):
        raise ValueError("verity signature partitions require signing support tracked by #23")
    return by_type[gpt.ROOT_X86_64][0], by_type[gpt.ROOT_X86_64_VERITY][0]


def _artifact_sizes(root_image_path, hash_image_path, root_partition, hash_partition):
    root_size = os.path.getsize(root_image_path)
    hash_size = os.path.getsize(hash_image_path)
    if root_size > MAX_ARTIFACT_BYTES or hash_size > MAX_ARTIFACT_BYTES:
        raise ValueError("dm-verity artifact exceeds validation resource limit")
    if root_size != root_partition["size_bytes"]:
        raise ValueError("root artifact size does not equal its GPT partition extent")
    if hash_size != hash_partition["size_bytes"]:
        raise ValueError("hash artifact size does not equal its GPT partition extent")
    return root_size, hash_size


def _check_superblock_padding(hash_image_path, tree_offset):
    with open(hash_image_path, "rb") as source:
        header_block = source.read(tree_offset)
        if len(header_block) != tree_offset or any(header_block[SUPERBLOCK_SIZE:]):
            raise ValueError("dm-verity superblock padding is not canonical zero padding")


def _check_zero_trailer(hash_image_path, offset):
    with open(hash_image_path, "rb") as source:
        source.seek(offset)
        if not _all_zero(source):
            raise ValueError("hash artifact has nonzero ambiguous trailing bytes")


def _artifact(path, size):
    return {"sha256": file_hashing.sha256_file(path), "size": size}


def project(root_hash_path, partition_metadata_path, root_image_path, hash_image_path):
    root_hash = Path(root_hash_path).read_text().strip().lower()
    root_partition, hash_partition = _root_partitions(partition_metadata_path)
    root_size, hash_size = _artifact_sizes(root_image_path, hash_image_path, root_partition, hash_partition)
    geometry = _read_superblock(hash_image_path)
    if geometry["data_blocks"] * geometry["data_block_size"] != root_size:
        raise ValueError("dm-verity data geometry does not cover the root artifact exactly")
    tree_offset = geometry["hash_block_size"]
    _check_superblock_padding(hash_image_path, tree_offset)
    levels, verified_root, tree_size = _verify_tree(root_image_path, hash_image_path, geometry, tree_offset)
    _check_zero_trailer(hash_image_path, tree_offset + tree_size)
    if root_hash != verified_root.hex():
        raise ValueError("supplied root hash does not equal the independently verified root")
    return {
        "artifacts": {
            "root": _artifact(root_image_path, root_size),
            "root_hash": _artifact(root_hash_path, os.path.getsize(root_hash_path)),
            "verity": _artifact(hash_image_path, hash_size),
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
        raise SystemExit("VERITY_METADATA_INVALID: {}".format(error)) from error
    Path(args.output).write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
