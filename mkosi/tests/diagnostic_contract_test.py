"""Portable contracts for actionable image and boot diagnostics."""

import contextlib
import importlib.util
import io
import pathlib
import sys
import types
import unittest

# The end of the output of a failed release child, with shortened paths.
_RELEASE_CHILD_TRACEBACK = b"""\
rules_mkosi release child failed: status=100; command=['mkosi/__main__.py', '-C', 'staging-root', 'build']
Traceback (most recent call last):
  File "mkosi/run.py", line 422, in spawn
    raise subprocess.CalledProcessError(returncode, cmdline)
subprocess.CalledProcessError: Command '['apt-get', 'install', 'netbase', 'rules-mkosi-hello']' returned non-zero \
exit status 100.

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "mkosi/private/run_mkosi.py", line 307, in _run_mkosi_in_process
    runpy.run_path(script, run_name="__main__")
    ~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "mkosi/run.py", line 138, in uncaught_exception_handler
    exit(rc)
    ~~~~^^^^
SystemExit: 100
"""
# The end of the output of a release build whose extra package depends on a package that no repository provides:
# APT's explanation, mkosi's log of the failed command, and the release child's traceback.
_UNMET_DEPENDENCY_OUTPUT = (
    b"""\
Reading package lists...
Building dependency tree...
Reading state information...
Solving dependencies...
Some packages could not be installed. This may mean that you have
requested an impossible situation or if you are using the unstable
distribution that some required packages have not yet been created
or been moved out of Incoming.
The following information may help to resolve the situation:

The following packages have unmet dependencies:
 rules-mkosi-hello : Depends: rules-mkosi-missing but it is not installable
E: Unable to correct problems, you have held broken packages.
E: The following information from --solver 3.0 may provide additional context:
   Unable to satisfy dependencies. Reached two conflicting decisions:
   1. rules-mkosi-hello:amd64=1.0 is selected for install
   2. rules-mkosi-hello:amd64 Depends rules-mkosi-missing
      but none of the choices are installable:
      [no choices]
\xe2\x80\xa3 [main] "apt-get install netbase rules-mkosi-hello" returned non-zero exit status 100.
"""
    + _RELEASE_CHILD_TRACEBACK
)


