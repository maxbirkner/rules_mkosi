"""Repository exposing the Debian package tree and toolchain."""

load("//mkosi/debian:provenance.bzl", "DEBIAN_TOOLS_SNAPSHOT", "DEBIAN_TOOLS_SNAPSHOT_URL")

_BUILD_TEMPLATE = """load("@rules_cc//cc:defs.bzl", "cc_binary")
load("@rules_python//python:defs.bzl", "py_binary")
load("@rules_mkosi//mkosi/debian:toolchain.bzl", "debian_tools_archive", "debian_tools_toolchain", "debian_tools_tree")
load("@rules_mkosi//mkosi:versions.bzl", "DEFAULT_PYTHON_VERSION")
load("@rules_mkosi//mkosi/private:bootstrap_binary.bzl", "bootstrap_binary")
load("@rules_mkosi//mkosi/private:c_options.bzl", "CXX_WARNINGS", "C_WARNINGS")

package(default_visibility = ["//visibility:public"])

alias(name = "provenance", actual = "{provenance}")
alias(name = "components", actual = "{components_label}")

debian_tools_archive(
    name = "tree",
    packages = ["{repo}//:all"],
    package_manifest = "{repo}//:package_manifest.txt",
)

debian_tools_tree(
    name = "tree_root",
    archive = ":tree",
    extractor = "@rules_mkosi//mkosi/debian:extract_tree.py",
    archive_sha256 = "{archive_sha256}",
)

alias(name = "python", actual = "{python_repo}//:python")
filegroup(
    name = "launcher_script",
    srcs = ["@rules_mkosi//mkosi/debian:debian_launcher.py"],
)
filegroup(
    name = "extractor",
    srcs = ["@rules_mkosi//mkosi/debian:extract_tree.py"],
)

py_binary(
    name = "launcher_cli",
    srcs = ["@rules_mkosi//mkosi/debian:debian_launcher.py"],
    data = [
        ":launcher_config.json",
        ":namespace_runner",
        ":tree",
        "@rules_mkosi//mkosi/debian:extract_tree.py",
    ],
    main = "@rules_mkosi//mkosi/debian:debian_launcher.py",
    # The locked mkosi_pypi hub is resolved for rules_mkosi's Python line, independent of the consumer's default.
    python_version = DEFAULT_PYTHON_VERSION,
    deps = [
        "@mkosi_pypi//click",
        "@rules_python//python/runfiles",
    ],
    visibility = ["//visibility:private"],
)

cc_binary(
    name = "launcher_binary",
    srcs = [
        "@rules_mkosi//mkosi/debian:launcher_main.cc",
    ],
    copts = CXX_WARNINGS,
    deps = ["@rules_cc//cc/runfiles"],
    features = ["fully_static_link"],
    linkopts = ["-static", "-Wl,--strip-debug", "-Wl,--build-id=none"],
    # Any Linux execution platform links or symlinks them; a Linux x86-64 one also cross-builds the arm64 ones.
    exec_compatible_with = ["@platforms//os:linux"],
    target_compatible_with = [
        "@platforms//os:linux",
        "{cpu_constraint}",
    ],
)

bootstrap_binary(
    name = "launcher",
    binary = ":launcher_binary",
    data = [
        ":launcher_cli",
        ":python",
        ":python_runtime",
    ],
    # Any Linux execution platform links or symlinks them; a Linux x86-64 one also cross-builds the arm64 ones.
    exec_compatible_with = ["@platforms//os:linux"],
    target_compatible_with = [
        "@platforms//os:linux",
        "{cpu_constraint}",
    ],
)

cc_binary(
    name = "namespace_runner_binary",
    srcs = ["@rules_mkosi//mkosi/debian:namespace_runner.c"],
    copts = C_WARNINGS,
    deps = [
        "@rules_mkosi//mkosi/private:mount_api",
        "@rules_mkosi//mkosi/private:write_all",
    ],
    features = ["fully_static_link"],
    linkopts = ["-static", "-Wl,--strip-debug", "-Wl,--build-id=none"],
    # Any Linux execution platform links or symlinks them; a Linux x86-64 one also cross-builds the arm64 ones.
    exec_compatible_with = ["@platforms//os:linux"],
    target_compatible_with = [
        "@platforms//os:linux",
        "{cpu_constraint}",
    ],
)

bootstrap_binary(
    name = "namespace_runner",
    binary = ":namespace_runner_binary",
    # Any Linux execution platform links or symlinks them; a Linux x86-64 one also cross-builds the arm64 ones.
    exec_compatible_with = ["@platforms//os:linux"],
    target_compatible_with = [
        "@platforms//os:linux",
        "{cpu_constraint}",
    ],
)

filegroup(
    name = "python_runtime",
    srcs = ["{python_repo}//:runtime"],
)

{emulator_aliases}
debian_tools_toolchain(
    name = "toolchain",
    release = "13",
    codename = "trixie",
    architecture = "{architecture}",
    snapshot = "{snapshot}",
    snapshot_url = "{snapshot_url}",
    lock_sha256 = "{lock_sha256}",
    archive_sha256 = "{archive_sha256}",
    python_version = "{python_version}",
    tree = ":tree",
    tree_root = ":tree_root",
    launcher = ":launcher",
    python = ":python",
    launcher_script = ":launcher_script",
    extractor = ":extractor",
    provenance = ":provenance",
    components = ":components",
    required_components = {required_components},
    user_mode_emulators = {user_mode_emulators},
)

toolchain(
    name = "{toolchain_name}",
    exec_compatible_with = [
        "@platforms//os:linux",
        "{cpu_constraint}",
    ],
    toolchain = ":toolchain",
    toolchain_type = "@rules_mkosi//mkosi/toolchain:debian_tools_toolchain_type",
)
"""

