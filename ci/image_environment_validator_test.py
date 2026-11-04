"""Tests for the mkosi image action environment audit."""

import pathlib
import sys
import unittest
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from image_environment_validator import environment_errors, graph_errors

PYTHONPATH = "external/+mkosi+mkosi_toolchains:external/rules_python++pip+pefile/site-packages"
RELEASE = {"MKOSI_HOST_DISTRIBUTION": "debian", "MKOSI_HOST_RELEASE": "trixie", "SOURCE_DATE_EPOCH": "0"}


def image_action(*options: str, **environment: str | None) -> dict[str, Any]:
    """Returns a tracer MkosiImage action whose environment entries are replaced, or removed when None."""
    values: dict[str, str | None] = {
        "PATH": "",
        "PYTHONNOUSERSITE": "1",
        "MKOSI_FORCE_USERNS_FALLBACK": "1",
        "PYTHONPATH": PYTHONPATH,
    }
    values.update(environment)
    # aquery omits the value of empty variables.
    variables = [
        {"key": key} | ({"value": value} if value else {}) for key, value in values.items() if value is not None
    ]
    return {
        "mnemonic": "MkosiImage",
        "targetId": 1,
        "arguments": ["bazel-out/bin/python3", *options, "mkosi/private/run_mkosi.py"],
        "environmentVariables": variables,
    }


class EnvironmentErrorsTest(unittest.TestCase):
    def test_accepts_tracer_environment(self) -> None:
        self.assertEqual([], environment_errors(image_action()))

    def test_accepts_release_environment(self) -> None:
        self.assertEqual([], environment_errors(image_action(**RELEASE)))

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
            environment_errors(image_action("-I", "-E")),
        )

    def test_rejects_unexpected_variable(self) -> None:
        self.assertEqual(["unexpected HOME=/home/user"], environment_errors(image_action(HOME="/home/user")))

    def test_rejects_partial_release_environment(self) -> None:
        self.assertEqual(
            ["incomplete release environment: SOURCE_DATE_EPOCH"],
            environment_errors(image_action(SOURCE_DATE_EPOCH="0")),
        )


class GraphErrorsTest(unittest.TestCase):
    def test_prefixes_errors_with_target_label(self) -> None:
        graph = {
            "targets": [{"id": 1, "label": "//pkg:image"}],
            "actions": [{"mnemonic": "Other"}, image_action(PATH="/bin")],
        }

        self.assertEqual(["//pkg:image: invalid PATH=/bin"], graph_errors(graph))

    def test_requires_an_image_action(self) -> None:
        self.assertEqual(["no MkosiImage action in the graph"], graph_errors({"actions": []}))


if __name__ == "__main__":
    unittest.main()
