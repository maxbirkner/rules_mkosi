import pathlib
import re
import sys
import unittest


ID_RE = re.compile(r"^BHV-[A-Z0-9]+(?:-[A-Z0-9]+)*$")
LAYERS = {"analysis", "artifact", "consumer", "runtime"}


def load_documented_ids(path):
    text = path.read_text()
    ids = re.findall(r"<!-- behavior:([A-Z0-9-]+) -->", text)
    if len(ids) != len(set(ids)):
        raise ValueError("documented behavior IDs must be unique")
    return set(ids)


def load_matrix(path):
    lines = path.read_text().splitlines()
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
        for entry in tests_text.split(";"):
            layer, target = entry.split("=", 1)
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
                else:
                    self.assertFalse(target.startswith("//e2e/smoke:"))


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
