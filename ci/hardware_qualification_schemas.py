"""Generates the hardware qualification schemas and the tables of docs/hardware-qualification.md.

The class, Secure Boot state, and check tables below are the single source of both JSON Schemas and of the generated
tables between the markers in the document. Without arguments, the script fails if a committed file differs from its
generated content; `--write` regenerates them. The output matches the layout of the pretty-format-json hook.
"""

import argparse
import dataclasses
import json
import pathlib
import re
import sys
from collections.abc import Sequence
from typing import Any

DOC = "docs/hardware-qualification.md"
RESULT_SCHEMA = "docs/hardware-qualification-result.schema.json"
SIGNOFF_SCHEMA = "docs/hardware-qualification-signoff.schema.json"
SCHEMA_BASE = "https://github.com/maxbirkner/rules_mkosi/blob/main/"

TRANSPORTS = {"nvme": "NVMe", "sata": "SATA", "mmc": "eMMC", "usb": "USB"}
# Network and console kinds, with their table label and the check that each requires.
NETWORKS = {"wired": ("Wired", "network-wired"), "wifi": ("Wi-Fi", "network-wifi")}
CONSOLES = {"serial": ("Serial", "console-serial"), "graphical": ("Graphical", "console-graphical")}
TPM2 = {
    "present": ("Present", ("firmware", "discrete")),
    "absent": ("Absent", ("absent",)),
    "any": ("Any", ("firmware", "discrete", "absent")),
}


@dataclasses.dataclass(frozen=True)
class HardwareClass:
    name: str
    machine: str
    generation: str
    tier: str
    boot_mode: str
    secure_boot: tuple[str, ...]
    transports: tuple[str, ...]
    network: tuple[str, ...]
    network_note: str
    consoles: tuple[str, ...]
    console_note: str
    tpm2: str


CLASSES = (
    HardwareClass(
        "uefi-modern-desktop",
        "Desktop, small form factor, or mini PC with a plug-in GPU or NIC",
        "2019 or newer",
        "uefi",
        "uefi",
        ("disabled", "setup-mode", "custom-keys"),
        ("nvme",),
        ("wired",),
        "",
        ("graphical",),
        "",
        "present",
    ),
    HardwareClass(
        "uefi-mobile-apu",
        "Laptop or handheld with an AMD APU or Intel mobile SoC",
        "2020 or newer",
        "uefi",
        "uefi",
        ("disabled", "setup-mode"),
        ("nvme",),
        ("wifi",),
        "with firmware",
        ("graphical",),
        "internal display",
        "present",
    ),
    HardwareClass(
        "uefi-embedded-headless",
        "Fanless industrial box without display",
        "2016 or newer",
        "uefi",
        "uefi",
        ("setup-mode", "custom-keys"),
        ("mmc", "sata"),
        ("wired",),
        "several ports",
        ("serial",),
        "",
        "any",
    ),
    HardwareClass(
        "uefi-older-generation",
        "Office desktop of an early UEFI generation",
        "2012 to 2018",
        "uefi",
        "uefi",
        ("disabled", "microsoft-factory-keys"),
        ("sata",),
        ("wired",),
        "",
        ("graphical",),
        "",
        "absent",
    ),
    HardwareClass(
        "uefi-removable-usb",
        "Any UEFI machine starting from the removable-media path",
        "Any",
        "uefi",
        "uefi",
        ("disabled",),
        ("usb",),
        ("wired",),
        "",
        ("graphical",),
        "",
        "any",
    ),
    HardwareClass(
        "bios-legacy-only",
        "Desktop without UEFI",
        "2006 to 2012",
        "bios",
        "bios",
        ("not-applicable",),
        ("sata",),
        ("wired",),
        "",
        ("graphical",),
        "VGA text, serial if present",
        "absent",
    ),
    HardwareClass(
        "bios-csm",
        "UEFI machine booting through its Compatibility Support Module",
        "2012 to 2020",
        "bios",
        "csm",
        ("not-applicable",),
        ("sata",),
        ("wired",),
        "",
        ("graphical",),
        "",
        "any",
    ),
)

