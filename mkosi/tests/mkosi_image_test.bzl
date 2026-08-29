"""Analysis tests for mkosi_image."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")
load("//mkosi:defs.bzl", "MkosiImageInfo", "mkosi_image")

def _provider_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)

    asserts.true(env, MkosiImageInfo in target)
    asserts.equals(env, "debian", target[MkosiImageInfo].distribution)
    asserts.equals(env, "subject.img", target[MkosiImageInfo].image.basename)
    asserts.equals(env, "mkosi", target[MkosiImageInfo].toolchain_name)

    actions = analysistest.target_actions(env)
    asserts.equals(env, 1, len(actions))
    asserts.equals(env, "FileWrite", actions[0].mnemonic)

    return analysistest.end(env)

_provider_test = analysistest.make(_provider_test_impl)

def mkosi_image_test_suite(name):
    mkosi_image(
        name = "subject",
        distribution = "debian",
        tags = ["manual"],
    )

    _provider_test(
        name = "provider_test",
        target_under_test = ":subject",
    )

    native.test_suite(
        name = name,
        tests = [":provider_test"],
    )
