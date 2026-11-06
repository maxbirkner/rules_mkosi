"""Tests the generated hardware qualification schemas, their document tables, and the document's example record.

The schemas are checked with a small validator for the JSON Schema keywords they use, so the test needs no
third-party package; it fails on any other keyword, so new keywords cannot go unchecked.
"""

import json
import pathlib
import re
import sys
import unittest
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import hardware_qualification_schemas as schemas

ROOT = pathlib.Path(sys.argv[1]).parent.parent
ANNOTATIONS = {"$schema", "$id", "$defs", "title", "description", "format"}
TYPES = {"object": dict, "array": list, "string": str, "boolean": bool}
LOG = [{"path": "logs/check.txt", "sha256": "f" * 64}]


class Validator:
    """Validates instances against a draft 2020-12 schema that uses only the keywords in `KEYWORDS`."""

    def __init__(self, schema: dict[str, Any]):
        self.root = schema

    def valid(self, schema: dict[str, Any], instance: Any) -> bool:
        return not self.errors(schema, instance)

    def errors(self, schema: dict[str, Any], instance: Any, path: str = "$") -> list[str]:
        errors = []
        for keyword, value in schema.items():
            if keyword in ANNOTATIONS or keyword in ("then", "else"):
                continue
            if keyword not in KEYWORDS:
                raise ValueError(f"unsupported keyword {keyword} at {path}")
            errors += KEYWORDS[keyword](self, value, instance, schema, path)
        return errors


def check_ref(validator, value, instance, schema, path):
    prefix = "#/$defs/"
    assert value.startswith(prefix), value
    return validator.errors(validator.root["$defs"][value[len(prefix) :]], instance, path)


def check_if(validator, value, instance, schema, path):
    branch = "then" if validator.valid(value, instance) else "else"
    return validator.errors(schema[branch], instance, path) if branch in schema else []


def check_object(test):
    def check(validator, value, instance, schema, path):
        return test(validator, value, instance, schema, path) if isinstance(instance, dict) else []

    return check


def check_array(test):
    def check(validator, value, instance, schema, path):
        return test(validator, value, instance, path) if isinstance(instance, list) else []

    return check


def check_properties(validator, value, instance, schema, path):
    return [e for key in value if key in instance for e in validator.errors(value[key], instance[key], f"{path}.{key}")]


def check_additional(validator, value, instance, schema, path):
    extra = [key for key in instance if key not in schema.get("properties", {})]
    if value is False:
        return [f"{path}: unexpected {key}" for key in extra]
    return [e for key in extra for e in validator.errors(value, instance[key], f"{path}.{key}")]


def fails(condition, message):
    return [message] if condition else []


KEYWORDS = {
    "$ref": check_ref,
    "if": check_if,
    "type": lambda v, value, i, s, p: fails(not isinstance(i, TYPES[value]), f"{p}: not {value}"),
    "const": lambda v, value, i, s, p: fails(i != value, f"{p}: {i!r} is not {value!r}"),
    "enum": lambda v, value, i, s, p: fails(i not in value, f"{p}: {i!r} not in {value}"),
    "pattern": lambda v, value, i, s, p: fails(isinstance(i, str) and not re.search(value, i), f"{p}: {i!r}"),
    "minLength": lambda v, value, i, s, p: fails(isinstance(i, str) and len(i) < value, f"{p}: too short"),
    "allOf": lambda v, value, i, s, p: [e for sub in value for e in v.errors(sub, i, p)],
    "not": lambda v, value, i, s, p: fails(v.valid(value, i), f"{p}: matches a forbidden schema"),
    "required": check_object(lambda v, value, i, s, p: [f"{p}: missing {k}" for k in value if k not in i]),
    "properties": check_object(check_properties),
    "additionalProperties": check_object(check_additional),
    "minProperties": check_object(lambda v, value, i, s, p: fails(len(i) < value, f"{p}: too few properties")),
    "propertyNames": check_object(lambda v, value, i, s, p: [e for k in i for e in v.errors(value, k, f"{p}.{k}")]),
    "items": check_array(lambda v, value, i, p: [e for n, x in enumerate(i) for e in v.errors(value, x, f"{p}[{n}]")]),
    "contains": check_array(lambda v, value, i, p: fails(not any(v.valid(value, x) for x in i), f"{p}: no match")),
    "minItems": check_array(lambda v, value, i, p: fails(len(i) < value, f"{p}: too few items")),
    "maxItems": check_array(lambda v, value, i, p: fails(len(i) > value, f"{p}: too many items")),
    "uniqueItems": check_array(
        lambda v, value, i, p: fails(value and len({json.dumps(x, sort_keys=True) for x in i}) < len(i), f"{p}: dup")
    ),
}