# Each state: name, firmware before the first boot, image, and expected result.
SECURE_BOOT_STATES = (
    (
        "disabled",
        "Secure Boot off",
        "Unsigned UEFI release image",
        "Boots; `bootctl status` reports Secure Boot disabled.",
    ),
    (
        "setup-mode",
        "Secure Boot on, no PK enrolled",
        "[`secure_boot_signed_image`](secure-boot.md#signed-disk-images-and-key-auto-enrollment) with "
        '`auto_enroll_keys` and `secure_boot_enroll = "force"`',
        "systemd-boot enrolls the keys and resets; then Secure Boot is enforced.",
    ),
    (
        "custom-keys",
        "Qualification PK, KEK, and db already enrolled",
        "`secure_boot_signed_image` without `auto_enroll_keys`",
        "Signed binaries boot; an unsigned UKI is refused.",
    ),
    (
        "microsoft-factory-keys",
        "Vendor default keys",
        "`secure_boot_signed_image` without `auto_enroll_keys`",
        "The firmware refuses the custom-signed systemd-boot, which proves enforcement and the need for enrollment.",
    ),
    (
        "not-applicable",
        "BIOS or CSM boot, Secure Boot off",
        "BIOS release image",
        "Secure Boot does not apply.",
    ),
)
STATES = tuple(state[0] for state in SECURE_BOOT_STATES)
FACTORY_KEYS = "microsoft-factory-keys"
SIGNED_STATES = ("setup-mode", "custom-keys", FACTORY_KEYS)
# States that boot rules_mkosi's own signed binaries, so an update with an unsigned UKI must be refused.
ENFORCING_STATES = ("setup-mode", "custom-keys")
AUTO_ENROLL_KEYS = ("PK.auth", "KEK.auth", "db.auth")
# The only checks that a factory-keys run can perform, because nothing else boots.
FACTORY_KEY_CHECKS = ("artifact-digest", "identity", "secure-boot-enforcement")


@dataclasses.dataclass(frozen=True)
class Check:
    id: str
    # always, uefi, network, console, states (`values` are states), or class-states (`values` are class, *states).
    when: str
    passes: str
    values: tuple[str, ...] = ()


CHECKS = (
    Check(
        "artifact-digest",
        "always",
        "`sha256sum` of the written file and of the device read back to the file's size match `written_sha256`.",
    ),
    Check("identity", "always", "`/sys/class/dmi/id/` and `/proc/cpuinfo` values are recorded in `machine`."),
    Check(
        "firmware-boot",
        "always",
        "The firmware starts the boot loader from the boot disk without a manually created boot entry.",
    ),
    Check(
        "boot-chain",
        "always",
        "`uefi`: `bootctl status` reports systemd-boot and the UKI's systemd-stub. "
        "`bios`: `/sys/firmware/efi` is absent and the console shows GRUB.",
    ),
    Check("boot-to-userspace", "always", "`systemctl is-system-running --wait` prints `running`."),
    Check(
        "storage",
        "always",
        "`lsblk -d -o NAME,TRAN,MODEL` shows the class's transport for the boot disk, "
        "and `journalctl -k -p err` has no storage errors.",
    ),
    Check(
        "reboot-poweroff",
        "always",
        "`systemctl reboot` and `systemctl poweroff` complete within two minutes each.",
    ),
    Check("tpm2", "always", "`systemd-creds has-tpm2` matches `machine.tpm2`, and boot does not depend on the TPM."),
    Check(
        "verity-root",
        "uefi",
        "`findmnt -no SOURCE,OPTIONS /` shows a read-only `/dev/mapper/` device, "
        "and `/proc/cmdline` contains `roothash=`.",
    ),
    Check(
        "ab-update",
        "uefi",
        "Release N+1 installs with `systemd-sysupdate` and is blessed, and release N+2, whose health check fails, "
        "rolls back to N+1, as in [boot assessment](sysupdate-ab.md#boot-assessment-and-rollback).",
    ),
    Check(
        "network-wired",
        "network",
        "The interface is `routable` in `networkctl status`; for `uefi`, the `ab-update` releases download "
        "[over HTTP](sysupdate-ab.md#updates-over-http) through it.",
        ("wired",),
    ),
    Check(
        "network-wifi",
        "network",
        "`journalctl -k` shows the firmware loaded without errors, "
        "and the interface is `routable` on a test access point.",
        ("wifi",),
    ),
    Check(
        "console-serial",
        "console",
        "The serial capture shows boot loader, kernel, and login prompt.",
        ("serial",),
    ),
    Check(
        "console-graphical",
        "console",
        "The display shows the boot menu, kernel output, and login prompt; attach a photo or recording.",
        ("graphical",),
    ),
    Check("secure-boot-state", "uefi", "`bootctl status` reports the state that the run expects."),
    Check(
        "secure-boot-enrollment",
        "states",
        "The console shows `Custom Secure Boot keys successfully enrolled`, "
        "and the next boot reports Secure Boot `enabled (user)`.",
        ("setup-mode",),
    ),
    Check(
        "secure-boot-enforcement",
        "states",
        "`setup-mode`, `custom-keys`: release N+3 with an unsigned UKI is refused, systemd-boot logs "
        "`Error loading …: Access denied`, and N+1 boots after one reset, as in "
        "[refused releases](secure-boot.md#releases-that-the-firmware-refuses). "
        "`microsoft-factory-keys`: the firmware refuses the custom-signed systemd-boot itself and shows its "
        "Secure Boot violation screen; attach a photo.",
        SIGNED_STATES,
    ),
    Check(
        "option-rom",
        "class-states",
        "Display and network of the plug-in card work with Secure Boot enforced.",
        ("uefi-modern-desktop", "setup-mode", "custom-keys"),
    ),
)
CHECK_IDS = tuple(check.id for check in CHECKS)