def _load(name: str, path: pathlib.Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("test module cannot be loaded: %s" % path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class DiagnosticContractTest(unittest.TestCase):
    diagnostics: types.ModuleType
    run_mkosi: types.ModuleType

    @classmethod
    def setUpClass(cls) -> None:
        root = pathlib.Path(__file__).parents[1] / "private"
        cls.diagnostics = _load("mkosi_diagnostics", root / "diagnostics.py")
        cls.run_mkosi = _load("run_mkosi", root / "run_mkosi.py")

    def test_all_failure_classes_are_actionable_and_preserve_detail(self) -> None:
        cases = {
            "KERNEL_CAPABILITY_FAILURE": "select a Linux runner that satisfies the kernel contract",
            "TOOLCHAIN_FAILURE": "register the required Bazel toolchain",
            "NETWORK_FAILURE": "allow the declared package network access",
            "PACKAGE_RESOLUTION_FAILURE": "add the missing package or dependency to the Debian snapshot lock",
            "EXTRA_PACKAGE_FAILURE": "pass extra_packages only Debian binary packages with unique names",
            "ASSEMBLY_FAILURE": "inspect the preserved mkosi output",
            "VM_FAILURE": "inspect the preserved serial, firmware, and QEMU logs",
        }
        for category, action in cases.items():
            output = io.StringIO()
            with contextlib.redirect_stderr(output):
                self.diagnostics.report(category, "original failure detail")
            message = output.getvalue()
            self.assertEqual(1, message.count(category + ":"))
            self.assertIn("original failure detail", message)
            self.assertIn("Action: " + action, message)

    def test_unknown_category_is_not_silently_accepted(self) -> None:
        with self.assertRaises(ValueError):
            self.diagnostics.report("UNKNOWN_FAILURE", "detail")

    def test_mkosi_output_classification_is_deterministic(self) -> None:
        cases = {
            b"could not download Packages": "NETWORK_FAILURE",
            b"systemd-repart: not found": "TOOLCHAIN_FAILURE",
            b"mkosi configuration is invalid": "ASSEMBLY_FAILURE",
            # APT's own outputs mention fetching, but a release build fails them only for packages it lacks.
            b"The following packages have unmet dependencies:\n"
            b" vendor-kernel : Depends: kmod but it is not installable\n": "PACKAGE_RESOLUTION_FAILURE",
            b"E: Failed to fetch file:/repository/pool/main/h/hello/hello_2.10-5_amd64.deb  File not found": (
                "PACKAGE_RESOLUTION_FAILURE"
            ),
            b"E: Unable to locate package vendor-firmware": "PACKAGE_RESOLUTION_FAILURE",
        }
        for output, expected in cases.items():
            self.assertEqual(expected, self.diagnostics.classify_mkosi_output(output))

    def _fail_mkosi(self, output: bytes) -> str:
        """Returns the diagnostic of an mkosi run that fails with status 100 and prints output to stderr."""
        result = types.SimpleNamespace(returncode=100, stdout=b"", stderr=output)
        message = io.StringIO()
        with contextlib.redirect_stderr(message), self.assertRaises(SystemExit):
            self.run_mkosi._run_mkosi("mkosi.py", ["build"], runner=lambda *_args, **_kwargs: result)
        return message.getvalue()

    def test_package_resolution_failure_detail_is_apt_explanation(self) -> None:
        multiple = (
            b"The following packages have unmet dependencies:\n"
            b" vendor-kernel : Depends: kmod but it is not installable\n"
            b"                 PreDepends: vendor-base (>= 2) but 1 is to be installed\n"
            b" vendor-tools : Depends: vendor-a but it is not installable or\n"
            b"                         vendor-b but it is not installable\n"
            b"E: Unable to correct problems, you have held broken packages.\n"
        )
        cases = {
            _UNMET_DEPENDENCY_OUTPUT: "rules-mkosi-hello : Depends: rules-mkosi-missing but it is not installable",
            multiple: (
                "vendor-kernel : Depends: kmod but it is not installable"
                " | vendor-kernel : PreDepends: vendor-base (>= 2) but 1 is to be installed"
                " | vendor-tools : Depends: vendor-a but it is not installable or vendor-b but it is not installable"
            ),
            b"E: Unable to locate package vendor-firmware\n": "E: Unable to locate package vendor-firmware",
            b"Package vendor-firmware is not available, but is referred to by another package.\n"
            b"E: Package 'vendor-firmware' has no installation candidate\n": (
                "E: Package 'vendor-firmware' has no installation candidate"
            ),
            b"E: Failed to fetch file:/repository/pool/main/h/hello/hello_2.10-5_amd64.deb  File not found\n": (
                "E: Failed to fetch file:/repository/pool/main/h/hello/hello_2.10-5_amd64.deb  File not found"
            ),
        }
        for apt_output, explanation in cases.items():
            with self.subTest(explanation=explanation):
                output = apt_output if apt_output is _UNMET_DEPENDENCY_OUTPUT else apt_output + _RELEASE_CHILD_TRACEBACK
                message = self._fail_mkosi(output)
                detail = message.splitlines()[0]
                self.assertEqual(
                    "PACKAGE_RESOLUTION_FAILURE: mkosi image assembly exited with status 100: " + explanation, detail
                )
                # The original output still follows the action, traceback included.
                self.assertIn("SystemExit: 100", message)

    def test_package_resolution_failure_without_apt_explanation_keeps_the_output_tail(self) -> None:
        detail = self._fail_mkosi(b"The following packages have unmet dependencies:\nSystemExit: 100\n").splitlines()[0]
        self.assertEqual(
            "PACKAGE_RESOLUTION_FAILURE: mkosi image assembly exited with status 100: "
            "The following packages have unmet dependencies: | SystemExit: 100",
            detail,
        )

    def test_kernel_preflight_failure_preserves_probe_without_a_host_fixture(self) -> None:
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

    def test_mkosi_process_failure_is_never_converted_to_success(self) -> None:
        result = types.SimpleNamespace(
            returncode=17,
            stdout=b"download failed: connection refused\n",
            stderr=b"",
        )
        output = io.StringIO()
        with contextlib.redirect_stderr(output), self.assertRaises(SystemExit) as failure:
            self.run_mkosi._run_mkosi(
                "mkosi.py",
                ["build"],
                runner=lambda *_args, **_kwargs: result,
            )
        self.assertEqual(17, failure.exception.code)
        message = output.getvalue()
        self.assertEqual(1, message.count("NETWORK_FAILURE:"))
        self.assertIn("download failed: connection refused", message)

    def test_mkosi_signal_failure_uses_shell_compatible_status(self) -> None:
        result = types.SimpleNamespace(
            returncode=-9,
            stdout=b"",
            stderr=b"mkosi process was killed\n",
        )
        output = io.StringIO()
        with contextlib.redirect_stderr(output), self.assertRaises(SystemExit) as failure:
            self.run_mkosi._run_mkosi(
                "mkosi.py",
                ["build"],
                runner=lambda *_args, **_kwargs: result,
            )
        self.assertEqual(137, failure.exception.code)
        self.assertIn("ASSEMBLY_FAILURE:", output.getvalue())
        self.assertIn("mkosi process was killed", output.getvalue())

    def test_child_exit_code_stays_in_the_portable_process_status_range(self) -> None:
        cases = {
            255: 255,
            256: 1,
            -127: 255,
            -128: 1,
            -9999: 1,
        }
        for returncode, expected in cases.items():
            status = self.diagnostics.child_exit_code(returncode)
            self.assertEqual(expected, status)
            self.assertGreaterEqual(status, 1)
            self.assertLessEqual(status, 255)
        with self.assertRaises(ValueError):
            self.diagnostics.child_exit_code(0)

    def test_fail_rejects_process_statuses_outside_one_byte_range(self) -> None:
        for exit_code in (0, 256):
            with self.assertRaises(ValueError):
                self.diagnostics.fail("ASSEMBLY_FAILURE", "detail", exit_code=exit_code)


if __name__ == "__main__":
    unittest.main()
