"""Tests for the derivation of an image version from the inputs of its build action."""

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "private"))
import input_version

CONFIG = "bazel-out/k8-fastbuild/bin/image.staging/mkosi.conf"
PAYLOAD_TREE = "bazel-out/k8-fastbuild/bin/payload"
TOOLCHAIN_SCRIPT = "external/+mkosi+mkosi_source/mkosi/__main__.py"
DEBIAN_TOOLS_TREE = "bazel-out/k8-opt-exec-ST-0123/bin/external/+debian+tools/tree"
INPUTS = [CONFIG, PAYLOAD_TREE, TOOLCHAIN_SCRIPT, DEBIAN_TOOLS_TREE]
COMMAND_LINE = ["python3", "run_mkosi.py", "--image-version-file", "bazel-out/k8-fastbuild/bin/image.image-version"]
ENVIRONMENT = {"PATH": "", "SOURCE_DATE_EPOCH": "0"}
REQUIREMENTS = {"block-network": "1", "no-remote-exec": "1"}


def _write(root, path, content, executable=False):
    target = Path(root, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    target.chmod(0o755 if executable else 0o644)


def _populate(root):
    _write(root, CONFIG, "[Content]\nBootable=yes\n")
    _write(root, PAYLOAD_TREE + "/usr/local/bin/tool", "#!/bin/sh\n", executable=True)
    _write(root, PAYLOAD_TREE + "/etc/tool.conf", "level=1\n")
    _write(root, TOOLCHAIN_SCRIPT, "print('mkosi')\n")
    _write(root, DEBIAN_TOOLS_TREE + "/usr/bin/systemd-repart", "repart 1\n", executable=True)


class InputVersionTest(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self._cwd = os.getcwd()
        self.addCleanup(os.chdir, self._cwd)
        self.execroot = Path(self._directory.name, "execroot")
        self.execroot.mkdir()
        _populate(self.execroot)
        os.chdir(self.execroot)
        self.baseline = self.digest()

    def digest(self, inputs=INPUTS, command_line=COMMAND_LINE, environment=ENVIRONMENT, requirements=REQUIREMENTS):
        return input_version.digest(inputs, command_line, environment, requirements)

    def digest_with_symlinks(self, symlinks):
        return input_version.digest(INPUTS, COMMAND_LINE, ENVIRONMENT, REQUIREMENTS, symlinks)

    def assertChanges(self, digest=None):
        self.assertNotEqual(self.baseline, self.digest() if digest is None else digest)

    def test_identical_inputs_give_identical_versions_regardless_of_order_and_execution_root(self):
        self.assertEqual(self.baseline, self.digest(inputs=list(reversed(INPUTS))))
        other = Path(self._directory.name, "other-output-base", "execroot")
        other.mkdir(parents=True)
        _populate(other)
        os.chdir(other)
        self.assertEqual(self.baseline, self.digest())

    def test_sandbox_symlinks_are_followed_to_their_content(self):
        sandbox = Path(self._directory.name, "sandbox", "execroot")
        for path in (CONFIG, TOOLCHAIN_SCRIPT):
            (sandbox / path).parent.mkdir(parents=True, exist_ok=True)
            (sandbox / path).symlink_to(self.execroot / path)
        for tree in (PAYLOAD_TREE, DEBIAN_TOOLS_TREE):
            for source in (self.execroot / tree).rglob("*"):
                if source.is_file():
                    link = sandbox / source.relative_to(self.execroot)
                    link.parent.mkdir(parents=True, exist_ok=True)
                    link.symlink_to(source)
        os.chdir(sandbox)
        self.assertEqual(self.baseline, self.digest())

    def test_configuration_names_in_output_paths_are_ignored(self):
        renamed = [path.replace("k8-fastbuild", "k8-opt") for path in INPUTS]
        for old, new in zip(INPUTS, renamed, strict=True):
            if old != new:
                Path(new).parent.mkdir(parents=True, exist_ok=True)
                Path(old).rename(new)
        command_line = [argument.replace("k8-fastbuild", "k8-opt") for argument in COMMAND_LINE]
        self.assertEqual(self.baseline, self.digest(inputs=renamed, command_line=command_line))

    def test_configuration_file_change_changes_version(self):
        _write(self.execroot, CONFIG, "[Content]\nBootable=no\n")
        self.assertChanges()

    def test_rootfs_payload_changes_change_version(self):
        _write(self.execroot, PAYLOAD_TREE + "/etc/tool.conf", "level=2\n")
        self.assertChanges()

    def test_added_empty_directory_changes_version(self):
        (self.execroot / PAYLOAD_TREE / "var/lib/tool").mkdir(parents=True)
        self.assertChanges()

    def test_renamed_file_changes_version(self):
        payload = self.execroot / PAYLOAD_TREE
        (payload / "etc/tool.conf").rename(payload / "etc/other.conf")
        self.assertChanges()

    def test_executable_bit_changes_version(self):
        (self.execroot / CONFIG).chmod(0o755)
        self.assertChanges()

    def test_toolchain_changes_change_version(self):
        _write(self.execroot, TOOLCHAIN_SCRIPT, "print('patched mkosi')\n")
        self.assertChanges()
        _populate(self.execroot)
        _write(self.execroot, DEBIAN_TOOLS_TREE + "/usr/bin/systemd-repart", "repart 2\n", executable=True)
        self.assertChanges()

    def test_additional_input_changes_version(self):
        _write(self.execroot, "external/+mkosi+mkosi_source/mkosi/patch.py", "")
        self.assertChanges(self.digest(inputs=[*INPUTS, "external/+mkosi+mkosi_source/mkosi/patch.py"]))

    def test_declared_version_input_change_changes_version(self):
        certificate = "certificates/db.crt"
        _write(self.execroot, certificate, "certificate 1\n")
        declared = self.digest(inputs=[*INPUTS, certificate])
        self.assertNotEqual(self.baseline, declared)
        _write(self.execroot, certificate, "certificate 2\n")
        self.assertNotEqual(declared, self.digest(inputs=[*INPUTS, certificate]))

    def test_declared_signing_roles_change_version(self):
        uki = {"signing_certificates": {"": "certificates/db.crt"}}
        boot_loader = {"signing_certificates": {"EFI/systemd/systemd-bootx64.efi": "certificates/db.crt"}}
        declared = input_version.digest(INPUTS, COMMAND_LINE, ENVIRONMENT, REQUIREMENTS, declared=uki)
        self.assertNotEqual(self.baseline, declared)
        moved = input_version.digest(INPUTS, COMMAND_LINE, ENVIRONMENT, REQUIREMENTS, declared=boot_loader)
        self.assertNotEqual(declared, moved)
        opt = {"signing_certificates": {"": "bazel-out/k8-opt/bin/db.crt"}}
        fastbuild = {"signing_certificates": {"": "bazel-out/k8-fastbuild/bin/db.crt"}}
        self.assertEqual(
            input_version.digest(INPUTS, COMMAND_LINE, ENVIRONMENT, REQUIREMENTS, declared=opt),
            input_version.digest(INPUTS, COMMAND_LINE, ENVIRONMENT, REQUIREMENTS, declared=fastbuild),
        )

    def test_command_line_environment_and_requirements_change_version(self):
        self.assertChanges(self.digest(command_line=[*COMMAND_LINE, "--image-id=other"]))
        self.assertChanges(self.digest(environment=ENVIRONMENT | {"SOURCE_DATE_EPOCH": "1"}))
        self.assertChanges(self.digest(requirements={"no-remote-exec": "1"}))

    def test_dangling_symlink_is_rejected(self):
        (self.execroot / PAYLOAD_TREE / "etc/missing").symlink_to("does-not-exist")
        with self.assertRaisesRegex(ValueError, "dangling symlink"):
            self.digest()

    def test_declared_symlinks_are_identified_by_their_target_text(self):
        link = "bazel-out/k8-fastbuild/bin/tool.venv/bin/python3"
        (self.execroot / link).parent.mkdir(parents=True)
        (self.execroot / link).symlink_to("../../tool.runfiles/python3")
        declared = self.digest_with_symlinks([link])
        self.assertNotEqual(self.baseline, declared)
        (self.execroot / link).unlink()
        (self.execroot / link).symlink_to("../../tool.runfiles/python4")
        self.assertNotEqual(declared, self.digest_with_symlinks([link]))
        other = Path(self._directory.name, "other-output-base", "execroot")
        _populate(other)
        (other / link.replace("k8-fastbuild", "k8-opt")).parent.mkdir(parents=True)
        (other / link.replace("k8-fastbuild", "k8-opt")).symlink_to("../../tool.runfiles/python3")
        os.chdir(other)
        self.assertEqual(declared, self.digest_with_symlinks([link.replace("k8-fastbuild", "k8-opt")]))

    def test_symlink_cycle_is_rejected(self):
        (self.execroot / PAYLOAD_TREE / "etc/loop").symlink_to("..")
        with self.assertRaisesRegex(ValueError, "symlink cycle"):
            self.digest()

    def test_main_writes_sixteen_hex_character_version_and_full_digest(self):
        inputs_file = Path(self._directory.name, "inputs.params")
        inputs_file.write_text("\n".join(INPUTS) + "\n", encoding="utf-8")
        version_file = Path(self._directory.name, "image-version")
        digest_file = Path(self._directory.name, "input-digest")
        input_version.main(
            [
                "--environment-json",
                '{"SOURCE_DATE_EPOCH": "0", "PATH": ""}',
                "--execution-requirements-json",
                '{"no-remote-exec": "1", "block-network": "1"}',
                "--version-output",
                str(version_file),
                "--digest-output",
                str(digest_file),
                "--inputs-file=" + str(inputs_file),
                "--command-line",
                *COMMAND_LINE,
            ]
        )
        self.assertRegex(version_file.read_text(encoding="ascii"), re.compile(r"\A[0-9a-f]{16}\n\Z"))
        self.assertEqual(self.baseline + "\n", digest_file.read_text(encoding="ascii"))
        self.assertEqual(self.baseline[:16] + "\n", version_file.read_text(encoding="ascii"))

    def test_main_reports_unreadable_inputs(self):
        inputs_file = Path(self._directory.name, "inputs.params")
        inputs_file.write_text("missing\n", encoding="utf-8")
        arguments = ["--environment-json", "{}", "--execution-requirements-json", "{}", "--version-output", "v"]
        arguments += ["--digest-output", "d", "--inputs-file", str(inputs_file), "--command-line"]
        with self.assertRaisesRegex(SystemExit, "IMAGE_INPUT_VERSION_FAILED: input does not exist"):
            input_version.main(arguments)


if __name__ == "__main__":
    unittest.main()
