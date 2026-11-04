"""Analysis coverage for the public Debian snapshot rule."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")
load("//mkosi:defs.bzl", "DebianSnapshotInfo")
load(
    "//mkosi/debian:provenance.bzl",
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
    asserts.equals(env, "amd64", info.architecture)
    asserts.equals(env, ["main"], info.components)
    asserts.equals(env, DEBIAN_TOOLS_SNAPSHOT, info.snapshot)
    asserts.equals(
        env,
        DEBIAN_TOOLS_SNAPSHOT_URL,
        info.snapshot_url,
    )
    asserts.equals(
        env,
        DEBIAN_TOOLS_LOCK_SHA256,
        info.lock_sha256,
    )
    asserts.equals(env, "repository_repository", info.repository.basename)
    asserts.equals(env, "inrelease", info.inrelease.basename)
    asserts.equals(env, ctx.files.locked_packages, info.package_files.to_list())
    actions = analysistest.target_actions(env)
    asserts.equals(env, 1, len(actions))
    asserts.equals(env, "StageDebianSnapshot", actions[0].mnemonic)
    asserts.equals(env, 2, len(actions[0].outputs.to_list()))
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
    attrs = {"locked_packages": attr.label(default = "@mkosi_debian_package_inputs//:all")},
)
