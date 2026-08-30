"""Repository rule for the static, pinned Zig C compiler."""

load("//mkosi/debian:provenance.bzl", "DEBIAN_TOOLS_ZIG_SHA256", "DEBIAN_TOOLS_ZIG_URL")

def _impl(ctx):
    ctx.download_and_extract(
        url = DEBIAN_TOOLS_ZIG_URL,
        sha256 = DEBIAN_TOOLS_ZIG_SHA256,
        stripPrefix = "zig-x86_64-linux-0.16.0",
    )
    ctx.file(
        "BUILD.bazel",
        """package(default_visibility = ["//visibility:public"])
exports_files(["zig"])
""",
    )
    if hasattr(ctx, "repo_metadata"):
        return ctx.repo_metadata(reproducible = True)
    return None

debian_zig_repo = repository_rule(
    implementation = _impl,
)
