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
    asserts.equals(env, 2, len(actions))
    asserts.equals(env, "Action", actions[0].mnemonic)
    asserts.equals(env, "FileWrite", actions[1].mnemonic)

    return analysistest.end(env)

def _toolchain_provider_test_impl(ctx):
    env = analysistest.begin(ctx)
    info = analysistest.target_under_test(env)[platform_common.ToolchainInfo].mkosi

    asserts.equals(env, "27", info.version)
    asserts.equals(
        env,
        "fa34b3ba66cc71d202b267a0f55e6c77f41d8db273ea5404f7fad99e464835f8",
        info.source_sha256,
    )
    asserts.equals(env, "sha256-+jSzumbMcdICsmeg9V5sd/QdjbJz6lQE9/rZnkZINfg=", info.integrity)
    asserts.equals(env, "3.11", info.python_version)
    asserts.equals(env, "mkosi-v1", info.format_version)
    asserts.true(env, info.executable.basename.endswith("mkosi_cli"))
    asserts.true(env, info.files_to_run.executable != None)
    asserts.true(env, len(info.runfiles_files.to_list()) > 0)

    return analysistest.end(env)

_toolchain_provider_test = analysistest.make(_toolchain_provider_test_impl)

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

    _toolchain_provider_test(
        name = "mkosi_toolchain_provider_test",
        target_under_test = "@mkosi_toolchains//:mkosi_toolchain",
    )

    native.test_suite(
        name = name,
        tests = [
            ":debian_provider_test",
            ":ubuntu_provider_test",
            ":mkosi_toolchain_provider_test",
        ],
    )
