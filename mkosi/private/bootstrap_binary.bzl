"""Builds statically linked bootstrap executables for a selectable target platform."""

_PLATFORMS = "//command_line_option:platforms"
_BOOTSTRAP_PLATFORM = str(Label("//mkosi/toolchain:bootstrap_platform"))
_INHERIT_PLATFORM = Label("//mkosi/toolchain:inherit_platform")

# Linux x86-64 musl platform for which the llvm module's C/C++ toolchain links fully static executables. With the default
# bootstrap platform, the executable is built for it, while its data keeps the current platform.
_STATIC_PLATFORM = str(Label("//mkosi/toolchain/bootstrap_cc:linux_x86_64_musl"))

# The first execution platform below the executable, by default the static platform, so that the toolchain's own helper
# tools link statically against musl too, instead of against the glibc runtime of the llvm module or with a host C/C++
# compiler. Consumers with remote execution select a musl child of their own execution platform.
_BOOTSTRAP_EXECUTION_PLATFORM = str(Label("//mkosi/toolchain:bootstrap_execution_platform"))
_EXTRA_EXECUTION_PLATFORMS = "//command_line_option:extra_execution_platforms"

# Enables rules_mkosi's static C/C++ toolchain, which matches only bootstrap executables.
_BOOTSTRAP_EXECUTABLE = str(Label("//mkosi/toolchain/bootstrap_cc:bootstrap_executable"))

# Bootstrap executables resolve this toolchain before every registered one, whatever the consumer registers and in
# which order its dependencies are resolved.
_EXTRA_TOOLCHAINS = "//command_line_option:extra_toolchains"
_BOOTSTRAP_CC_TOOLCHAINS = str(Label("//mkosi/toolchain/bootstrap_cc:all"))

# Bootstrap launchers execute the static interpreter on a py_binary's stub, which therefore must be Python rather
# than the shell stage-one bootstrap that consumers selecting rules_python's `script` bootstrap would generate.
_PYTHON_BOOTSTRAP = str(Label("@rules_python//python/config_settings:bootstrap_impl"))

def _select_bootstrap_settings(settings, bootstrap_executable, default_platforms):
    platform = settings[_BOOTSTRAP_PLATFORM]
    return {
        _PLATFORMS: default_platforms if platform == _INHERIT_PLATFORM else [str(platform)],
        _PYTHON_BOOTSTRAP: "system_python",
        _BOOTSTRAP_EXECUTABLE: bootstrap_executable,
    }

def _prepend_missing(values, value):
    return values if value in values else [value] + values

def _select_executable_settings(settings, _attr):
    execution_platform = str(settings[_BOOTSTRAP_EXECUTION_PLATFORM])
    return _select_bootstrap_settings(settings, True, [_STATIC_PLATFORM]) | {
        _EXTRA_EXECUTION_PLATFORMS: _prepend_missing(settings[_EXTRA_EXECUTION_PLATFORMS], execution_platform),
        _EXTRA_TOOLCHAINS: _prepend_missing(settings[_EXTRA_TOOLCHAINS], _BOOTSTRAP_CC_TOOLCHAINS),
    }

def _select_data_settings(settings, _attr):
    return _select_bootstrap_settings(settings, False, settings[_PLATFORMS])

_TRANSITION_INPUTS = [_PLATFORMS, _BOOTSTRAP_PLATFORM]
_TRANSITION_OUTPUTS = [_PLATFORMS, _PYTHON_BOOTSTRAP, _BOOTSTRAP_EXECUTABLE]

_bootstrap_transition = transition(
    implementation = _select_executable_settings,
    inputs = _TRANSITION_INPUTS + [_BOOTSTRAP_EXECUTION_PLATFORM, _EXTRA_EXECUTION_PLATFORMS, _EXTRA_TOOLCHAINS],
    outputs = _TRANSITION_OUTPUTS + [_EXTRA_EXECUTION_PLATFORMS, _EXTRA_TOOLCHAINS],
)

# Leaves the static C/C++ toolchain disabled and, with the default bootstrap platform, the current platform, so that the
# data shares its configuration and outputs with the same targets outside the bootstrap executable.
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
            doc = """Statically linked binary built for --@rules_mkosi//mkosi/toolchain:bootstrap_platform, by default
//mkosi/toolchain/bootstrap_cc:linux_x86_64_musl.""",
        ),
        "data": attr.label_list(
            allow_files = True,
            cfg = _bootstrap_data_transition,
            doc = """Runfiles of the executable, built with the same Python bootstrap as `binary`, outside the
configuration of the static C/C++ toolchain, and for the current platform unless a bootstrap platform is selected.""",
        ),
        "_allowlist_function_transition": attr.label(
            default = "@bazel_tools//tools/allowlists/function_transition_allowlist",
        ),
    },
    doc = """Exposes a static bootstrap executable built for the configured bootstrap platform.

The executable is a symlink named after this target. Its runfiles are those of `binary` and `data`, so runfiles
libraries initialized from either the directory or the manifest of this executable find the same files.

By default `binary` is built for `//mkosi/toolchain/bootstrap_cc:linux_x86_64_musl`, a Linux x86-64 platform with the
llvm module's musl and non-PIE constraints. Its transition sets
`//mkosi/toolchain/bootstrap_cc:bootstrap_executable`, the only configuration in which the static musl toolchain of
`//mkosi/toolchain/bootstrap_cc`, the llvm module's Linux x86-64 C/C++ toolchain, matches, and puts it first in
`--extra_toolchains`, so it outranks every registered C/C++ toolchain whatever the consumer registers. It matches
Linux x86-64 platforms with the `@llvm//constraints/libc:musl` constraint. The transition also puts
`--@rules_mkosi//mkosi/toolchain:bootstrap_execution_platform`, by default that same platform, first in
`--extra_execution_platforms`, so that the llvm toolchain's own helper tools, which are built for the execution
platform, link statically against musl too and no host C/C++ compiler is needed. For any other bootstrap platform
selected with the flag below, the first registered toolchain that matches it builds `binary`:

    common --@rules_mkosi//mkosi/toolchain:bootstrap_platform=//platforms:my_static_platform

`data` is built without the static toolchain and, with the default bootstrap platform, for the current platform, so
that targets such as the Debian tools archive are built once for both the bootstrap executable and their other
dependents.

The transition also selects rules_python's `system_python` bootstrap, even when a consumer selects `script`, because
the static launcher executes the interpreter directly on its py_binary stub.
""",
)
