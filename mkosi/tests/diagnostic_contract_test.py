"""Portable contracts for actionable image and boot diagnostics."""

import contextlib
import importlib.util
import io
import pathlib
import sys
import types
import unittest


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class DiagnosticContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = pathlib.Path(__file__).parents[1] / "private"
        cls.diagnostics = _load("mkosi_diagnostics", root / "diagnostics.py")
        cls.run_mkosi = _load("run_mkosi", root / "run_mkosi.py")

    def test_all_failure_classes_are_actionable_and_preserve_detail(self):
        cases = {
            "KERNEL_CAPABILITY_FAILURE": "select a Linux runner that satisfies the kernel contract",
            "TOOLCHAIN_FAILURE": "register the required Bazel toolchain",
            "NETWORK_FAILURE": "allow the declared package network access",
            "ASSEMBLY_FAILURE": "inspect the preserved mkosi output",
            "VM_FAILURE": "inspect the preserved serial and QEMU logs",
        }
        for category, action in cases.items():
            output = io.StringIO()
            with contextlib.redirect_stderr(output):
                self.diagnostics.report(category, "original failure detail")
            message = output.getvalue()
            self.assertEqual(1, message.count(category + ":"))
            self.assertIn("original failure detail", message)
            self.assertIn("Action: " + action, message)

    def test_unknown_category_is_not_silently_accepted(self):
        with self.assertRaises(ValueError):
            self.diagnostics.report("UNKNOWN_FAILURE", "detail")

    def test_mkosi_output_classification_is_deterministic(self):
        cases = {
            b"could not download Packages": "NETWORK_FAILURE",
            b"systemd-repart: not found": "TOOLCHAIN_FAILURE",
            b"mkosi configuration is invalid": "ASSEMBLY_FAILURE",
        }
        for output, expected in cases.items():
            self.assertEqual(expected, self.diagnostics.classify_mkosi_output(output))

    def test_kernel_preflight_failure_preserves_probe_without_a_host_fixture(self):
        result = types.SimpleNamespace(
            returncode=1,
            stdout=b"FAIL user_namespace: enable unprivileged user namespaces\n",
            stderr=b"RESULT kernel_contract: FAIL\n",
        )
        output = io.StringIO()
        with contextlib.redirect_stderr(output), self.assertRaises(SystemExit):
            self.diagnostics.run_kernel_preflight(
                "kernel-preflight",
                "mkosi image assembly",
                runner=lambda *_args, **_kwargs: result,
            )
        message = output.getvalue()
        self.assertEqual(1, message.count("KERNEL_CAPABILITY_FAILURE:"))
        self.assertIn("FAIL user_namespace", message)
        self.assertIn("RESULT kernel_contract: FAIL", message)

    def test_mkosi_process_failure_is_never_converted_to_success(self):
        result = types.SimpleNamespace(
            returncode=17,
            stdout=b"download failed: connection refused\n",
            stderr=b"",
        )
        output = io.StringIO()
        with contextlib.redirect_stderr(output), self.assertRaises(SystemExit):
            self.run_mkosi._run_mkosi(
                "mkosi.py",
                ["build"],
                runner=lambda *_args, **_kwargs: result,
            )
        message = output.getvalue()
        self.assertEqual(1, message.count("NETWORK_FAILURE:"))
        self.assertIn("download failed: connection refused", message)


if __name__ == "__main__":
    unittest.main()
