"""Run a writable two-boot systemd-sysupdate lifecycle under QEMU/OVMF."""

import hashlib
import importlib.util
import json
import os
import pathlib
import shutil
import sys


def _load(name):
    path = pathlib.Path(__file__).with_name(name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


boot = _load("boot_test")
gpt = _load("partition_metadata")


def _partition_digests(path):
    result = {}
    with open(path, "rb") as image:
        for partition in gpt.project_image(path)["partitions"]:
            image.seek(partition["start_bytes"])
            remaining = partition["size_bytes"]
            digest = hashlib.sha256()
            while remaining:
                chunk = image.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise RuntimeError("short partition read")
                digest.update(chunk)
                remaining -= len(chunk)
            result[str(partition["number"])] = {
                "label": partition["label"],
                "sha256": digest.hexdigest(),
                "type_guid": partition["type_guid"],
            }
    return result


def _run(config, disk, scratch, marker, expected_failure_marker=""):
    old = os.environ.get("TEST_TMPDIR")
    os.environ["TEST_TMPDIR"] = str(scratch)
    try:
        update_payload = boot._resolve_runfile(config["update_payload"])
        boot._boot(
            disk,
            boot._resolve_runfile(config["qemu"]),
            boot._resolve_runfile(config["system_data"]),
            qemu_args=config["qemu_args"]
            + [
                "-fsdev",
                "local,id=updates,path={},security_model=none,readonly=on".format(
                    update_payload
                ),
                "-device",
                "virtio-9p-pci,fsdev=updates,mount_tag=rules_mkosi_updates",
            ],
            firmware_code=boot._resolve_runfile(config["firmware_code"]),
            firmware_vars=boot._resolve_runfile(config["firmware_vars"]),
            kernel_preflight=boot._resolve_runfile(config["kernel_preflight"]),
            readiness_marker=marker,
            expected_failure_marker=expected_failure_marker,
            shutdown_markers=config["shutdown_markers"],
            boot_timeout_seconds=config["boot_timeout_seconds"],
            qmp_initialization_timeout_seconds=config[
                "qmp_initialization_timeout_seconds"
            ],
            shutdown_timeout_seconds=config["shutdown_timeout_seconds"],
            diagnostic_bytes=config["diagnostic_bytes"],
            snapshot=False,
        )
    finally:
        if old is None:
            os.environ.pop("TEST_TMPDIR", None)
        else:
            os.environ["TEST_TMPDIR"] = old


def main():
    config = json.loads(pathlib.Path(boot._resolve_runfile(sys.argv[1])).read_text())
    state = pathlib.Path(os.environ["TEST_TMPDIR"])
    disk = state / "release-ab.raw"
    shutil.copyfile(boot._resolve_runfile(config["image"]), disk)
    before = _partition_digests(disk)
    with open(disk, "ab") as image:
        image.truncate(image.tell() + 1280 * 1024 * 1024)
    disk.chmod(0o600)
    _run(config, disk, state / "update-boot", "RULES_MKOSI_SYSUPDATE_APPLIED_VERSION=2")
    after = _partition_digests(disk)

    changed = [
        key
        for key in sorted(set(before) | set(after))
        if key not in before
        or key not in after
        or before[key]["sha256"] != after[key]["sha256"]
    ]
    changed_labels = {after[key]["label"] for key in changed}
    if "root-2" not in changed_labels or "verity-2" not in changed_labels:
        raise RuntimeError(
            "systemd-sysupdate did not mutate both inactive partitions: {}".format(
                sorted(changed_labels)
            )
        )
    for key, value in before.items():
        if value["label"] in ("root-1", "verity-1") and key in changed:
            raise RuntimeError("active A partition changed: {}".format(value["label"]))

    rollback = len(sys.argv) == 3 and sys.argv[2] == "--rollback"
    if rollback:
        for attempt in range(1, 4):
            _run(
                config,
                disk,
                state / "failed-slot-b-{}".format(attempt),
                "RULES_MKOSI_SLOT_B_VERSION=2",
                "Welcome to emergency mode!",
            )
        _run(
            config,
            disk,
            state / "rollback-slot-a",
            "RULES_MKOSI_ROLLBACK_SLOT_A_VERSION=1",
        )
    else:
        _run(config, disk, state / "slot-b-boot", "RULES_MKOSI_SLOT_B_VERSION=2")
    evidence = {
        "after": after,
        "before": before,
        "changed_partition_numbers": changed,
        "format_version": "rules-mkosi-sysupdate-vm-evidence-v1",
    }
    output = pathlib.Path(os.environ.get("TEST_UNDECLARED_OUTPUTS_DIR", state))
    output.mkdir(parents=True, exist_ok=True)
    (output / "sysupdate-evidence.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    )
    if rollback:
        print("systemd-boot exhausted slot B attempts and rolled back to slot A")
    else:
        print("systemd-sysupdate inactive-slot mutation and slot B boot verified")


if __name__ == "__main__":
    main()
