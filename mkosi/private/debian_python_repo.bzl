"""Repository rule for the static Python runtime used by Debian tooling."""

load(
    "//mkosi/debian:provenance.bzl",
    "DEBIAN_TOOLS_PYTHON_SHA256",
    "DEBIAN_TOOLS_PYTHON_URL",
    "DEBIAN_TOOLS_PYTHON_VERSION",
)

def _impl(ctx):
    ctx.download_and_extract(
        url = DEBIAN_TOOLS_PYTHON_URL,
        sha256 = DEBIAN_TOOLS_PYTHON_SHA256,
        stripPrefix = "python/install",
    )
    python_minor = ".".join(DEBIAN_TOOLS_PYTHON_VERSION.split(".")[:2])
    ctx.symlink(ctx.path("bin/python" + python_minor), "python")
    ctx.file(
        "BUILD.bazel",
        """package(default_visibility = ["//visibility:public"])

exports_files(["python"] + glob(["bin/**", "lib/**"]))

filegroup(
    name = "runtime",
    srcs = glob(["lib/**"]),
)
""",
    )
    if hasattr(ctx, "repo_metadata"):
        return ctx.repo_metadata(reproducible = True)
    return None

debian_python_repo = repository_rule(
    implementation = _impl,
)