JSON = dict[str, Any]
SHA256: JSON = {"$ref": "#/$defs/sha256"}
NONEMPTY: JSON = {"$ref": "#/$defs/nonempty_string"}


def checks_when(when: str) -> list[str]:
    """Returns the IDs of the checks with the given `when`."""
    return [check.id for check in CHECKS if check.when == when]


def required_checks(hardware_class: HardwareClass, state: str) -> list[str]:
    """Returns the checks that a passed run of the class in the Secure Boot state requires, in table order."""
    if state == FACTORY_KEYS:
        return [check for check in CHECK_IDS if check in FACTORY_KEY_CHECKS]
    dimensions = {NETWORKS[kind][1] for kind in hardware_class.network}
    dimensions |= {CONSOLES[kind][1] for kind in hardware_class.consoles}
    required = []
    for check in CHECKS:
        if (
            check.when == "always"
            or (check.when == "uefi" and hardware_class.tier == "uefi")
            or (check.when in ("network", "console") and check.id in dimensions)
            or (check.when == "states" and state in check.values)
            or (check.when == "class-states" and hardware_class.name == check.values[0] and state in check.values[1:])
        ):
            required.append(check.id)
    return required


def expected_payloads(hardware_class: HardwareClass, state: str) -> list[str]:
    """Returns the update results that a passed run of the class in the Secure Boot state must record."""
    if hardware_class.tier != "uefi" or state == FACTORY_KEYS:
        return []
    return ["blessed", "rolled-back"] + (["refused"] if state in ENFORCING_STATES else [])


def enum(values: Any) -> JSON:
    values = list(values)
    return {"const": values[0]} if len(values) == 1 else {"enum": values}


def obj(properties: JSON, required: Any = (), **extra: Any) -> JSON:
    result: JSON = {"type": "object", "additionalProperties": False, "properties": properties}
    if required:
        result["required"] = list(required)
    result.update(extra)
    return result


def array(items: JSON, **extra: Any) -> JSON:
    return {"type": "array", "items": items, **extra}


def when(**conditions: Any) -> JSON:
    """Matches records whose class, outcome, and firmware fields have the given values; `not_secure_boot` negates."""
    parts = []
    for key, values in conditions.items():
        if key == "not_secure_boot":
            parts.append({"properties": {"firmware": {"properties": {"secure_boot": {"not": enum(values)}}}}})
        elif key in ("secure_boot", "tier"):
            parts.append({"properties": {"firmware": {"properties": {key: enum(values)}}}})
        else:
            parts.append({"properties": {key: enum(values)}})
    return parts[0] if len(parts) == 1 else {"allOf": parts}


def passed_checks(ids: Any) -> JSON:
    ids = list(ids)
    passed = {check: {"$ref": "#/$defs/passed_check"} for check in ids}
    return {"properties": {"checks": {"required": ids, "properties": passed}}}


def payloads_expected(*expected: str) -> JSON:
    contains = [{"contains": {"properties": {"expected": {"const": value}}}} for value in expected]
    return {
        "properties": {
            "subject": {"required": ["update_payloads"], "properties": {"update_payloads": {"allOf": contains}}}
        }
    }


