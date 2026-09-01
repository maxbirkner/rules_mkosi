"""Independent consumer check for the public Debian toolchain API."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")
load(
    "@rules_mkosi//mkosi:defs.bzl",
    "DebianSnapshotInfo",
    "DebianToolsInfo",
    "MkosiImageInfo",
)

def _public_api_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    asserts.true(env, DebianToolsInfo in target)
    asserts.equals(env, "debian", target[DebianToolsInfo].distribution)
    asserts.equals(env, "13", target[DebianToolsInfo].release)
    asserts.equals(env, "3.14.7", target[DebianToolsInfo].python_version)
    asserts.true(env, target[DebianToolsInfo].launcher.executable != None)
    return analysistest.end(env)

public_api_test = analysistest.make(_public_api_test_impl)

def _mkosi_python_override_test_impl(ctx):
    env = analysistest.begin(ctx)
    info = analysistest.target_under_test(env)[platform_common.ToolchainInfo].mkosi
    asserts.equals(env, "3.14", info.python_version)
    asserts.equals(env, "3.14.0", info.resolved_python_version)
    asserts.true(
        env,
        "consumer_python" in info.resolved_python_interpreter.path,
        "mkosi toolchain selected the consumer-registered Python runtime",
    )
    return analysistest.end(env)

mkosi_python_override_test = analysistest.make(_mkosi_python_override_test_impl)

def _snapshot_public_api_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    asserts.true(env, DebianSnapshotInfo in target)
    info = target[DebianSnapshotInfo]
    asserts.equals(env, "debian", info.distribution)
    asserts.equals(env, "13", info.release)
    asserts.equals(env, "trixie", info.codename)
    asserts.equals(env, "amd64", info.architecture)
    asserts.equals(env, "20250814T000000Z", info.snapshot)
    asserts.equals(env, "repository_repository", info.repository.basename)
    return analysistest.end(env)

snapshot_public_api_test = analysistest.make(_snapshot_public_api_test_impl)

def _image_public_api_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    asserts.true(env, MkosiImageInfo in target)
    asserts.equals(env, "demo.raw", target[MkosiImageInfo].image.basename)
    return analysistest.end(env)

image_public_api_test = analysistest.make(_image_public_api_test_impl)
