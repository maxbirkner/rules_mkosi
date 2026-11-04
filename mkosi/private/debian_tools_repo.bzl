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

alias(name = "python", actual = "@mkosi_debian_python//:python")
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
    data = [
        ":launcher_cli",
        ":python",
        ":python_runtime",
    ],
    deps = ["@rules_cc//cc/runfiles"],
    features = ["fully_static_link"],
    linkopts = ["-static", "-Wl,--strip-debug", "-Wl,--build-id=none"],
    exec_compatible_with = [
        "@platforms//os:linux",
        "@platforms//cpu:x86_64",
    ],
    target_compatible_with = [
        "@platforms//os:linux",
        "@platforms//cpu:x86_64",
    ],
)

bootstrap_binary(
    name = "launcher",
    binary = ":launcher_binary",
    exec_compatible_with = [
        "@platforms//os:linux",
        "@platforms//cpu:x86_64",
    ],
    target_compatible_with = [
        "@platforms//os:linux",
        "@platforms//cpu:x86_64",
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
    exec_compatible_with = [
        "@platforms//os:linux",
        "@platforms//cpu:x86_64",
    ],
    target_compatible_with = [
        "@platforms//os:linux",
        "@platforms//cpu:x86_64",
    ],
)

bootstrap_binary(
    name = "namespace_runner",
    binary = ":namespace_runner_binary",
    exec_compatible_with = [
        "@platforms//os:linux",
        "@platforms//cpu:x86_64",
    ],
    target_compatible_with = [
        "@platforms//os:linux",
        "@platforms//cpu:x86_64",
    ],
)

filegroup(
    name = "python_runtime",
    srcs = ["@mkosi_debian_python//:runtime"],
)

debian_tools_toolchain(
    name = "toolchain",
    release = "13",
    codename = "trixie",
    architecture = "amd64",
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
)

toolchain(
    name = "linux_x86_64",
    exec_compatible_with = [
        "@platforms//os:linux",
        "@platforms//cpu:x86_64",
    ],
    toolchain = ":toolchain",
    toolchain_type = "@rules_mkosi//mkosi/toolchain:debian_tools_toolchain_type",
)
"""

def _impl(ctx):
    ctx.file(
        "launcher_config.json",
        json.encode({
            "archive_sha256": ctx.attr.archive_sha256,
            "format_version": "debian-launcher-v1",
        }) + "\n",
    )
    ctx.file(
        "BUILD.bazel",
        _BUILD_TEMPLATE.format(
            repo = ctx.attr.package_repo,
            provenance = ctx.attr.provenance,
            components_label = ctx.attr.components,
            required_components = repr(ctx.attr.required_components),
            lock_sha256 = ctx.attr.lock_sha256,
            archive_sha256 = ctx.attr.archive_sha256,
            python_version = ctx.attr.python_version,
            snapshot = DEBIAN_TOOLS_SNAPSHOT,
            snapshot_url = DEBIAN_TOOLS_SNAPSHOT_URL,
        ),
    )
    if hasattr(ctx, "repo_metadata"):
        return ctx.repo_metadata(reproducible = True)
    return None

debian_tools_repo = repository_rule(
    implementation = _impl,
    attrs = {
        "archive_sha256": attr.string(mandatory = True),
        "components": attr.label(mandatory = True),
        "lock_sha256": attr.string(mandatory = True),
        "package_repo": attr.string(mandatory = True),
        "provenance": attr.label(mandatory = True),
        "python_version": attr.string(mandatory = True),
        "required_components": attr.string_list(mandatory = True),
    },
)