def minimal_result(hardware_class: schemas.HardwareClass, state: str) -> dict[str, Any]:
    """Returns a passed result record with only what the class and Secure Boot state require."""
    image: dict[str, Any] = {name: "1" * 64 for name in ("reproducibility_manifest_sha256", "canonical_sha256")}
    image["written_sha256"] = "2" * 64
    if state in schemas.SIGNED_STATES:
        image["signed_binaries"] = [{"esp_path": "", "sha256": "3" * 64}]
        image["signed_image_record_sha256"] = "4" * 64
    if state == "setup-mode":
        image["auto_enroll_keys"] = [{"name": key, "sha256": "5" * 64} for key in schemas.AUTO_ENROLL_KEYS]
    payloads = schemas.expected_payloads(hardware_class, state)
    subject: dict[str, Any] = {"rules_mkosi": {"commit": "0" * 40}, "image": image}
    if payloads:
        subject["update_payloads"] = [
            {"version": str(n + 2), "sha256sums_sha256": "6" * 64, "expected": e} for n, e in enumerate(payloads)
        ]
    dmi = {name: "x" for name in ("sys_vendor", "product_name", "bios_vendor", "bios_version", "bios_date")}
    return {
        "format_version": "rules-mkosi-hardware-qualification-result-v1",
        "class": hardware_class.name,
        "subject": subject,
        "machine": {
            "dmi": dmi,
            "cpu": "x",
            "boot_disk": {"transport": hardware_class.transports[0], "model": "x"},
            "network": [{"kind": kind, "driver": "x"} for kind in hardware_class.network],
            "consoles": list(hardware_class.consoles),
            "tpm2": schemas.TPM2[hardware_class.tpm2][1][0],
        },
        "firmware": {"tier": hardware_class.tier, "boot_mode": hardware_class.boot_mode, "secure_boot": state},
        "operator": "x",
        "started_at": "2026-01-01T00:00:00Z",
        "finished_at": "2026-01-01T01:00:00Z",
        "checks": {
            check: {"status": "passed", "logs": LOG} for check in schemas.required_checks(hardware_class, state)
        },
        "outcome": "passed",
    }


def minimal_signoff() -> dict[str, Any]:
    """Returns a sign-off that qualifies every class with one result per Secure Boot state."""
    classes = {
        hardware_class.name: {
            "status": "qualified",
            "results": [
                {"asset": f"{hardware_class.name}-{state}.json", "sha256": "7" * 64, "secure_boot": state}
                for state in hardware_class.secure_boot
            ],
        }
        for hardware_class in schemas.CLASSES
    }
    return {
        "format_version": "rules-mkosi-hardware-qualification-signoff-v1",
        "release": {"tag": "v1.2.3", "commit": "0" * 40, "archive_sha256": "8" * 64},
        "vm_gates": {"ci_run": "https://github.com/maxbirkner/rules_mkosi/actions/runs/1", "conclusion": "success"},
        "classes": classes,
        "signed_off_by": "x",
        "signed_off_at": "2026-01-01T02:00:00Z",
    }


def combinations():
    return [(hardware_class, state) for hardware_class in schemas.CLASSES for state in hardware_class.secure_boot]


class GeneratedFilesTest(unittest.TestCase):
    def test_committed_files_match_the_generator(self):
        for path, content in schemas.expected_files(ROOT).items():
            with self.subTest(path=path):
                self.assertEqual((ROOT / path).read_text(encoding="utf-8"), content, "run --write")

    def test_missing_table_markers_fail(self):
        with self.assertRaisesRegex(ValueError, "expected one pair of classes markers"):
            schemas.render_doc("no markers")


def schema_keywords(schema: dict[str, Any]) -> set[str]:
    """Returns every keyword that the schema and its subschemas use."""
    found = set(schema)
    for keyword, value in schema.items():
        if keyword in ("properties", "$defs"):
            subschemas = list(value.values())
        elif keyword == "allOf":
            subschemas = value
        elif isinstance(value, dict):
            subschemas = [value]
        else:
            subschemas = []
        for subschema in subschemas:
            found |= schema_keywords(subschema)
    return found