def some_check(definition: str) -> JSON:
    """Matches records with at least one check that matches the definition: not every check fails to match it."""
    return {"properties": {"checks": {"not": {"additionalProperties": {"not": {"$ref": definition}}}}}}


def class_rules() -> list[JSON]:
    """Ties each class to its tier, boot mode, Secure Boot states, boot disk transports, and TPM2 presence."""
    rules = []
    for hardware_class in CLASSES:
        firmware = {
            "tier": enum([hardware_class.tier]),
            "boot_mode": enum([hardware_class.boot_mode]),
            "secure_boot": enum(hardware_class.secure_boot),
        }
        machine = {
            "boot_disk": {"properties": {"transport": enum(hardware_class.transports)}},
            "tpm2": enum(TPM2[hardware_class.tpm2][1]),
        }
        rules.append(
            {
                "if": when(**{"class": [hardware_class.name]}),
                "then": {"properties": {"firmware": {"properties": firmware}, "machine": {"properties": machine}}},
            }
        )
    return rules


def signed_image_rules() -> list[JSON]:
    """Requires the signed binaries of Secure Boot runs and the key files of auto-enrollment."""
    keys = [{"contains": {"properties": {"name": {"const": key}}}} for key in AUTO_ENROLL_KEYS]
    signed: JSON = {
        "required": ["signed_binaries", "signed_image_record_sha256"],
        "properties": {"signed_binaries": {"minItems": 1}},
    }
    enrolled = {"required": ["auto_enroll_keys"], "properties": {"auto_enroll_keys": {"allOf": keys}}}
    return [
        {"if": when(secure_boot=SIGNED_STATES), "then": {"properties": {"subject": {"properties": {"image": signed}}}}},
        {
            "if": when(secure_boot=["setup-mode"]),
            "then": {"properties": {"subject": {"properties": {"image": enrolled}}}},
        },
    ]


def passed_rules() -> list[JSON]:
    """Requires every check that the tier, class, and Secure Boot state demand for a passed outcome."""
    not_failed = {"additionalProperties": {"properties": {"status": {"enum": ["passed", "not-applicable"]}}}}
    rules = [
        {"if": when(outcome=["passed"]), "then": {"properties": {"checks": not_failed}}},
        {"if": when(outcome=["passed"], not_secure_boot=[FACTORY_KEYS]), "then": passed_checks(checks_when("always"))},
        {"if": when(outcome=["passed"], secure_boot=[FACTORY_KEYS]), "then": passed_checks(FACTORY_KEY_CHECKS)},
        {
            "if": when(outcome=["passed"], tier=["uefi"], not_secure_boot=[FACTORY_KEYS]),
            "then": {"allOf": [passed_checks(checks_when("uefi")), payloads_expected("blessed", "rolled-back")]},
        },
        {"if": when(outcome=["passed"], secure_boot=ENFORCING_STATES), "then": payloads_expected("refused")},
    ]
    for check in CHECKS:
        if check.when == "states":
            states = [state for state in check.values if state != FACTORY_KEYS]
            rules.append({"if": when(outcome=["passed"], secure_boot=states), "then": passed_checks([check.id])})
        elif check.when == "class-states":
            condition = when(outcome=["passed"], secure_boot=check.values[1:], **{"class": [check.values[0]]})
            rules.append({"if": condition, "then": passed_checks([check.id])})
    for hardware_class in CLASSES:
        dimensions = [NETWORKS[kind][1] for kind in hardware_class.network]
        dimensions += [CONSOLES[kind][1] for kind in hardware_class.consoles]
        condition = when(outcome=["passed"], not_secure_boot=[FACTORY_KEYS], **{"class": [hardware_class.name]})
        rules.append({"if": condition, "then": passed_checks(dimensions)})
    return rules


def outcome_rules() -> list[JSON]:
    """`failed` needs a failed check that does not invalidate the run, and `invalid` needs one that does."""
    failed = some_check("#/$defs/failed_check")
    invalidating = some_check("#/$defs/invalidating_check")
    return [
        {"if": when(outcome=["failed"]), "then": {"allOf": [failed, {"not": invalidating}]}},
        {"if": when(outcome=["invalid"]), "then": invalidating},
    ]


