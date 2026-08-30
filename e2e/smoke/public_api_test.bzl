"""Independent consumer check for the public Debian toolchain API."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")
load("@rules_mkosi//mkosi:defs.bzl", "DebianToolsInfo")

def _public_api_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    asserts.true(env, DebianToolsInfo in target)
    asserts.equals(env, "debian", target[DebianToolsInfo].distribution)
    asserts.equals(env, "13", target[DebianToolsInfo].release)
    asserts.true(env, target[DebianToolsInfo].launcher.executable != None)
    return analysistest.end(env)

public_api_test = analysistest.make(_public_api_test_impl)