class ValidatorTest(unittest.TestCase):
    def test_validator_supports_every_keyword_of_the_schemas(self):
        for schema in (schemas.result_schema(), schemas.signoff_schema()):
            self.assertLessEqual(schema_keywords(schema) - ANNOTATIONS - {"then", "else"}, set(KEYWORDS))

    def test_unknown_keywords_fail(self):
        with self.assertRaisesRegex(ValueError, "unsupported keyword maximum"):
            Validator({}).errors({"maximum": 1}, 2)


class ResultSchemaTest(unittest.TestCase):
    def setUp(self):
        self.validator = Validator(schemas.result_schema())

    def assert_valid(self, record):
        self.assertEqual(self.validator.errors(self.validator.root, record), [])

    def assert_invalid(self, record):
        self.assertNotEqual(self.validator.errors(self.validator.root, record), [])

    def test_document_example_is_valid(self):
        text = (ROOT / schemas.DOC).read_text(encoding="utf-8")
        example = re.search(r"```json\n(.*?)```", text, re.DOTALL)
        assert example is not None
        self.assert_valid(json.loads(example.group(1)))

    def test_every_class_and_state_accepts_its_required_checks(self):
        self.assertEqual(len(combinations()), 12)
        for hardware_class, state in combinations():
            with self.subTest(hardware_class=hardware_class.name, state=state):
                self.assert_valid(minimal_result(hardware_class, state))

    def test_passed_without_a_required_check_is_rejected(self):
        for hardware_class, state in combinations():
            for check in schemas.required_checks(hardware_class, state):
                with self.subTest(hardware_class=hardware_class.name, state=state, check=check):
                    record = minimal_result(hardware_class, state)
                    del record["checks"][check]
                    self.assert_invalid(record)
                    record["checks"][check] = {"status": "not-applicable", "logs": []}
                    self.assert_invalid(record)

    def test_tier_must_match_the_class(self):
        for hardware_class, state in combinations():
            with self.subTest(hardware_class=hardware_class.name, state=state):
                record = minimal_result(hardware_class, state)
                record["firmware"]["tier"] = "bios" if hardware_class.tier == "uefi" else "uefi"
                self.assert_invalid(record)
        bios_with_secure_boot = minimal_result(schemas.CLASSES[-1], "not-applicable")
        bios_with_secure_boot["firmware"]["secure_boot"] = "disabled"
        self.assert_invalid(bios_with_secure_boot)

    def test_outcome_must_match_the_checks(self):
        record = minimal_result(schemas.CLASSES[0], "setup-mode")
        record["outcome"] = "failed"
        self.assert_invalid(record)
        failure = {"category": "network", "attribution": "firmware", "summary": "x"}
        record["checks"]["network-wired"] = {"status": "failed", "logs": LOG, "failure": failure}
        self.assert_valid(record)
        record["outcome"] = "passed"
        self.assert_invalid(record)
        record["outcome"] = "invalid"
        self.assert_invalid(record)
        failure["attribution"] = "procedure"
        self.assert_valid(record)

    def test_enforcing_states_need_a_refused_update(self):
        record = minimal_result(schemas.CLASSES[0], "custom-keys")
        record["subject"]["update_payloads"] = record["subject"]["update_payloads"][:2]
        self.assert_invalid(record)


class SignoffSchemaTest(unittest.TestCase):
    def setUp(self):
        self.validator = Validator(schemas.signoff_schema())

    def errors(self, signoff):
        return self.validator.errors(self.validator.root, signoff)

    def test_every_class_qualified(self):
        self.assertEqual(self.errors(minimal_signoff()), [])

    def test_every_class_appears_exactly_once(self):
        signoff = minimal_signoff()
        del signoff["classes"]["bios-csm"]
        self.assertNotEqual(self.errors(signoff), [])
        signoff = minimal_signoff()
        signoff["classes"]["uefi-other"] = {"status": "not-tested", "results": []}
        self.assertNotEqual(self.errors(signoff), [])

    def test_qualified_class_needs_every_secure_boot_state(self):
        signoff = minimal_signoff()
        signoff["classes"]["uefi-modern-desktop"]["results"].pop()
        self.assertNotEqual(self.errors(signoff), [])

    def test_status_must_match_the_results(self):
        signoff = minimal_signoff()
        signoff["classes"]["bios-csm"]["status"] = "not-tested"
        self.assertNotEqual(self.errors(signoff), [])
        signoff["classes"]["bios-csm"] = {"status": "failed", "results": []}
        self.assertNotEqual(self.errors(signoff), [])


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
