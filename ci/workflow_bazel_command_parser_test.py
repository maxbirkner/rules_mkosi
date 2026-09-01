"""Table-driven tests for the workflow Bazel command policy."""

import pathlib
import sys
import textwrap
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from workflow_bazel_command_test import (
    _expression_launches_build_or_test,
    _yaml_shell_bodies,
    validate_shell_sources,
)


def _workflow(run_yaml):
    return "jobs:\n  fixture:\n    steps:\n      - " + textwrap.indent(
        run_yaml,
        "        ",
    ).lstrip()


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
            (
                "generic-variable",
                'run: |\n  "$cmd" test //pkg:target\n',
            ),
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
            (
                "github-matrix-string-index",
                "run: |\n  ${{ matrix['bazel'] }} test //pkg:target\n",
            ),
            (
                "github-needs-output",
                "run: |\n  ${{ needs.setup.outputs.bazel }} build //pkg:target\n",
            ),
            (
                "github-event-input",
                "run: |\n  ${{ github.event.inputs.bazel }} test //pkg:target\n",
            ),
            (
                "github-computed-expression",
                "run: |\n  ${{ fromJSON(inputs.tools)[0] }} build //pkg:target\n",
            ),
            (
                "github-expression-command-prefix",
                "run: |\n  ${{ github.workspace }}/bin/tool test //pkg:target\n",
            ),
            (
                "github-expression-after-if",
                "run: |\n"
                "  if ${{ matrix.bazel }} test //pkg:target; then\n"
                "    echo unexpected\n"
                "  fi\n",
            ),
            (
                "github-expression-folded-more-indented",
                "run: >-\n"
                "  echo preparing\n"
                "    ${{ matrix.bazel }} test //pkg:target\n",
            ),
            (
                "github-expression-folded-header-comment",
                "run: >- # retained by structural YAML parsing\n"
                "  ${{ matrix.bazel }} test //pkg:target\n",
            ),
            (
                "github-expression-after-time",
                "run: |\n"
                "  time ${{ matrix.bazel }} test //pkg:target\n",
            ),
            (
                "github-expression-in-brace-group",
                "run: |\n"
                "  { ${{ matrix.bazel }} test //pkg:target; }\n",
            ),
            (
                "github-expression-in-subshell",
                "run: |\n"
                "  (${{ matrix.bazel }} test //pkg:target)\n",
            ),
        ]
        for name, fixture in fixtures:
            with self.subTest(name=name):
                self.assertTrue(
                    validate_shell_sources(
                        [("fixture", _workflow(fixture), True)]
                    ),
                    name,
                )

    def test_valid_wildcard_and_queries(self):
        fixture = """run: |
  run_bazel bazel test --config=ordinary //...
  bazel --output_base="$out" build --config=deterministic //...
  bazel query //pkg:target
  $bazel cquery //pkg:target
  /usr/bin/bazel info output_base
  ${{ matrix.script }} --help
  echo ${{ matrix.bazel }} query
  printf '%s\\n' "${{ fromJSON(inputs.tools)[0] }}" info
"""
        self.assertEqual(
            validate_shell_sources(
                [("fixture", _workflow(fixture), True)]
            ),
            [],
        )

    def test_folded_scalar_preserves_more_indented_line_break(self):
        fixture = (
            "run: >-\n"
            "  echo preparing\n"
            "    ${{ matrix.bazel }} test //pkg:target\n"
        )
        self.assertEqual(
            _yaml_shell_bodies(_workflow(fixture)),
            ["echo preparing\n  ${{ matrix.bazel }} test //pkg:target"],
        )

    def test_expression_scan_handles_control_forms(self):
        self.assertTrue(
            _expression_launches_build_or_test(
                "if ${{ matrix.bazel }} test //pkg:target; then echo bad; fi"
            )
        )
        self.assertTrue(
            _expression_launches_build_or_test(
                "{ time ${{ matrix.bazel }} build //pkg:target; }"
            )
        )


if __name__ == "__main__":
    unittest.main()
