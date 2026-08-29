"""Repository rule that exposes registered mkosi toolchains."""

def _toolchains_repo_impl(repository_ctx):
    repository_ctx.file(
        "BUILD.bazel",
        """load("@rules_mkosi//mkosi:toolchain.bzl", "mkosi_toolchain")

package(default_visibility = ["//visibility:public"])

mkosi_toolchain(
    name = "mkosi_toolchain",
    toolchain_name = {toolchain_name},
)

toolchain(
    name = "linux_x86_64",
    exec_compatible_with = [
        "@platforms//os:linux",
        "@platforms//cpu:x86_64",
    ],
    toolchain = ":mkosi_toolchain",
    toolchain_type = "@rules_mkosi//mkosi/toolchain:toolchain_type",
)
""".format(toolchain_name = repr(repository_ctx.attr.toolchain_name)),
    )

    if hasattr(repository_ctx, "repo_metadata"):
        return repository_ctx.repo_metadata(reproducible = True)
    return None

toolchains_repo = repository_rule(
    implementation = _toolchains_repo_impl,
    attrs = {
        "toolchain_name": attr.string(mandatory = True),
    },
)
