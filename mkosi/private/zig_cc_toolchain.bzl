"""Declares toolchain() targets for hermetic_cc_toolchain's zig musl C/C++ toolchain.

Toolchain resolution loads every registered toolchain() target for any toolchain type. hermetic_cc_toolchain's own
toolchain() targets take their execution constraints from @zig_config, the repository that downloads the zig SDK, so
registering them fetches the SDK for every build. These targets use only @platforms and @zig_sdk//libc constraints,
which download nothing, and reference the zig cc_toolchain by label, so Bazel fetches the SDK only when it selects one.
"""

_LINUX_X86_64 = [
    Label("@platforms//os:linux"),
    Label("@platforms//cpu:x86_64"),
]

def zig_musl_cc_toolchain(name, libc, target_settings = []):
    """Declares a toolchain() for the zig musl cc_toolchain that runs on and targets Linux x86-64.

    Args:
        name: Name of the toolchain() target.
        libc: The `@zig_sdk//libc` constraint value that target platforms must have, such as `unconstrained` for
            platforms without an explicit libc, like hermetic_cc_toolchain's `toolchain` package, or `musl`, like its
            `libc_aware/toolchain` package.
        target_settings: Labels of config_settings that must match the target configuration.
    """
    native.toolchain(
        name = name,
        exec_compatible_with = _LINUX_X86_64,
        target_compatible_with = _LINUX_X86_64 + [Label("@zig_sdk//libc:" + libc)],
        target_settings = target_settings,
        toolchain = Label("@zig_config//:x86_64-linux-musl_cc"),
        toolchain_type = Label("@bazel_tools//tools/cpp:toolchain_type"),
    )
