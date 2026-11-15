"""Analysis coverage for the public Debian snapshot rule."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")
load("//mkosi:defs.bzl", "DebianSnapshotInfo")
load(
    "//mkosi/debian:provenance.bzl",
    "DEBIAN_TOOLS_ARM64_LOCK_SHA256",
    "DEBIAN_TOOLS_LOCK_SHA256",
    "DEBIAN_TOOLS_SNAPSHOT",
    "DEBIAN_TOOLS_SNAPSHOT_URL",
)

def _provider_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    asserts.true(env, DebianSnapshotInfo in target)
    info = target[DebianSnapshotInfo]
    asserts.equals(env, "debian-snapshot-v1", info.format_version)
    asserts.equals(env, "debian", info.distribution)
    asserts.equals(env, "13", info.release)
    asserts.equals(env, "trixie", info.codename)
    asserts.equals(env, ctx.attr.expected_architecture, info.architecture)
    asserts.equals(env, ["main"], info.components)
    asserts.equals(env, DEBIAN_TOOLS_SNAPSHOT, info.snapshot)
    asserts.equals(
        env,
        DEBIAN_TOOLS_SNAPSHOT_URL,
        info.snapshot_url,
    )
    asserts.equals(
        env,
        ctx.attr.expected_lock_sha256,
        info.lock_sha256,
    )
    asserts.equals(env, "repository_repository", info.repository.basename)
    asserts.equals(env, "inrelease", info.inrelease.basename)
    asserts.equals(env, ctx.files.locked_packages, info.package_files.to_list())
    actions = analysistest.target_actions(env)
    asserts.equals(env, 1, len(actions))
    asserts.equals(env, "StageDebianSnapshot", actions[0].mnemonic)
    asserts.equals(env, 2, len(actions[0].outputs.to_list()))
    architecture = actions[0].argv.index("--architecture")
    asserts.equals(env, ctx.attr.expected_architecture, actions[0].argv[architecture + 1])
    asserts.true(
        env,
        "dists/trixie/main/binary-%s/Packages.xz" % ctx.attr.expected_architecture in actions[0].argv,
        "the stager reads the main index of the lock's architecture",
    )
    _assert_isolated_static_python(env, actions[0])
    return analysistest.end(env)

def _assert_isolated_static_python(env, action):
    """Asserts that the stager runs in isolated mode with the static interpreter's own standard library."""
    interpreter = action.argv[0]
    asserts.equals(env, "-I", action.argv[1])
    asserts.true(env, action.argv[2].endswith("/debian_snapshot.py"), "argv[2] is the stager script")
    asserts.equals(
        env,
        {
            "PATH": "",
            "PYTHONHOME": interpreter[:interpreter.rfind("/")],
            "PYTHONNOUSERSITE": "1",
        },
        action.env,
    )

debian_snapshot_provider_test = analysistest.make(
    _provider_test_impl,
    attrs = {
        "expected_architecture": attr.string(default = "amd64"),
        "expected_lock_sha256": attr.string(default = DEBIAN_TOOLS_LOCK_SHA256),
        "locked_packages": attr.label(default = "@mkosi_debian_package_inputs//:all"),
    },
)

def debian_snapshot_arm64_provider_test(name, target_under_test):
    """Checks the provider and staging action of the built-in arm64 snapshot.

    Args:
      name: Test name.
      target_under_test: The arm64 debian_snapshot target.
    """
    debian_snapshot_provider_test(
        name = name,
        target_under_test = target_under_test,
        expected_architecture = "arm64",
        expected_lock_sha256 = DEBIAN_TOOLS_ARM64_LOCK_SHA256,
        locked_packages = "@mkosi_debian_package_inputs_arm64//:all",
    )
