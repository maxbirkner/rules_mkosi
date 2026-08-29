"""Repository exposing the Debian package tree and toolchain."""

def _impl(ctx):
    ctx.file(
        "BUILD.bazel",
        """load("@rules_mkosi//mkosi/debian:toolchain.bzl", "debian_tools_toolchain", "debian_tools_tree")

package(default_visibility = ["//visibility:public"])

alias(name = "tree", actual = "{repo}//:flat")
alias(name = "provenance", actual = "{provenance}")
alias(name = "components", actual = "{components_label}")

debian_tools_tree(
    name = "tree_root",
    archive = ":tree",
    extractor = "@rules_mkosi//mkosi/debian:extract_tree.py",
)

alias(name = "python", actual = "@python_3_11//:python3")
filegroup(
    name = "launcher_script",
    srcs = ["@rules_mkosi//mkosi/debian:debian_launcher.py"],
)
filegroup(
    name = "extractor",
    srcs = ["@rules_mkosi//mkosi/debian:extract_tree.py"],
)

debian_tools_toolchain(
    name = "toolchain",
    release = "13",
    codename = "trixie",
    architecture = "amd64",
    snapshot = "20250814T000000Z",
    snapshot_url = "https://snapshot.debian.org/archive/debian/20250814T000000Z",
    lock_sha256 = "{lock_sha256}",
    archive_sha256 = "{archive_sha256}",
    tree = ":tree",
    tree_root = ":tree_root",
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
""".format(
            repo = ctx.attr.package_repo,
            provenance = ctx.attr.provenance,
            components_label = ctx.attr.components,
            required_components = repr(ctx.attr.required_components),
            lock_sha256 = ctx.attr.lock_sha256,
            archive_sha256 = ctx.attr.archive_sha256,
        ),
    )
    if hasattr(ctx, "repo_metadata"):
        return ctx.repo_metadata(reproducible = True)
    return None

debian_tools_repo = repository_rule(
    implementation = _impl,
    attrs = {
        "package_repo": attr.string(mandatory = True),
        "provenance": attr.label(mandatory = True),
        "components": attr.label(mandatory = True),
        "required_components": attr.string_list(mandatory = True),
        "lock_sha256": attr.string(mandatory = True),
        "archive_sha256": attr.string(mandatory = True),
    },
)
