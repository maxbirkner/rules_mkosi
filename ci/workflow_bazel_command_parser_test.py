"""Table-driven tests for the workflow Bazel command policy."""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from workflow_bazel_command_test import validate_shell_sources


class WorkflowBazelCommandParserTest(unittest.TestCase):
    def test_invalid_commands(self):
        fixtures = [
            ("literal", "run: |\n  bazel test //pkg:target\n"),
            ("wrapper", "run: |\n  run_bazel bazel test //pkg:target\n"),
            ("variable", "run: |\n  $bazel test //pkg:target\n"),
            ("absolute", "run: |\n  /usr/bin/bazel build //pkg:target\n"),
            ("multiline", "run: |\n  bazel test --config=ordinary \\\n    //pkg:target\n"),
            ("folded", "run: >-\n  bazel build --config=ordinary\n  //pkg:target\n"),
            (
                "sudo-wrapper",
                "run: |\n  sudo -n env BAZEL=bazel bazel test //pkg:target\n",
            ),
            (
                "variable-wrapper",
                "run: |\n  BAZEL=bazel; \"$BAZEL\" test //pkg:target\n",
            ),
            (
                "default-variable",
                "run: |\n  \"${BAZEL:-bazel}\" build //pkg:target\n",
            ),
            (
                "ambiguous-variable",
                "run: |\n  \"$BAZEL\" \"$ACTION\" //pkg:target\n",
            ),
            ("generic-variable", 'run: "$cmd" test //pkg:target\n'),
            (
                "shell-wrapper",
                'run: |\n  sh -c "bazel test //pkg:target"\n',
            ),
            (
                "scalar-indent",
                "run: |2-\n    bazel test //pkg:target\n",
            ),
            (
                "scalar-folded",
                "run: >2-\n    bazel build //pkg:target\n",
            ),
            (
                "scalar-chomp-indent",
                "run: |-2\n    bazel test //pkg:target\n",
            ),
            (
                "scalar-folded-chomp-indent",
                "run: >+2\n    bazel build //pkg:target\n",
            ),
            (
                "github-expression",
                "run: |\n  ${{ env.BAZEL }} test //pkg:target\n",
            ),
            (
                "github-matrix-expression",
                "run: |\n  ${{ matrix.bazel }} test //pkg:target\n",
            ),
            (
                "github-output-expression",
                "run: |\n  ${{ steps.setup.outputs.bazel }} build //pkg:target\n",
            ),
            (
                "github-index-expression",
                "run: |\n  ${{ steps.setup.outputs.tools[0] }} test //pkg:target\n",
            ),
        ]
        for name, fixture in fixtures:
            with self.subTest(name=name):
                self.assertTrue(
                    validate_shell_sources([("fixture", fixture, True)]),
                    name,
                )

    def test_valid_wildcard_and_queries(self):
        fixture = """run: |
  run_bazel bazel test --config=ordinary //...
  bazel --output_base="$out" build --config=deterministic //...
  bazel query //pkg:target
  $bazel cquery //pkg:target
  /usr/bin/bazel info output_base
"""
        self.assertEqual(
            validate_shell_sources([("fixture", fixture, True)]),
            [],
        )


if __name__ == "__main__":
    unittest.main()