def subject_schema() -> JSON:
    signed_binary = obj(
        {
            "esp_path": {"type": "string", "description": "Empty for the UKI, as in the signing request."},
            "sha256": SHA256,
        },
        ["esp_path", "sha256"],
    )
    key = obj({"name": {"enum": [*AUTO_ENROLL_KEYS, "dbx.auth"]}, "sha256": SHA256}, ["name", "sha256"])
    image = obj(
        {
            "reproducibility_manifest_sha256": SHA256,
            "canonical_sha256": SHA256,
            "written_sha256": SHA256,
            "signed_image_record_sha256": SHA256,
            "signed_binaries": array(signed_binary),
            "auto_enroll_keys": array(key),
        },
        ["reproducibility_manifest_sha256", "canonical_sha256", "written_sha256"],
    )
    payload = obj(
        {
            "version": {"type": "string", "pattern": "^[A-Za-z0-9.]+$"},
            "sha256sums_sha256": SHA256,
            "expected": {"enum": ["blessed", "rolled-back", "refused"]},
        },
        ["version", "sha256sums_sha256", "expected"],
    )
    rules_mkosi = obj(
        {
            "commit": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
            "version": {"type": "string", "pattern": "^[0-9]+\\.[0-9]+\\.[0-9]+$"},
            "archive_sha256": SHA256,
        },
        ["commit"],
    )
    return obj(
        {"rules_mkosi": rules_mkosi, "image": image, "update_payloads": array(payload)}, ["rules_mkosi", "image"]
    )


def machine_schema() -> JSON:
    required_dmi = ("sys_vendor", "product_name", "bios_vendor", "bios_version", "bios_date")
    optional_dmi = ("product_version", "board_vendor", "board_name")
    dmi = {name: NONEMPTY for name in required_dmi} | {name: {"type": "string"} for name in optional_dmi}
    network = obj(
        {"kind": {"enum": list(NETWORKS)}, "driver": NONEMPTY, "firmware": array(NONEMPTY)},
        ["kind", "driver"],
    )
    return obj(
        {
            "dmi": obj(dmi, required_dmi),
            "cpu": NONEMPTY,
            "boot_disk": obj({"transport": {"enum": list(TRANSPORTS)}, "model": NONEMPTY}, ["transport", "model"]),
            "network": array(network),
            "consoles": array({"enum": list(CONSOLES)}, minItems=1, uniqueItems=True),
            "tpm2": {"enum": list(TPM2["any"][1])},
        },
        ["dmi", "cpu", "boot_disk", "network", "consoles", "tpm2"],
    )


def firmware_schema() -> JSON:
    return obj(
        {
            "tier": {"enum": ["uefi", "bios"]},
            "boot_mode": {"enum": ["uefi", "csm", "bios"]},
            "secure_boot": {"enum": list(STATES)},
            "db_includes_microsoft_uefi_ca": {"type": "boolean"},
            "settings": array(NONEMPTY),
        },
        ["tier", "boot_mode", "secure_boot"],
    )


def check_schema() -> JSON:
    def status_is(status: str) -> JSON:
        return {"properties": {"status": {"const": status}}}

    return obj(
        {
            "status": {"enum": ["passed", "failed", "not-applicable"]},
            "logs": array({"$ref": "#/$defs/log"}),
            "failure": {"$ref": "#/$defs/failure"},
            "notes": {"type": "string"},
        },
        ["status", "logs"],
        allOf=[
            {"if": status_is("failed"), "then": {"required": ["failure"], "properties": {"logs": {"minItems": 1}}}},
            {
                "if": status_is("passed"),
                "then": {"not": {"required": ["failure"]}, "properties": {"logs": {"minItems": 1}}},
            },
            {"if": status_is("not-applicable"), "then": {"not": {"required": ["failure"]}}},
        ],
    )


FAILURE_CATEGORIES = (
    "provisioning",
    "firmware-boot",
    "secure-boot",
    "boot-loader",
    "kernel-initrd",
    "root-integrity",
    "storage",
    "network",
    "console",
    "update-rollback",
    "tpm",
    "power-state",
    "hardware-fault",
)
ATTRIBUTIONS = ("rules-mkosi", "image-configuration", "firmware", "hardware", "procedure")
# Attributions that make a run invalid, so it must be repeated.
INVALIDATING = ("procedure", "hardware")


