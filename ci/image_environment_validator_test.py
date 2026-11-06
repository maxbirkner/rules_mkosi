"""Tests for the mkosi image action environment audit."""

import pathlib
import sys
import unittest
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from image_environment_validator import environment_errors, graph_errors, interpreter_flags

PYTHONPATH = "external/+mkosi+mkosi_source:external/rules_python++pip+pefile/site-packages"
RELEASE = {"MKOSI_HOST_DISTRIBUTION": "debian", "MKOSI_HOST_RELEASE": "trixie", "SOURCE_DATE_EPOCH": "0"}


def image_action(
    *options: str, release: bool = False, offline: bool = False, **environment: str | None
) -> dict[str, Any]:
    """Returns an MkosiImage action whose environment entries are replaced, or removed when None.

    The action is a release, an offline tracer that installs from a Debian snapshot, or a networked tracer.
    """
    values: dict[str, str | None] = {
        "PATH": "",
        "PYTHONNOUSERSITE": "1",
        "MKOSI_FORCE_USERNS_FALLBACK": "1",
        "PYTHONPATH": PYTHONPATH,
        **(RELEASE if release else {}),
        **environment,
    }
    # aquery omits the value of empty variables.
    variables = [
        {"key": key} | ({"value": value} if value else {}) for key, value in values.items() if value is not None
    ]
    requirements = ["block-network" if release or offline else "requires-network", "no-remote-exec"]
    if not release:
        requirements.append("no-cache")
    return {
        "mnemonic": "MkosiImage",
        "targetId": 2 if release else 1,
        "arguments": ["bazel-out/bin/python3", *options, "mkosi/private/run_mkosi.py"],
        "environmentVariables": variables,
        "executionInfo": [{"key": key, "value": "1"} for key in requirements],
    }


class EnvironmentErrorsTest(unittest.TestCase):
    def test_accepts_tracer_environment(self) -> None:
        for offline in (False, True):
            with self.subTest(offline=offline):
                self.assertEqual([], environment_errors(image_action(offline=offline)))

    def test_accepts_release_environment(self) -> None:
        self.assertEqual([], environment_errors(image_action(release=True)))

    def test_requires_each_entry(self) -> None:
        action = image_action(PATH=None, PYTHONNOUSERSITE=None, MKOSI_FORCE_USERNS_FALLBACK=None, PYTHONPATH=None)

        self.assertEqual(
            [
                "missing MKOSI_FORCE_USERNS_FALLBACK",
                "missing PATH",
                "missing PYTHONNOUSERSITE",
                "missing PYTHONPATH",
            ],
            environment_errors(action),
        )

    def test_rejects_host_search_path(self) -> None:
        self.assertEqual(["invalid PATH=/usr/bin"], environment_errors(image_action(PATH="/usr/bin")))

    def test_rejects_disabled_flags(self) -> None:
        action = image_action(PYTHONNOUSERSITE="0", MKOSI_FORCE_USERNS_FALLBACK="0")

        self.assertEqual(
            ["invalid MKOSI_FORCE_USERNS_FALLBACK=0", "invalid PYTHONNOUSERSITE=0"],
            environment_errors(action),
        )

    def test_rejects_pythonpath_outside_execroot(self) -> None:
        for value in ("/usr/lib/python3/dist-packages", "external/a:", "external/../../site-packages"):
            with self.subTest(value=value):
                self.assertEqual([f"invalid PYTHONPATH={value}"], environment_errors(image_action(PYTHONPATH=value)))

    def test_rejects_options_that_ignore_pythonpath(self) -> None:
        self.assertEqual(
            ["interpreter options -E, -I ignore PYTHONPATH"],
            environment_errors(image_action("-Is", "-sE")),
        )

    def test_rejects_unexpected_variable(self) -> None:
        self.assertEqual(["unexpected HOME=/home/user"], environment_errors(image_action(HOME="/home/user")))

    def test_rejects_release_variables_on_tracer_action(self) -> None:
        # A tracer action that installs from a Debian snapshot runs offline, but is still not a release.
        for offline in (False, True):
            with self.subTest(offline=offline):
                self.assertEqual(
                    [
                        "unexpected MKOSI_HOST_DISTRIBUTION=debian",
                        "unexpected MKOSI_HOST_RELEASE=trixie",
                        "unexpected SOURCE_DATE_EPOCH=0",
                    ],
                    environment_errors(
                        image_action(
                            offline=offline,
                            MKOSI_HOST_DISTRIBUTION="debian",
                            MKOSI_HOST_RELEASE="trixie",
                            SOURCE_DATE_EPOCH="0",
                        )
                    ),
                )

    def test_requires_release_variables_on_release_action(self) -> None:
        action = image_action(release=True, MKOSI_HOST_RELEASE=None, SOURCE_DATE_EPOCH=None)

        self.assertEqual(["missing MKOSI_HOST_RELEASE", "missing SOURCE_DATE_EPOCH"], environment_errors(action))


class InterpreterFlagsTest(unittest.TestCase):
    def flags(self, *options: str) -> set[str]:
        return interpreter_flags(["python3", *options, "script.py", "-I"])

    def test_splits_combined_short_options(self) -> None:
        self.assertEqual({"I", "s", "E"}, self.flags("-Is", "-sE"))

    def test_skips_separate_option_values(self) -> None:
        self.assertEqual({"X", "I", "W"}, self.flags("-X", "utf8", "-I", "-W", "Ignore"))

    def test_skips_attached_option_values(self) -> None:
        self.assertEqual({"s", "X"}, self.flags("-sXImportTime"))

    def test_skips_long_option_values(self) -> None:
        self.assertEqual({"E"}, self.flags("--check-hash-based-pycs", "always", "-E"))

    def test_stops_at_program_options(self) -> None:
        for options in (("-c", "-I"), ("-m", "-I"), ("-sm", "-I"), ("--", "-I")):
            with self.subTest(options=options):
                self.assertNotIn("I", interpreter_flags(["python3", *options]))


class GraphErrorsTest(unittest.TestCase):
    def test_prefixes_errors_with_target_label(self) -> None:
        graph = {
            "targets": [{"id": 1, "label": "//pkg:image"}, {"id": 2, "label": "//pkg:release"}],
            "actions": [{"mnemonic": "Other"}, image_action(PATH="/bin"), image_action(release=True)],
        }

        self.assertEqual(["//pkg:image: invalid PATH=/bin"], graph_errors(graph))

    def test_requires_release_and_tracer_actions(self) -> None:
        cases: tuple[tuple[list[dict[str, Any]], list[str]], ...] = (
            ([image_action()], ["no release MkosiImage action in the graph"]),
            ([image_action(release=True)], ["no tracer MkosiImage action in the graph"]),
            ([], ["no release MkosiImage action in the graph", "no tracer MkosiImage action in the graph"]),
        )
        for actions, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(expected, graph_errors({"actions": actions}))


if __name__ == "__main__":
    unittest.main()
