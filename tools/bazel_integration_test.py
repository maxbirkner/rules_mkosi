"""Real-Bazel integration test for the module-local cache wrapper."""

import os
import pathlib
import shutil
import stat
import subprocess
import sys


def run(command, cwd, env, capture=False):
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.STDOUT if capture else None,
    )


def startup_options(output_base):
    return (
        "--nosystem_rc",
        "--nohome_rc",
        "--command_port=0",
        "--invocation_policy=",
        "--unix_digest_hash_attribute_name=user.checksum",
        f"--output_base={output_base}",
    )


def main():
    wrapper = pathlib.Path(sys.argv[1]).resolve(strict=True)
    work = pathlib.Path(sys.argv[2]).resolve()
    expected_version = sys.argv[3]
    shutil.rmtree(work, ignore_errors=True)
    package = work / "package"
    package.mkdir(parents=True)
    (work / "MODULE.bazel").write_text(
        'module(name = "bazel_wrapper_integration")\n',
        encoding="utf-8",
    )
    (package / "BUILD.bazel").write_text(
        """
genrule(
    name = "cache_probe",
    outs = ["cache-probe.txt"],
    cmd = "echo module-local-cache > $@",
)
""".lstrip(),
        encoding="utf-8",
    )

    env = os.environ.copy()
    actual_version = run(
        (str(wrapper), "--version"),
        cwd=package,
        env=env,
        capture=True,
    ).stdout.strip()
    if actual_version != f"bazel {expected_version}":
        raise RuntimeError(
            f"expected Bazel {expected_version}, got {actual_version}"
        )

    output_bases = (work / ".output-a", work / ".output-b")
    outputs = []
    try:
        for output_base in output_bases:
            command = (
                str(wrapper),
                *startup_options(output_base),
                "build",
                "--lockfile_mode=off",
                "--color=no",
                "--curses=no",
                ":cache_probe",
            )
            outputs.append(run(command, package, env, capture=True).stdout)

        cache = work / ".cache" / "bazel-disk"
        rc = work / ".cache" / "bazel-wrapper.bazelrc"
        if not cache.is_dir() or cache.is_symlink():
            raise RuntimeError(f"exact module cache was not created: {cache}")
        if not rc.is_file() or rc.is_symlink():
            raise RuntimeError(f"secure generated rc was not created: {rc}")
        if stat.S_IMODE(rc.stat().st_mode) != 0o600:
            raise RuntimeError("generated rc permissions are not 0600")
        if (package / ".cache").exists():
            raise RuntimeError("wrapper created an invocation-relative cache")
        if "disk cache hit" not in outputs[1]:
            raise RuntimeError("second output base did not hit the disk cache")
        result = run(
            (
                str(wrapper),
                *startup_options(output_bases[1]),
                "query",
                "--lockfile_mode=off",
                ":cache_probe",
            ),
            package,
            env,
            capture=True,
        ).stdout
        labels = [
            line.strip()
            for line in result.splitlines()
            if line.startswith("//")
        ]
        if labels != ["//package:cache_probe"]:
            raise RuntimeError(
                f"relative label resolved incorrectly: {labels!r}"
            )
    finally:
        for output_base in output_bases:
            try:
                run(
                    (
                        str(wrapper),
                        *startup_options(output_base),
                        "shutdown",
                    ),
                    package,
                    env,
                )
            except subprocess.CalledProcessError:
                pass
        shutil.rmtree(work, ignore_errors=True)

    print(
        f"real wrapper integration passed Bazel {expected_version}: "
        "startup options, cache hit, and relative label"
    )


if __name__ == "__main__":
    main()
