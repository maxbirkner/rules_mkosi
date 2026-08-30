"""Analysis tests for mkosi_image."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")
load("//mkosi:defs.bzl", "MkosiImageInfo", "MkosiQemuToolchainInfo", "mkosi_image")
load("//mkosi/debian:toolchain.bzl", "DebianToolsInfo")

def _provider_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)

    asserts.true(env, MkosiImageInfo in target)
    asserts.equals(env, ctx.attr.expected_output, target[MkosiImageInfo].image.basename)

    actions = analysistest.target_actions(env)
    asserts.equals(env, 1, len(actions))
    asserts.equals(env, "MkosiImage", actions[0].mnemonic)
    action_inputs = [file.basename for file in actions[0].inputs.to_list()]
    asserts.true(env, ctx.attr.expected_config in action_inputs)
    asserts.true(env, "tree_root_root" in action_inputs)
    asserts.true(env, "mkosi_cli" in action_inputs)
    asserts.false(env, "flat.tar" in action_inputs)
    asserts.false(env, "launcher" in action_inputs)
    asserts.equals(env, 1, len(actions[0].outputs.to_list()))
    asserts.equals(env, ctx.attr.expected_output, actions[0].outputs.to_list()[0].basename)
    asserts.true(env, actions[0].argv[0].endswith("mkosi_cli"))
    asserts.equals(env, "-I", actions[0].argv[1])
    asserts.true(env, actions[0].argv[2].endswith(ctx.attr.expected_config))
    asserts.equals(env, "--tools-tree", actions[0].argv[3])
    asserts.true(env, actions[0].argv[4].endswith("tree_root_root"))
    asserts.equals(env, "--output-directory", actions[0].argv[5])
    asserts.true(env, actions[0].argv[6].endswith("/mkosi/tests"))
    asserts.equals(env, "--output", actions[0].argv[7])
    asserts.equals(env, "debian_subject", actions[0].argv[8])
    asserts.equals(env, "build", actions[0].argv[-1])
    asserts.equals(env, "", actions[0].env["PATH"])

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

def _qemu_toolchain_provider_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    info = target[platform_common.ToolchainInfo].qemu

    asserts.true(env, MkosiQemuToolchainInfo in target)
    asserts.equals(env, "linux", info.execution_os)
    asserts.equals(env, "x86_64", info.execution_cpu)
    asserts.equals(env, "11.0.0.1", info.qemu_version)
    asserts.equals(env, "edk2-stable202605-r1", info.ovmf_version)
    asserts.equals(
        env,
        "b84d359893a0a1d565f368adb8290933ef9c99431acd98cff0fc4c9b35de3d22",
        info.qemu_sha256,
    )
    asserts.equals(
        env,
        "8ae4d2d73161cc2335f5675d3b8b6edfa0642301679764a246940488ea3ce20d",
        info.ovmf_sha256,
    )
    asserts.true(env, info.qemu_system.basename == "qemu-system-x86_64")
    asserts.true(env, info.qemu_files_to_run.executable != None)
    asserts.true(env, info.ovmf_code.basename == "code.fd")
    asserts.true(env, info.ovmf_vars.basename == "vars.fd")
    return analysistest.end(env)

def _debian_tools_provider_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    info = target[platform_common.ToolchainInfo].debian_tools

    asserts.true(env, DebianToolsInfo in target)
    asserts.equals(env, "debian-tools-v1", info.format_version)
    asserts.equals(env, "debian", info.distribution)
    asserts.equals(env, "13", info.release)
    asserts.equals(
        env,
        "d9d4ebdb252324d84d2817397df31fd016fbb6020f4919e2effbf8f7958fd657",
        info.archive_sha256,
    )
    asserts.equals(env, "trixie", info.codename)
    asserts.equals(env, "amd64", info.architecture)
    asserts.equals(env, "20250814T000000Z", info.snapshot)
    asserts.equals(
        env,
        "8828eb8e8f4b207e8cd765ebabb1ebdf23ffd006893d5dbd7ddb65bd481c0077",
        info.lock_sha256,
    )
    asserts.equals(
        env,
        "https://snapshot.debian.org/archive/debian/20250814T000000Z",
        info.snapshot_url,
    )
    asserts.equals(env, "flat.tar", info.tree.basename)
    asserts.equals(env, "tree_root_root", info.tree_root.basename)
    asserts.equals(env, "launcher", info.launcher.executable.basename)
    asserts.true(env, info.launcher.executable != None)
    asserts.true(env, info.tree_files_to_run.executable == None)
    asserts.equals(env, 11, len(info.required_components))
    asserts.true(env, info.provenance.basename == "provenance.bzl")
    return analysistest.end(env)

_debian_tools_provider_test = analysistest.make(_debian_tools_provider_test_impl)

_qemu_toolchain_provider_test = analysistest.make(_qemu_toolchain_provider_test_impl)

_provider_test = analysistest.make(
    _provider_test_impl,
    attrs = {
        "expected_config": attr.string(mandatory = True),
        "expected_output": attr.string(mandatory = True),
    },
)

def mkosi_image_test_suite(name):
    """Defines analysis tests for the config-driven image action.

    Args:
      name: Name of the generated test suite.
    """
    mkosi_image(
        name = "debian_subject",
        config = "testdata/minimal.conf",
        tags = ["manual"],
    )

    _provider_test(
        name = "debian_provider_test",
        expected_config = "minimal.conf",
        expected_output = "debian_subject.raw",
        target_under_test = ":debian_subject",
    )

    _toolchain_provider_test(
        name = "mkosi_toolchain_provider_test",
        target_under_test = "@mkosi_toolchains//:mkosi_toolchain",
    )

    _qemu_toolchain_provider_test(
        name = "qemu_toolchain_provider_test",
        target_under_test = "@mkosi_toolchains//:qemu_ovmf_toolchain",
    )

    _debian_tools_provider_test(
        name = "debian_tools_provider_test",
        target_under_test = "@mkosi_debian_tools//:toolchain",
    )

    native.test_suite(
        name = name,
        tests = [
            ":debian_provider_test",
            ":mkosi_toolchain_provider_test",
            ":qemu_toolchain_provider_test",
            ":debian_tools_provider_test",
        ],
    )
