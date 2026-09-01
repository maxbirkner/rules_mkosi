import pathlib
import re
import sys
import unittest


ID_RE = re.compile(r"^BHV-[A-Z0-9]+(?:-[A-Z0-9]+)*$")
LAYERS = {"analysis", "artifact", "consumer", "module-resolution", "runtime"}
ROOT_LAYERS = LAYERS - {"consumer"}


def load_documented_ids(path):
    text = path.read_text()
    ids = re.findall(r"<!-- behavior:([A-Z0-9-]+) -->", text)
    if len(ids) != len(set(ids)):
        raise ValueError("documented behavior IDs must be unique")
    return set(ids)


def parse_matrix(text):
    lines = text.splitlines()
    if not lines or lines[0] != "id\tsurface\tcases\tbehavior\ttests":
        raise ValueError("matrix header is invalid")
    by_id = {}
    for line in lines[1:]:
        behavior_id, surface, cases_text, behavior, tests_text = line.split(
            "\t"
        )
        if not ID_RE.fullmatch(behavior_id):
            raise ValueError(f"invalid behavior ID: {behavior_id}")
        if behavior_id in by_id:
            raise ValueError(f"duplicate matrix behavior ID: {behavior_id}")
        if not behavior.strip():
            raise ValueError(f"{behavior_id} has no behavior description")
        cases = set(cases_text.split(","))
        if not cases or not cases <= {"positive", "boundary", "negative"}:
            raise ValueError(f"{behavior_id} has invalid cases")
        if not tests_text:
            raise ValueError(f"{behavior_id} has no mapped test target")
        mappings = []
        mapping_keys = set()
        for entry in tests_text.split(";"):
            layer, target = entry.split("=", 1)
            mapping_key = (layer, target)
            if mapping_key in mapping_keys:
                raise ValueError(
                    f"{behavior_id} has duplicate mapping {layer}={target}"
                )
            mapping_keys.add(mapping_key)
            mapping = {"layer": layer, "target": target}
            mappings.append(mapping)
        for mapping in mappings:
            if mapping["layer"] not in LAYERS:
                raise ValueError(
                    f"{behavior_id} has invalid layer {mapping['layer']}"
                )
            if not mapping["target"].startswith("//"):
                raise ValueError(
                    f"{behavior_id} has non-canonical target {mapping['target']}"
                )
        by_id[behavior_id] = {
            "behavior": behavior,
            "cases": sorted(cases),
            "surface": surface,
            "tests": mappings,
        }
    return by_id


def load_matrix(path):
    return parse_matrix(path.read_text())


def validate_registered_targets(matrix, manifest, scope):
    registered = {
        target.replace("@@//", "//", 1) for target in manifest.splitlines()
    }
    layers = {"consumer"} if scope == "consumer" else ROOT_LAYERS
    mapped = {
        mapping["target"]
        for row in matrix.values()
        for mapping in row["tests"]
        if mapping["layer"] in layers
    }
    if scope == "consumer":
        registered = {
            target.replace("//:", "//e2e/smoke:", 1) for target in registered
        }
    missing = mapped - registered
    extra = registered - mapped
    if missing or extra:
        raise ValueError(
            f"{scope} target manifest differs: missing={sorted(missing)}, "
            f"extra={sorted(extra)}"
        )


class BehaviorMatrixTest(unittest.TestCase):
    def test_every_documented_behavior_is_mapped(self):
        docs = load_documented_ids(pathlib.Path(sys.argv[1]))
        matrix = load_matrix(pathlib.Path(sys.argv[2]))
        self.assertEqual(docs, set(matrix), "documentation/matrix behavior IDs differ")

    def test_public_attributes_have_all_case_classes(self):
        matrix = load_matrix(pathlib.Path(sys.argv[2]))
        for behavior_id, row in matrix.items():
            if row["surface"] == "attribute":
                self.assertEqual(
                    {"positive", "boundary", "negative"},
                    set(row["cases"]),
                    f"{behavior_id} lacks positive/boundary/negative coverage",
                )

    def test_root_and_consumer_layers_are_not_conflated(self):
        matrix = load_matrix(pathlib.Path(sys.argv[2]))
        for behavior_id, row in matrix.items():
            for mapping in row["tests"]:
                target = mapping["target"]
                if mapping["layer"] == "consumer":
                    self.assertTrue(target.startswith("//e2e/smoke:"))
                elif mapping["layer"] == "module-resolution":
                    self.assertTrue(
                        target.startswith("//:e2e/module_resolution/")
                    )
                else:
                    self.assertFalse(target.startswith("//e2e/smoke:"))

    def test_registered_labels_match_mappings(self):
        matrix = load_matrix(pathlib.Path(sys.argv[2]))
        manifest = pathlib.Path(sys.argv[3]).read_text()
        validate_registered_targets(matrix, manifest, sys.argv[4])

    def test_duplicate_behavior_id_is_rejected(self):
        header = "id\tsurface\tcases\tbehavior\ttests\n"
        row = "BHV-DUP\tfailure\tnegative\tduplicate\tanalysis=//:test\n"
        with self.assertRaisesRegex(ValueError, "duplicate matrix behavior ID"):
            parse_matrix(header + row + row)

    def test_duplicate_layer_target_mapping_is_rejected(self):
        text = (
            "id\tsurface\tcases\tbehavior\ttests\n"
            "BHV-DUP\tfailure\tnegative\tduplicate\t"
            "analysis=//:test;analysis=//:test\n"
        )
        with self.assertRaisesRegex(ValueError, "duplicate mapping"):
            parse_matrix(text)

    def test_stale_mapping_is_rejected_by_manifest_contract(self):
        matrix = parse_matrix(
            "id\tsurface\tcases\tbehavior\ttests\n"
            "BHV-STALE\tfailure\tnegative\tstale\tanalysis=//:stale\n"
        )
        with self.assertRaisesRegex(ValueError, "missing=.*//:stale"):
            validate_registered_targets(matrix, "//:maintained\n", "root")


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
