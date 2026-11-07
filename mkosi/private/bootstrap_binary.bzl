"""Builds statically linked bootstrap executables for a selectable target platform."""

_PLATFORMS = "//command_line_option:platforms"
_BOOTSTRAP_PLATFORM = str(Label("//mkosi/toolchain:bootstrap_platform"))
_INHERIT_PLATFORM = Label("//mkosi/toolchain:inherit_platform")

# Enables rules_mkosi's static C/C++ toolchains, which match only bootstrap executables.
_BOOTSTRAP_EXECUTABLE = str(Label("//mkosi/toolchain/bootstrap_cc:bootstrap_executable"))

# Bootstrap launchers execute the static interpreter on a py_binary's stub, which therefore must be Python rather
# than the shell stage-one bootstrap that consumers selecting rules_python's `script` bootstrap would generate.
_PYTHON_BOOTSTRAP = str(Label("@rules_python//python/config_settings:bootstrap_impl"))

def _bootstrap_transition_impl(settings, _attr):
    platform = settings[_BOOTSTRAP_PLATFORM]
    return {
        _PLATFORMS: settings[_PLATFORMS] if platform == _INHERIT_PLATFORM else [str(platform)],
        _PYTHON_BOOTSTRAP: "system_python",
        _BOOTSTRAP_EXECUTABLE: True,
    }

_bootstrap_transition = transition(
    implementation = _bootstrap_transition_impl,
    inputs = [_PLATFORMS, _BOOTSTRAP_PLATFORM],
    outputs = [_PLATFORMS, _PYTHON_BOOTSTRAP, _BOOTSTRAP_EXECUTABLE],
)

def _bootstrap_binary_impl(ctx):
    binary = ctx.attr.binary[0][DefaultInfo]
    executable = ctx.actions.declare_file(ctx.label.name)
    ctx.actions.symlink(
        output = executable,
        target_file = binary.files_to_run.executable,
        is_executable = True,
    )
    return [DefaultInfo(
        executable = executable,
        files = depset([executable]),
        runfiles = ctx.runfiles(files = [executable]).merge(binary.default_runfiles),
    )]

bootstrap_binary = rule(
    implementation = _bootstrap_binary_impl,
    executable = True,
    attrs = {
        "binary": attr.label(
            cfg = _bootstrap_transition,
            executable = True,
            mandatory = True,
            doc = "Statically linked binary built for --@rules_mkosi//mkosi/toolchain:bootstrap_platform.",
        ),
        "_allowlist_function_transition": attr.label(
            default = "@bazel_tools//tools/allowlists/function_transition_allowlist",
        ),
    },
    doc = """Exposes a static bootstrap executable built for the configured bootstrap platform.

The executable is a symlink named after this target. Its runfiles are those of `binary`, so runfiles libraries
initialized from either the directory or the manifest of this executable find the same files.

By default the current target platform is kept and `binary` uses whichever registered C/C++ toolchain matches it
first. The transition also sets `//mkosi/toolchain/bootstrap_cc:bootstrap_executable`, the only configuration in which
the static zig musl toolchains of `//mkosi/toolchain/bootstrap_cc` match. A consumer whose preferred toolchain is
registered first and cannot link fully static executables selects a platform that a static-capable toolchain
matches, for example a musl platform:

    common --@rules_mkosi//mkosi/toolchain:bootstrap_platform=//platforms:linux_x86_64_musl

The transition also selects rules_python's `system_python` bootstrap, even when a consumer selects `script`, because
the static launcher executes the interpreter directly on its py_binary stub.
""",
)