def result_defs() -> JSON:
    failure = obj(
        {
            "category": {"enum": list(FAILURE_CATEGORIES)},
            "attribution": {"enum": list(ATTRIBUTIONS)},
            "summary": NONEMPTY,
            "issue": {"type": "string", "format": "uri"},
        },
        ["category", "attribution", "summary"],
        **{
            "if": {"properties": {"category": {"const": "hardware-fault"}}},
            "then": {"properties": {"attribution": {"const": "hardware"}}},
        },
    )
    invalidating_failure = {"properties": {"attribution": {"enum": list(INVALIDATING)}}}
    log_path = {"type": "string", "pattern": "^logs/[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$"}
    return {
        "check": check_schema(),
        "failure": failure,
        "failed_check": {"properties": {"status": {"const": "failed"}}},
        "invalidating_check": {"properties": {"status": {"const": "failed"}, "failure": invalidating_failure}},
        "passed_check": {"properties": {"status": {"const": "passed"}}},
        "log": obj({"path": log_path, "sha256": SHA256}, ["path", "sha256"]),
        "nonempty_string": {"type": "string", "minLength": 1},
        "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    }


def result_schema() -> JSON:
    """Returns the schema of one qualification run."""
    properties = {
        "format_version": {"const": "rules-mkosi-hardware-qualification-result-v1"},
        "class": {"enum": [hardware_class.name for hardware_class in CLASSES]},
        "subject": subject_schema(),
        "machine": machine_schema(),
        "firmware": firmware_schema(),
        "operator": NONEMPTY,
        "started_at": {"type": "string", "format": "date-time"},
        "finished_at": {"type": "string", "format": "date-time"},
        "checks": {
            "type": "object",
            "minProperties": 1,
            "propertyNames": {"enum": list(CHECK_IDS)},
            "additionalProperties": {"$ref": "#/$defs/check"},
        },
        "outcome": {"enum": ["passed", "failed", "invalid"]},
    }
    rules = class_rules() + signed_image_rules() + passed_rules() + outcome_rules()
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_BASE + RESULT_SCHEMA,
        "title": "rules_mkosi hardware qualification result",
        "description": "One physical qualification run of one machine in one firmware configuration; see " + DOC + ".",
        **obj(properties, properties, allOf=rules),
        "$defs": result_defs(),
    }


def signoff_class(hardware_class: HardwareClass) -> JSON:
    """Restricts a class's results to its Secure Boot states and requires one per state when it is qualified."""
    contains = [{"contains": {"properties": {"secure_boot": {"const": state}}}} for state in hardware_class.secure_boot]
    return {
        "allOf": [
            {"$ref": "#/$defs/class_entry"},
            {"properties": {"results": {"items": {"properties": {"secure_boot": enum(hardware_class.secure_boot)}}}}},
            {
                "if": {"properties": {"status": {"const": "qualified"}}},
                "then": {"properties": {"results": {"allOf": contains}}},
            },
        ]
    }


def signoff_defs() -> JSON:
    result = obj(
        {"asset": NONEMPTY, "sha256": SHA256, "secure_boot": {"enum": list(STATES)}}, ["asset", "sha256", "secure_boot"]
    )
    status_rules = [
        {"if": {"properties": {"status": {"const": "failed"}}}, "then": {"properties": {"results": {"minItems": 1}}}},
        {
            "if": {"properties": {"status": {"const": "not-tested"}}},
            "then": {"properties": {"results": {"maxItems": 0}}},
        },
    ]
    class_entry = obj(
        {
            "status": {"enum": ["qualified", "failed", "not-tested"]},
            "results": array({"$ref": "#/$defs/result"}, uniqueItems=True),
            "known_issues": array({"type": "string", "format": "uri"}),
        },
        ["status", "results"],
        allOf=status_rules,
    )
    return {
        "class_entry": class_entry,
        "nonempty_string": {"type": "string", "minLength": 1},
        "result": result,
        "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    }


def signoff_schema() -> JSON:
    """Returns the schema of a release sign-off, which lists every class exactly once."""
    release = obj(
        {
            "tag": {"type": "string", "pattern": "^v[0-9]+\\.[0-9]+\\.[0-9]+$"},
            "commit": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
            "archive_sha256": SHA256,
        },
        ["tag", "commit", "archive_sha256"],
    )
    vm_gates = obj(
        {"ci_run": {"type": "string", "format": "uri"}, "conclusion": {"const": "success"}}, ["ci_run", "conclusion"]
    )
    classes = {hardware_class.name: signoff_class(hardware_class) for hardware_class in CLASSES}
    properties = {
        "format_version": {"const": "rules-mkosi-hardware-qualification-signoff-v1"},
        "release": release,
        "vm_gates": vm_gates,
        "classes": obj(classes, classes),
        "signed_off_by": NONEMPTY,
        "signed_off_at": {"type": "string", "format": "date-time"},
    }
    description = "The hardware classes that one rules_mkosi release claims, with their attached results; see "
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_BASE + SIGNOFF_SCHEMA,
        "title": "rules_mkosi hardware qualification sign-off",
        "description": description + DOC + ".",
        **obj(properties, properties),
        "$defs": signoff_defs(),
    }


