"""Cross-builds bootstrap executables for Linux aarch64 on the current execution platform."""

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