# The Debian tools of each execution platform CPU: the amd64 tools in the root package, whose Linux x86-64 toolchain
# also cross-builds arm64 images with rules_qemu's static qemu-aarch64, and the arm64 tools in the `arm64` package.
_EMULATOR_ALIASES = """# rules_qemu's static qemu-aarch64 for Linux x86-64 hosts, which runs the arm64 programs of cross-built images.
alias(
    name = "arm64_user_mode_emulator",
    actual = "@qemu_user_prebuilt_linux_amd64_aarch64//:qemu-aarch64",
)
"""

_PACKAGES = {
    "": struct(
        architecture = "amd64",
        cpu_constraint = "@platforms//cpu:x86_64",
        emulator_aliases = _EMULATOR_ALIASES,
        python_repo = "@mkosi_debian_python",
        toolchain_name = "linux_x86_64",
        user_mode_emulators = {"arm64": ":arm64_user_mode_emulator"},
    ),
    "arm64": struct(
        architecture = "arm64",
        cpu_constraint = "@platforms//cpu:aarch64",
        emulator_aliases = "",
        python_repo = "@mkosi_debian_python_aarch64",
        toolchain_name = "linux_aarch64",
        user_mode_emulators = {},
    ),
}

def _write_tools_package(ctx, package, settings, architecture_attrs):
    prefix = package + "/" if package else ""
    ctx.file(
        prefix + "launcher_config.json",
        json.encode({
            "archive_sha256": architecture_attrs["archive_sha256"],
            "format_version": "debian-launcher-v1",
        }) + "\n",
    )
    ctx.file(
        prefix + "BUILD.bazel",
        _BUILD_TEMPLATE.format(
            repo = architecture_attrs["package_repo"],
            provenance = ctx.attr.provenance,
            components_label = architecture_attrs["components"],
            required_components = repr(architecture_attrs["required_components"]),
            lock_sha256 = architecture_attrs["lock_sha256"],
            archive_sha256 = architecture_attrs["archive_sha256"],
            python_version = ctx.attr.python_version,
            snapshot = DEBIAN_TOOLS_SNAPSHOT,
            snapshot_url = DEBIAN_TOOLS_SNAPSHOT_URL,
            architecture = settings.architecture,
            cpu_constraint = settings.cpu_constraint,
            emulator_aliases = settings.emulator_aliases,
            python_repo = settings.python_repo,
            toolchain_name = settings.toolchain_name,
            user_mode_emulators = repr(settings.user_mode_emulators),
        ),
    )

def _impl(ctx):
    for package, settings in _PACKAGES.items():
        architecture_attrs = json.decode(ctx.attr.architectures[settings.architecture])
        _write_tools_package(ctx, package, settings, architecture_attrs)
    if hasattr(ctx, "repo_metadata"):
        return ctx.repo_metadata(reproducible = True)
    return None

debian_tools_repo = repository_rule(
    implementation = _impl,
    attrs = {
        "architectures": attr.string_dict(
            mandatory = True,
            doc = """JSON object of each Debian architecture of the tools, `amd64` and `arm64`, with its `package_repo`,
`components` label, `required_components`, `lock_sha256` and `archive_sha256`.""",
        ),
        "provenance": attr.label(mandatory = True),
        "python_version": attr.string(mandatory = True),
    },
)