def dump(schema: JSON) -> str:
    """Formats JSON like the pretty-format-json hook."""
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def code(values: Any) -> str:
    return ", ".join(f"`{value}`" for value in values)


def labeled(labels: list[str], note: str) -> str:
    return ", ".join(labels) + (f" ({note})" if note else "")


def table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def classes_table() -> str:
    header = ("Class", "Representative machine", "Generation", "Boot disk", "Network", "Console", "Secure Boot states")
    rows = []
    for hardware_class in CLASSES:
        rows.append(
            (
                f"`{hardware_class.name}`",
                hardware_class.machine,
                hardware_class.generation,
                " or ".join(TRANSPORTS[transport] for transport in hardware_class.transports),
                labeled([NETWORKS[kind][0] for kind in hardware_class.network], hardware_class.network_note),
                labeled([CONSOLES[kind][0] for kind in hardware_class.consoles], hardware_class.console_note),
                code(hardware_class.secure_boot),
                TPM2[hardware_class.tpm2][0],
            )
        )
    return table((*header, "TPM2"), rows)


def secure_boot_table() -> str:
    rows = [(f"`{name}`", firmware, image, expected) for name, firmware, image, expected in SECURE_BOOT_STATES]
    return table(("State", "Firmware before the first boot", "Image", "Expected result"), rows)


def required_when(check: Check) -> str:
    if check.when == "always":
        return "Always"
    if check.when == "uefi":
        return "`uefi`"
    if check.when == "network":
        return NETWORKS[check.values[0]][0] + " network"
    if check.when == "console":
        return CONSOLES[check.values[0]][0] + " console"
    if check.when == "states":
        return code(check.values)
    return f"`{check.values[0]}` in " + " or ".join(f"`{state}`" for state in check.values[1:])


def checks_table() -> str:
    rows = [(f"`{check.id}`", required_when(check), check.passes) for check in CHECKS]
    return table(("Check", "Required when", "Passes when"), rows)


TABLES = {"classes": classes_table, "secure-boot-states": secure_boot_table, "checks": checks_table}


def render_table(text: str, name: str, content: str) -> str:
    """Replaces the generated table between the named markers; fails unless there is exactly one marker pair."""
    begin = f"<!-- BEGIN GENERATED {name}: python3 ci/hardware_qualification_schemas.py --write -->"
    end = f"<!-- END GENERATED {name} -->"
    pattern = re.compile(re.escape(begin) + r"\n.*?\n" + re.escape(end), re.DOTALL)
    replacement = f"{begin}\n\n{content}\n\n{end}"
    text, count = pattern.subn(lambda _: replacement, text)
    if count != 1:
        raise ValueError(f"{DOC}: expected one pair of {name} markers, found {count}")
    return text


def render_doc(text: str) -> str:
    for name, render in TABLES.items():
        text = render_table(text, name, render())
    return text


def expected_files(root: pathlib.Path) -> dict[str, str]:
    """Returns the generated content of every file, keyed by its path relative to the repository root."""
    return {
        RESULT_SCHEMA: dump(result_schema()),
        SIGNOFF_SCHEMA: dump(signoff_schema()),
        DOC: render_doc((root / DOC).read_text(encoding="utf-8")),
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="regenerate the files instead of checking them")
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)
    stale = []
    for path, content in expected_files(args.root).items():
        if (args.root / path).read_text(encoding="utf-8") != content:
            stale.append(path)
            if args.write:
                (args.root / path).write_text(content, encoding="utf-8")
    if stale and not args.write:
        print(
            f"{', '.join(stale)}: out of date; run python3 ci/hardware_qualification_schemas.py --write",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
