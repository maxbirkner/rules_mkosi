"""Execution tests for the module-local Bazel disk-cache wrapper."""

import os
import pathlib
import shutil
import stat
import subprocess
import sys
import unittest


_FAKE_BAZEL = r"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\0' "$PWD" "${USE_BAZEL_VERSION:-}" "$@" >"$CAPTURE_FILE"
cache=
while (($#)); do
    case "$1" in
        --disk_cache=*)
            cache=${1#--disk_cache=}
            break
            ;;
        --disk_cache)
            cache=${2:?missing disk cache value}
            break
            ;;
        *)
            shift
            ;;
    esac
done
if [[ -n "$cache" ]]; then
    mkdir -p "$cache"
fi
"""


class BazelWrapperTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wrapper = pathlib.Path(sys.argv[1]).resolve()
        cls.work = pathlib.Path(os.environ["TEST_TMPDIR"]) / "bazel-wrapper-test"
        shutil.rmtree(cls.work, ignore_errors=True)
        cls.work.mkdir()
        cls.backend_dir = cls.work / "backend"
        cls.backend_dir.mkdir()
        cls.backend = cls.backend_dir / "bazel"
        cls.backend.write_text(_FAKE_BAZEL, encoding="utf-8")
        cls.backend.chmod(cls.backend.stat().st_mode | stat.S_IXUSR)

    def setUp(self):
        self.case = self.work / self._testMethodName
        shutil.rmtree(self.case, ignore_errors=True)
        self.case.mkdir()
        self.capture = self.case / "capture"

    def module(self, relative, bazelrc=False):
        root = self.case / relative
        root.mkdir(parents=True)
        (root / "MODULE.bazel").write_text(
            'module(name = "wrapper_test")\n',
            encoding="utf-8",
        )
        if bazelrc:
            (root / ".bazelrc").write_text(
                "build --disk_cache=.cache/bazel-disk\n",
                encoding="utf-8",
            )
        return root

    def invoke(self, cwd, version, *arguments):
        env = os.environ.copy()
        env.update(
            {
                "CAPTURE_FILE": str(self.capture),
                "PATH": os.pathsep.join(
                    (
                        str(self.wrapper.parent),
                        str(self.backend_dir),
                        env["PATH"],
                    )
                ),
                "USE_BAZEL_VERSION": version,
            }
        )
        subprocess.run(
            (str(self.wrapper), *arguments),
            cwd=cwd,
            env=env,
            check=True,
        )
        fields = self.capture.read_bytes().split(b"\0")
        return [field.decode() for field in fields[:-1]]

    def assert_invocation(self, actual, cwd, version, arguments):
        self.assertEqual(actual, [str(cwd), version, *arguments])

    def test_root_and_nested_cwd_preserve_labels_and_argv(self):
        root = self.module("module", bazelrc=True)
        nested = root / "pkg" / "nested directory"
        nested.mkdir(parents=True)
        output_base = self.case / "output base"
        for version in ("8.5.1", "9.2.0"):
            with self.subTest(version=version, cwd="root"):
                actual = self.invoke(root, version, "build", "//...")
                self.assert_invocation(
                    actual,
                    root,
                    version,
                    (
                        "build",
                        f"--disk_cache={root}/.cache/bazel-disk",
                        "//...",
                    ),
                )
            with self.subTest(version=version, cwd="nested"):
                actual = self.invoke(
                    nested,
                    version,
                    "--output_base",
                    str(output_base),
                    "--failure_detail_out",
                    str(self.case / "failure detail"),
                    "--host_jvm_args",
                    "-Dmessage=value with spaces",
                    "test",
                    "--test_env=VALUE=two words",
                    ":target",
                    ":target with spaces",
                )
                self.assert_invocation(
                    actual,
                    nested,
                    version,
                    (
                        "--output_base",
                        str(output_base),
                        "--failure_detail_out",
                        str(self.case / "failure detail"),
                        "--host_jvm_args",
                        "-Dmessage=value with spaces",
                        "test",
                        f"--disk_cache={root}/.cache/bazel-disk",
                        "--test_env=VALUE=two words",
                        ":target",
                        ":target with spaces",
                    ),
                )
            self.assertTrue((root / ".cache" / "bazel-disk").is_dir())
            self.assertFalse((nested / ".cache").exists())

    def test_nearest_module_without_bazelrc_owns_cache(self):
        outer = self.module("outer", bazelrc=True)
        fixture = outer / "fixtures" / "standalone"
        fixture.mkdir(parents=True)
        (fixture / "MODULE.bazel").write_text(
            'module(name = "standalone")\n',
            encoding="utf-8",
        )
        nested = fixture / "package"
        nested.mkdir()
        for version in ("8.5.1", "9.2.0"):
            with self.subTest(version=version):
                actual = self.invoke(nested, version, "query", ":local")
                self.assert_invocation(
                    actual,
                    nested,
                    version,
                    (
                        "query",
                        f"--disk_cache={fixture}/.cache/bazel-disk",
                        ":local",
                    ),
                )
        self.assertTrue((fixture / ".cache" / "bazel-disk").is_dir())
        self.assertFalse((outer / ".cache").exists())
        self.assertFalse((nested / ".cache").exists())

    def test_explicit_disk_cache_override_is_preserved(self):
        root = self.module("module")
        nested = root / "pkg"
        nested.mkdir()
        for version, option in (
            ("8.5.1", (f"--disk_cache={self.case}/user cache",)),
            ("9.2.0", ("--disk_cache", f"{self.case}/user cache")),
        ):
            with self.subTest(version=version):
                actual = self.invoke(nested, version, "test", *option, ":target")
                self.assert_invocation(
                    actual,
                    nested,
                    version,
                    ("test", *option, ":target"),
                )
        self.assertTrue((self.case / "user cache").is_dir())
        self.assertFalse((root / ".cache").exists())
        self.assertFalse((nested / ".cache").exists())

    def test_disk_cache_text_is_not_mistaken_for_an_override(self):
        root = self.module("module")
        actual = self.invoke(
            root,
            "9.2.0",
            "test",
            "--define=message=--disk_cache=relative",
            "--",
            "--disk_cache=also-a-target",
        )
        self.assert_invocation(
            actual,
            root,
            "9.2.0",
            (
                "test",
                f"--disk_cache={root}/.cache/bazel-disk",
                "--define=message=--disk_cache=relative",
                "--",
                "--disk_cache=also-a-target",
            ),
        )
        self.assertTrue((root / ".cache" / "bazel-disk").is_dir())
        self.assertFalse((root / "relative").exists())

    def test_non_build_command_remains_transparent(self):
        root = self.module("module")
        actual = self.invoke(root, "8.5.1", "mod", "deps")
        self.assert_invocation(actual, root, "8.5.1", ("mod", "deps"))
        self.assertFalse((root / ".cache").exists())

    def test_path_containing_wrapper_does_not_recurse(self):
        root = self.module("module")
        actual = self.invoke(root, "9.2.0", "info", "workspace")
        self.assert_invocation(
            actual,
            root,
            "9.2.0",
            (
                "info",
                f"--disk_cache={root}/.cache/bazel-disk",
                "workspace",
            ),
        )


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
