"""Analysis tests for mkosi_image."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")
load("//mkosi:defs.bzl", "MkosiImageInfo", "mkosi_image")

def _provider_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)

    asserts.true(env, MkosiImageInfo in target)
    asserts.equals(env, ctx.attr.expected_distribution, target[MkosiImageInfo].distribution)
    asserts.equals(env, ctx.attr.expected_output, target[MkosiImageInfo].image.basename)
    asserts.equals(env, "mkosi", target[MkosiImageInfo].toolchain_name)

    actions = analysistest.target_actions(env)
    asserts.equals(env, 1, len(actions))
    asserts.equals(env, "FileWrite", actions[0].mnemonic)

    return analysistest.end(env)

_provider_test = analysistest.make(
    _provider_test_impl,
    attrs = {
        "expected_distribution": attr.string(mandatory = True),
        "expected_output": attr.string(mandatory = True),
    },
)

def mkosi_image_test_suite(name):
    """Defines analysis tests for every supported placeholder distribution.

    Args:
      name: Name of the generated test suite.
    """
    mkosi_image(
        name = "debian_subject",
        distribution = "debian",
        tags = ["manual"],
    )

    _provider_test(
        name = "debian_provider_test",
        expected_distribution = "debian",
        expected_output = "debian_subject.img",
        target_under_test = ":debian_subject",
    )

    mkosi_image(
        name = "ubuntu_subject",
        distribution = "ubuntu",
        tags = ["manual"],
    )

    _provider_test(
        name = "ubuntu_provider_test",
        expected_distribution = "ubuntu",
        expected_output = "ubuntu_subject.img",
        target_under_test = ":ubuntu_subject",
    )

    native.test_suite(
        name = name,
        tests = [
            ":debian_provider_test",
            ":ubuntu_provider_test",
        ],
    )
