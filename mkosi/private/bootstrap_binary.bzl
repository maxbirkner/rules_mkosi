"""Builds statically linked bootstrap executables for a selectable target platform."""

_PLATFORMS = "//command_line_option:platforms"
_BOOTSTRAP_PLATFORM = str(Label("//mkosi/toolchain:bootstrap_platform"))
_INHERIT_PLATFORM = Label("//mkosi/toolchain:inherit_platform")

# Enables rules_mkosi's static C/C++ toolchains, which match only bootstrap executables.
_BOOTSTRAP_EXECUTABLE = str(Label("//mkosi/toolchain/bootstrap_cc:bootstrap_executable"))

# Bootstrap executables resolve these toolchains before every registered one, whatever the consumer registers and in
# which order its dependencies are resolved.
_EXTRA_TOOLCHAINS = "//command_line_option:extra_toolchains"
_BOOTSTRAP_CC_TOOLCHAINS = str(Label("//mkosi/toolchain/bootstrap_cc:all"))

# Bootstrap launchers execute the static interpreter on a py_binary's stub, which therefore must be Python rather
# than the shell stage-one bootstrap that consumers selecting rules_python's `script` bootstrap would generate.
_PYTHON_BOOTSTRAP = str(Label("@rules_python//python/config_settings:bootstrap_impl"))

def _select_bootstrap_settings(settings, bootstrap_executable):
    platform = settings[_BOOTSTRAP_PLATFORM]
    return {
        _PLATFORMS: settings[_PLATFORMS] if platform == _INHERIT_PLATFORM else [str(platform)],
        _PYTHON_BOOTSTRAP: "system_python",
        _BOOTSTRAP_EXECUTABLE: bootstrap_executable,
    }

def _select_executable_settings(settings, _attr):
    extra_toolchains = settings[_EXTRA_TOOLCHAINS]
    if _BOOTSTRAP_CC_TOOLCHAINS not in extra_toolchains:
        extra_toolchains = [_BOOTSTRAP_CC_TOOLCHAINS] + extra_toolchains
    return _select_bootstrap_settings(settings, True) | {_EXTRA_TOOLCHAINS: extra_toolchains}

def _select_data_settings(settings, _attr):
    return _select_bootstrap_settings(settings, False)

_TRANSITION_INPUTS = [_PLATFORMS, _BOOTSTRAP_PLATFORM]
_TRANSITION_OUTPUTS = [_PLATFORMS, _PYTHON_BOOTSTRAP, _BOOTSTRAP_EXECUTABLE]

_bootstrap_transition = transition(
    implementation = _select_executable_settings,
    inputs = _TRANSITION_INPUTS + [_EXTRA_TOOLCHAINS],
    outputs = _TRANSITION_OUTPUTS + [_EXTRA_TOOLCHAINS],
)

# Leaves the static C/C++ toolchains disabled, so that with the default bootstrap platform the data shares its
# configuration and outputs with the same targets outside the bootstrap executable.
_bootstrap_data_transition = transition(
    implementation = _select_data_settings,
    inputs = _TRANSITION_INPUTS,
    outputs = _TRANSITION_OUTPUTS,
)

def _bootstrap_binary_impl(ctx):
    binary = ctx.attr.binary[0][DefaultInfo]
    executable = ctx.actions.declare_file(ctx.label.name)
    ctx.actions.symlink(
        output = executable,
        target_file = binary.files_to_run.executable,
        is_executable = True,
    )
    runfiles = ctx.runfiles(files = [executable] + ctx.files.data).merge_all(
        [binary.default_runfiles] + [target[DefaultInfo].default_runfiles for target in ctx.attr.data],
    )
    return [DefaultInfo(
        executable = executable,
        files = depset([executable]),
        runfiles = runfiles,
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
        "data": attr.label_list(
            allow_files = True,
            cfg = _bootstrap_data_transition,
            doc = """Runfiles of the executable, built for the same platform and Python bootstrap as `binary`, but
outside the configuration of the static C/C++ toolchains.""",
        ),
        "_allowlist_function_transition": attr.label(
            default = "@bazel_tools//tools/allowlists/function_transition_allowlist",
        ),
    },
    doc = """Exposes a static bootstrap executable built for the configured bootstrap platform.

The executable is a symlink named after this target. Its runfiles are those of `binary` and `data`, so runfiles
libraries initialized from either the directory or the manifest of this executable find the same files.

By default the current target platform is kept. The transition of `binary` sets
`//mkosi/toolchain/bootstrap_cc:bootstrap_executable`, the only configuration in which the static zig musl toolchains
of `//mkosi/toolchain/bootstrap_cc` match, and puts them first in `--extra_toolchains`, so they outrank every
registered C/C++ toolchain whatever the consumer registers. They match Linux x86-64 platforms without a
`@zig_sdk//libc` constraint or with `@zig_sdk//libc:musl`; for any other platform, the first registered toolchain that
matches it builds `binary`:

    common --@rules_mkosi//mkosi/toolchain:bootstrap_platform=//platforms:my_static_platform

`data` is built without these settings, so that, with the default bootstrap platform, targets such as the Debian tools
archive are built once for both the bootstrap executable and their other dependents.

The transition also selects rules_python's `system_python` bootstrap, even when a consumer selects `script`, because
the static launcher executes the interpreter directly on its py_binary stub.
""",
)
