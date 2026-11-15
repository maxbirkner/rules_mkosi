"""Analysis tests of image actions that build arm64 images on a Linux x86-64 execution platform."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")
load("//mkosi:defs.bzl", "MkosiImageInfo")
load("//mkosi/tests:analysis_test_helpers.bzl", "argv_preamble", "option_value", "single_action")

def _foreign_architecture_test_impl(ctx):
    env = analysistest.begin(ctx)
    action = single_action(env, ctx.attr.mnemonic)
    preamble = argv_preamble(action.argv)
    inputs = [file.path for file in action.inputs.to_list()]
    asserts.equals(env, "arm64", option_value(preamble, "--debian-snapshot-architecture"))
    asserts.equals(env, "arm64", option_value(preamble, "--foreign-architecture"))
    emulator = option_value(preamble, "--foreign-emulator")
    asserts.true(env, emulator.endswith("/qemu-user-linux-amd64-aarch64"), emulator)
    asserts.true(env, emulator in inputs, "the action reads the emulator")
    runner = option_value(preamble, "--binfmt-runner")
    asserts.true(env, runner.endswith("/binfmt_runner"), runner)
    asserts.true(env, runner in inputs, "the action reads the runner")
    return analysistest.end(env)

foreign_architecture_test = analysistest.make(
    _foreign_architecture_test_impl,
    attrs = {"mnemonic": attr.string(mandatory = True)},
)

def _arm64_image_test_impl(ctx):
    env = analysistest.begin(ctx)
    asserts.equals(env, "arm64", analysistest.target_under_test(env)[MkosiImageInfo].architecture)
    projection = single_action(env, "MkosiPartitionMetadata")
    asserts.equals(env, "arm64", option_value(projection.argv, "--architecture"))
    return analysistest.end(env)

arm64_image_test = analysistest.make(_arm64_image_test_impl)
