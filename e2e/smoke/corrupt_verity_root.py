#!/usr/bin/python3
"""Corrupt the root filesystem payload without changing GPT or verity hashes."""

import argparse
import json
import shutil

ROOT_X86_64 = "4f68bce3-e8cd-4db1-96e7-fbcaf984b709"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--partitions", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    metadata = json.load(open(args.partitions, encoding="utf-8"))
    roots = [p for p in metadata["partitions"] if p["type_guid"] == ROOT_X86_64]
    if len(roots) != 1:
        raise SystemExit("expected exactly one x86-64 root partition")
    shutil.copyfile(args.image, args.output)
    offset = roots[0]["start_bytes"] + 1024
    with open(args.output, "r+b") as image:
        image.seek(offset)
        original = image.read(1)
        if len(original) != 1:
            raise SystemExit("root filesystem corruption offset is outside image")
        image.seek(offset)
        image.write(bytes([original[0] ^ 1]))


if __name__ == "__main__":
    main()
