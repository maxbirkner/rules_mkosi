"""Tests for the function size ratchet."""

import io
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import check_function_size
from check_function_size import (
    base_revision,
    committed_baseline,
    function_lengths,
    ratchet_violations,
    read_baseline,
    shrunk_baseline,
    violations,
)


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


class RatchetTest(unittest.TestCase):
    def test_accepts_unchanged_lowered_and_removed_entries(self):
        base = {"a.py:same": 50, "a.py:lowered": 60, "a.py:removed": 70}

        self.assertEqual(ratchet_violations({"a.py:same": 50, "a.py:lowered": 55}, base), [])

    def test_rejects_a_new_baseline_entry(self):
        self.assertEqual(
            ratchet_violations({"a.py:old": 50, "a.py:fresh": 45}, {"a.py:old": 50}),
            ["a.py:fresh: new baseline entry; shorten the function instead of listing it"],
        )

    def test_rejects_a_raised_baseline_entry(self):
        self.assertEqual(
            ratchet_violations({"a.py:long": 51}, {"a.py:long": 50}),
            ["a.py:long: baseline entry raised from 50 to 51; entries may only shrink"],
        )


@unittest.skipUnless(shutil.which("git"), "needs git")
class CommittedBaselineTest(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        self.environment = dict(
            os.environ,
            GIT_AUTHOR_NAME="test",
            GIT_AUTHOR_EMAIL="test@example.com",
            GIT_COMMITTER_NAME="test",
            GIT_COMMITTER_EMAIL="test@example.com",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_NOSYSTEM="1",
        )
        self.git("init", "--quiet", "--initial-branch=main")
        (self.root / "README").write_text("first\n")
        self.commit("without a baseline")

    def git(self, *arguments: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.root), *arguments],
            check=True,
            capture_output=True,
            env=self.environment,
            text=True,
        ).stdout.strip()

    def commit(self, message: str) -> str:
        self.git("add", "--all")
        self.git("commit", "--quiet", "--message", message)
        return self.git("rev-parse", "HEAD")

    def write_baseline(self, text: str) -> None:
        (self.root / "ci").mkdir(exist_ok=True)
        (self.root / check_function_size.BASELINE).write_text(text)

    def test_skips_a_revision_without_the_baseline_file(self):
        self.assertIsNone(committed_baseline(self.root, "HEAD", check_function_size.BASELINE))

    def test_reads_the_baseline_at_the_merge_base(self):
        self.write_baseline("a.py:long 50\n")
        base = self.commit("add baseline")
        self.git("switch", "--quiet", "--create", "topic")
        self.write_baseline("a.py:long 60\n")
        self.commit("raise baseline")
        self.git("switch", "--quiet", "main")
        self.write_baseline("")
        self.commit("drop baseline entry on main")
        self.git("switch", "--quiet", "topic")

        revision = base_revision(self.root, "main")

        self.assertEqual(revision, base)
        self.assertEqual(committed_baseline(self.root, revision, check_function_size.BASELINE), {"a.py:long": 50})

    def test_defaults_to_head_and_rejects_unknown_revisions(self):
        self.assertEqual(base_revision(self.root, None), "HEAD")
        with self.assertRaises(subprocess.CalledProcessError):
            committed_baseline(self.root, "no-such-ref", check_function_size.BASELINE)


class MainTest(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        (self.root / "ci").mkdir()
        (self.root / "long.py").write_text("def long():\n" + lines(44))
        (self.root / "suite.bzl").write_text("def suite():\n" + lines(2))
        self.baseline = self.root / check_function_size.BASELINE

    def run_main(self, *args: str, base_baseline: dict[str, int] | None = None) -> tuple[int, str]:
        stderr = io.StringIO()
        with (
            mock.patch.object(check_function_size, "tracked_sources", return_value=["long.py", "suite.bzl"]),
            mock.patch.object(check_function_size, "committed_baseline", return_value=base_baseline) as committed,
            redirect_stderr(stderr),
        ):
            status = check_function_size.main(["--root", str(self.root), "--base-ref", "", *args])
        committed.assert_called_once_with(self.root, "HEAD", check_function_size.BASELINE)
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

    def test_fails_when_the_baseline_gains_an_entry_absent_at_the_base_revision(self):
        self.baseline.write_text("long.py:long 45\n")

        status, stderr = self.run_main(base_baseline={})

        self.assertEqual(status, 1)
        self.assertIn("long.py:long: new baseline entry", stderr)

    def test_fails_when_the_baseline_entry_is_higher_than_at_the_base_revision(self):
        (self.root / "long.py").write_text("def long():\n" + lines(49))
        self.baseline.write_text("long.py:long 50\n")

        status, stderr = self.run_main(base_baseline={"long.py:long": 45})

        self.assertEqual(status, 1)
        self.assertIn("long.py:long: baseline entry raised from 45 to 50", stderr)

    def test_update_rewrites_the_baseline_and_passes(self):
        self.baseline.write_text("long.py:long 50\nsuite.bzl:suite 50\n")

        self.assertEqual(self.run_main("--update-baseline"), (0, ""))
        self.assertEqual(
            self.baseline.read_text(),
            check_function_size.BASELINE_HEADER + "long.py:long 45\n",
        )


if __name__ == "__main__":
    unittest.main()
