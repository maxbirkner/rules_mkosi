"""Cross-builds bootstrap executables for Linux aarch64 and checks the host's default bootstrap platform."""

load("@bazel_skylib//lib:unittest.bzl", "asserts", "unittest")
load("//mkosi/toolchain/bootstrap_cc:host_platform.bzl", "select_host_bootstrap_platform")

_BOOTSTRAP_PLATFORM = str(Label("//mkosi/toolchain:bootstrap_platform"))
_AARCH64_MUSL = str(Label("//mkosi/toolchain/bootstrap_cc:linux_aarch64_musl"))

def _select_aarch64_bootstrap_platform(_settings, _attr):
    return {_BOOTSTRAP_PLATFORM: _AARCH64_MUSL}

_aarch64_bootstrap_transition = transition(
    implementation = _select_aarch64_bootstrap_platform,
    inputs = [],
    outputs = [_BOOTSTRAP_PLATFORM],
)

def _aarch64_bootstrap_files_impl(ctx):
    return [DefaultInfo(files = depset(transitive = [target[DefaultInfo].files for target in ctx.attr.srcs]))]

aarch64_bootstrap_files = rule(
    implementation = _aarch64_bootstrap_files_impl,
    attrs = {
        "srcs": attr.label_list(
            cfg = _aarch64_bootstrap_transition,
            mandatory = True,
            doc = "bootstrap_binary targets, built for //mkosi/toolchain/bootstrap_cc:linux_aarch64_musl.",
        ),
        "_allowlist_function_transition": attr.label(
            default = "@bazel_tools//tools/allowlists/function_transition_allowlist",
        ),
    },
    doc = "Exposes the executables of bootstrap_binary targets built with the Linux aarch64 musl bootstrap platform.",
)

def _host_bootstrap_platform_test_impl(ctx):
    env = unittest.begin(ctx)
    aarch64 = "//mkosi/toolchain/bootstrap_cc:linux_aarch64_musl"
    x86_64 = "//mkosi/toolchain/bootstrap_cc:linux_x86_64_musl"
    for expected, constraints in [
        (aarch64, ["@platforms//cpu:aarch64", "@platforms//os:linux"]),
        (x86_64, ["@platforms//cpu:x86_64", "@platforms//os:linux"]),
        # An Apple silicon host that executes remotely on Linux x86-64 keeps the x86-64 default.
        (x86_64, ["@platforms//cpu:aarch64", "@platforms//os:osx"]),
    ]:
        asserts.equals(env, expected, select_host_bootstrap_platform(constraints), str(constraints))
    return unittest.end(env)

host_bootstrap_platform_test = unittest.make(_host_bootstrap_platform_test_impl)
