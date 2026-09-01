#!/usr/bin/python3
"""Project and validate an sfdisk GPT description."""

import argparse
import json
import subprocess
from pathlib import Path

ROOT_X86_64 = "4f68bce3-e8cd-4db1-96e7-fbcaf984b709"
ALIGNMENT = 1024 * 1024


def project(table):
    partition_table = table.get("partitiontable", {})
    if partition_table.get("label") != "gpt":
        raise ValueError("partition table must use GPT")
    sector_size = partition_table.get("sectorsize")
    if not isinstance(sector_size, int) or sector_size <= 0:
        raise ValueError("partition table has no valid sector size")

    result = []
    previous_end = None
    for number, partition in enumerate(partition_table.get("partitions", []), 1):
        start = partition.get("start")
        size = partition.get("size")
        if not isinstance(start, int) or not isinstance(size, int) or size <= 0:
            raise ValueError("partition {} has invalid geometry".format(number))
        start_bytes = start * sector_size
        size_bytes = size * sector_size
        if start_bytes % ALIGNMENT:
            raise ValueError("partition {} is not 1 MiB aligned".format(number))
        if previous_end is not None and start_bytes < previous_end:
            raise ValueError("partition {} overlaps or is out of order".format(number))
        previous_end = start_bytes + size_bytes
        result.append(
            {
                "label": partition.get("name", ""),
                "number": number,
                "size_bytes": size_bytes,
                "start_bytes": start_bytes,
                "type_guid": str(partition.get("type", "")).lower(),
            }
        )

    roots = [entry for entry in result if entry["type_guid"] == ROOT_X86_64]
    if len(roots) != 1:
        raise ValueError("exactly one Linux x86-64 root partition is required")
    if roots[0]["label"] != "root-x86-64":
        raise ValueError("Linux x86-64 root partition label must be root-x86-64")
    return {
        "format_version": "mkosi-partition-metadata-v1",
        "partitions": result,
        "sector_size": sector_size,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--launcher", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    completed = subprocess.run(
        [
            args.launcher,
            "--ro-bind={}".format(Path(args.image).resolve()) + ":/inputs/image",
            "sfdisk",
            "--json",
            "/inputs/image",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    metadata = project(json.loads(completed.stdout))
    Path(args.output).write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
