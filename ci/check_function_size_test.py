"""Tests for the function size ratchet."""

import io
import pathlib
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import check_function_size
from check_function_size import function_lengths, read_baseline, shrunk_baseline, violations


def lines(count: int, indent: str = "    ") -> str:
    return "".join("%sx = %d\n" % (indent, number) for number in range(count))


class FunctionLengthsTest(unittest.TestCase):
    def test_counts_signature_through_last_body_line_without_decorators(self):
        source = "@decorator\ndef wrapped(\n    argument,\n):\n" + lines(3)

        self.assertEqual(function_lengths(source, "file.py"), {"wrapped": 6})

    def test_names_methods_and_nested_functions_by_their_enclosing_scopes(self):
        source = textwrap.dedent("""\
            class Case:
                def method(self):
                    def helper():
                        return 1
                    return helper()
            """)

        self.assertEqual(function_lengths(source, "file.py"), {"Case.method": 4, "Case.method.helper": 2})

    def test_numbers_repeated_names(self):
        source = "def twice():\n    pass\n\ndef twice():\n    pass\n    pass\n"

        self.assertEqual(function_lengths(source, "file.py"), {"twice": 2, "twice#2": 3})

    def test_parses_starlark_macros_and_rule_implementations(self):
        source = textwrap.dedent("""\
            load("@rules_cc//cc:defs.bzl", "cc_library")

            def _impl(ctx):
                return [DefaultInfo(files = depset(ctx.files.srcs))]

            my_rule = rule(implementation = _impl, attrs = {"srcs": attr.label_list()})

            def my_macro(name, **kwargs):
                my_rule(name = name, **kwargs)
                cc_library(name = name + "_lib")
            """)

        self.assertEqual(function_lengths(source, "defs.bzl"), {"_impl": 2, "my_macro": 3})

    def test_reports_unparsable_sources(self):
        with self.assertRaises(SyntaxError):
            function_lengths("def broken(:\n", "broken.bzl")


class ViolationsTest(unittest.TestCase):
    def test_accepts_short_functions_and_unchanged_baseline_entries(self):
        self.assertEqual(violations({"a.py:short": 5, "a.py:long": 50}, {"a.py:long": 50}, 40), [])

    def test_rejects_a_new_function_over_the_limit(self):
        self.assertEqual(
            violations({"a.py:fresh": 41}, {}, 40),
            ["a.py:fresh: 41 lines exceeds the 40-line limit"],
        )

    def test_rejects_a_baseline_function_that_grew(self):
        self.assertEqual(
            violations({"a.py:long": 51}, {"a.py:long": 50}, 40),
            ["a.py:long: grew to 51 lines; the baseline allows 50"],
        )

    def test_rejects_stale_baseline_entries(self):
        self.assertEqual(
            violations(
                {"a.py:fits": 40, "a.py:shorter": 45}, {"a.py:fits": 50, "a.py:gone": 50, "a.py:shorter": 50}, 40
            ),
            [
                "a.py:fits: now 40 lines and within the limit; remove its baseline entry",
                "a.py:gone: function no longer exists; remove its baseline entry",
                "a.py:shorter: shrank to 45 lines; lower its baseline entry from 50",
            ],
        )


class BaselineTest(unittest.TestCase):
    def test_reads_entries_and_skips_comments(self):
        text = "# header\n\nci/a.py:Case.method 50\nmkosi/defs.bzl:suite 900\n"

        self.assertEqual(read_baseline(text), {"ci/a.py:Case.method": 50, "mkosi/defs.bzl:suite": 900})

    def test_rejects_malformed_and_repeated_entries(self):
        for text in ("a.py:long\n", "a.py:long fifty\n", "a.py 50\n", "a.py:long 50\na.py:long 50\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                read_baseline(text)

    def test_update_only_removes_and_lowers_entries(self):
        lengths = {"a.py:fits": 40, "a.py:shorter": 45, "a.py:grown": 60, "a.py:fresh": 70}
        baseline = {"a.py:fits": 50, "a.py:gone": 50, "a.py:shorter": 50, "a.py:grown": 50}

        self.assertEqual(shrunk_baseline(lengths, baseline, 40), {"a.py:shorter": 45, "a.py:grown": 50})


class MainTest(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        (self.root / "ci").mkdir()
        (self.root / "long.py").write_text("def long():\n" + lines(44))
        (self.root / "suite.bzl").write_text("def suite():\n" + lines(2))
        self.baseline = self.root / check_function_size.BASELINE

    def run_main(self, *args: str) -> tuple[int, str]:
        stderr = io.StringIO()
        with (
            mock.patch.object(check_function_size, "tracked_sources", return_value=["long.py", "suite.bzl"]),
            redirect_stderr(stderr),
        ):
            status = check_function_size.main(["--root", str(self.root), *args])
        return status, stderr.getvalue()

    def test_passes_with_matching_baseline(self):
        self.baseline.write_text("long.py:long 45\n")

        self.assertEqual(self.run_main(), (0, ""))

    def test_fails_and_explains_an_outdated_baseline(self):
        self.baseline.write_text("long.py:long 50\nsuite.bzl:suite 50\n")

        status, stderr = self.run_main()

        self.assertEqual(status, 1)
        self.assertIn("long.py:long: shrank to 45 lines", stderr)
        self.assertIn("suite.bzl:suite: now 3 lines", stderr)

    def test_update_rewrites_the_baseline_and_passes(self):
        self.baseline.write_text("long.py:long 50\nsuite.bzl:suite 50\n")

        self.assertEqual(self.run_main("--update-baseline"), (0, ""))
        self.assertEqual(
            self.baseline.read_text(),
            check_function_size.BASELINE_HEADER + "long.py:long 45\n",
        )


if __name__ == "__main__":
    unittest.main()
