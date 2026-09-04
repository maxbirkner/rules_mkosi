"""Validate and project immutable systemd-sysupdate A/B artifacts."""

import argparse
import hashlib
import json
import pathlib
import re

ROOT_TYPE = "4f68bce3-e8cd-4db1-96e7-fbcaf984b709"
VERITY_TYPE = "2c7357ed-ebd2-46d9-aec1-23d437ec2bf5"
ALIGNMENT = 1024 * 1024
VERSION = re.compile(r"^[0-9][0-9A-Za-z._+-]*$")


def _digest(path):
    value = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def project(slots, boot_attempts):
    if set(slots) != {"a", "b"}:
        raise ValueError("exactly slots a and b are required")
    if boot_attempts < 1:
        raise ValueError("boot_attempts must be positive")
    ranges = []
    output_slots = {}
    versions = set()
    for name in ("a", "b"):
        slot = slots[name]
        version = slot["version"]
        if not VERSION.fullmatch(version):
            raise ValueError("invalid slot {} version".format(name))
        versions.add(version)
        partitions = []
        for role, type_guid in (("root", ROOT_TYPE), ("verity", VERITY_TYPE)):
            item = slot[role]
            offset, size = item["offset"], item["size"]
            if offset % ALIGNMENT or size <= 0 or size % ALIGNMENT:
                raise ValueError("{}-{} is not MiB aligned".format(role, name))
            ranges.append((offset, offset + size, "{}-{}".format(role, name)))
            partitions.append({
                "label_pattern": "{}-@v".format(role),
                "offset": offset,
                "role": role,
                "size": size,
                "type_guid": type_guid,
            })
        output_slots[name] = {
            "boot_entry_pattern": "rules-mkosi_@v+@l-@d.efi",
            "partitions": partitions,
            "version": version,
        }
    if len(versions) != 2:
        raise ValueError("slot versions must differ")
    for role in ("root", "verity"):
        sizes = {slots[name][role]["size"] for name in ("a", "b")}
        if len(sizes) != 1:
            raise ValueError("{} slots are not symmetric".format(role))
    for current, following in zip(sorted(ranges), sorted(ranges)[1:]):
        if current[1] > following[0]:
            raise ValueError("{} overlaps {}".format(current[2], following[2]))
    return {
        "boot": {
            "attempts": boot_attempts,
            "assessment": "systemd-boot",
            "entry_pattern": "rules-mkosi_@v+@l-@d.efi",
            "success_commit": "systemd-bless-boot.service",
        },
        "firmware": "uefi",
        "format_version": "rules-mkosi-sysupdate-ab-v1",
        "slots": output_slots,
        "systemd_version": "257.7-1",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    spec = json.loads(pathlib.Path(arguments.spec).read_text(encoding="utf-8"))
    projection = project(spec["slots"], spec["boot_attempts"])
    artifacts = {}
    for slot_name in ("a", "b"):
        artifacts[slot_name] = {}
        for role, path in spec["artifacts"][slot_name].items():
            artifacts[slot_name][role] = {
                "sha256": _digest(path),
                "size": pathlib.Path(path).stat().st_size,
            }
    projection["artifacts"] = artifacts
    pathlib.Path(arguments.output).write_text(
        json.dumps(projection, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
