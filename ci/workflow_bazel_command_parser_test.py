"""Table-driven tests for the workflow Bazel command policy."""

import pathlib
import sys
import textwrap
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from workflow_bazel_command_test import (
    _token_is_command_position,
    _yaml_shell_bodies,
    validate_shell_sources,
)


def _workflow(run_yaml):
    return "jobs:\n  fixture:\n    steps:\n      - " + textwrap.indent(
        run_yaml,
        "        ",
    ).lstrip()


def _violations(source):
    return validate_shell_sources([("fixture", source, False)])


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
            (
                "github-expression-line-continuation-test",
                "run: |\n"
                "  ${{ env.BAZEL }} \\\n"
                "    test //pkg:target\n",
            ),
            (
                "github-expression-line-continuation-build",
                "run: |\n"
                "  ${{ env.BAZEL }}    \\\n"
                "        build //pkg:target\n",
            ),
            (
                "github-expression-continued-double-quoted-test",
                "run: |\n"
                "  ${{ env.BAZEL }} \\\n"
                '    te""st //pkg:target\n',
            ),
            (
                "github-expression-continued-single-quoted-test",
                "run: |\n"
                "  ${{ env.BAZEL }} \\\n"
                "    t'es't //pkg:target\n",
            ),
            (
                "github-expression-continued-escaped-test",
                "run: |\n"
                "  ${{ env.BAZEL }} \\\n"
                "    te\\st //pkg:target\n",
            ),
            (
                "github-expression-continued-double-quoted-build",
                "run: |\n"
                "  ${{ env.BAZEL }} \\\n"
                '    bu""ild //pkg:target\n',
            ),
            (
                "github-expression-continued-single-quoted-build",
                "run: |\n"
                "  ${{ env.BAZEL }} \\\n"
                "    b'uil'd //pkg:target\n",
            ),
            (
                "github-expression-continued-escaped-build",
                "run: |\n"
                "  ${{ env.BAZEL }} \\\n"
                "    bu\\ild //pkg:target\n",
            ),
            (
                "github-expression-malformed-shell",
                "run: |\n"
                '  ${{ env.BAZEL }} "unterminated\n',
            ),
            (
                "github-expression-nested-shell-fragments",
                "run: |\n"
                "  sh -c '${{ env.BAZEL }} te\"\"st //pkg:target'\n",
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
  echo te""st //pkg:target
  echo t'es't //pkg:target
  echo te\\st //pkg:target
  echo bu""ild //pkg:target
  echo b'uil'd //pkg:target
  echo bu\\ild //pkg:target
  echo "${{ matrix.bazel }}" test //pkg:target
  printf '%s\\n' "${{ env.BAZEL }}" build //pkg:target
  echo GITHUB_EXPRESSION_LAUNCHER test //pkg:target
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

    def test_expression_launchers_handle_control_forms(self):
        self.assertTrue(
            _violations(
                "if ${{ matrix.bazel }} test //pkg:target; "
                "then echo bad; fi"
            )
        )
        self.assertTrue(
            _violations(
                "{ time ${{ matrix.bazel }} build //pkg:target; }"
            )
        )

    def test_token_command_positions(self):
        cases = [
            (["launcher"], 0, True),
            (["if", "launcher"], 1, True),
            (["then", "launcher"], 1, True),
            (["elif", "launcher"], 1, True),
            (["while", "launcher"], 1, True),
            (["until", "launcher"], 1, True),
            (["time", "launcher"], 1, True),
            (["!", "launcher"], 1, True),
            (["{", "launcher"], 1, True),
            (["(", "launcher"], 1, True),
            (
                ["sudo", "-n", "env", "BAZEL=bazel", "launcher"],
                4,
                True,
            ),
            (["echo", "launcher"], 1, False),
            (["printf", "%s", "launcher"], 2, False),
            (["if", "echo", "launcher"], 2, False),
        ]
        for tokens, index, expected in cases:
            with self.subTest(tokens=tokens):
                self.assertEqual(
                    _token_is_command_position(tokens, index),
                    expected,
                )

    def test_expression_launchers_normalize_both_continuation_endings(self):
        for ending in ("\\\n", "\\\r\n"):
            for command in ("build", "test"):
                with self.subTest(ending=repr(ending), command=command):
                    self.assertTrue(
                        _violations(
                            "${{ env.BAZEL }} "
                            + ending
                            + f"    {command} //pkg:target"
                        )
                    )

    def test_unrelated_and_literal_backslashes_do_not_hide_bypass(self):
        source = (
            "printf '%s' '\\\\'; echo unrelated \\\n"
            "  value\n"
            "${{ env.BAZEL }} \\\n"
            "  build //pkg:target\n"
        )
        self.assertTrue(_violations(source))


if __name__ == "__main__":
    unittest.main()
