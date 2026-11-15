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

    # An interpreter that runs outside a sandbox, such as the Debian tools launcher started by `bazel run`, can write
    # bytecode into this directory. The next analysis would add it to the runtime, so that the keys of the actions that
    # read the runtime, and image versions derived from their inputs, would depend on what ran in the output base.
    ctx.file(
        "BUILD.bazel",
        """package(default_visibility = ["//visibility:public"])

_BYTECODE = ["**/__pycache__/**", "**/*.pyc"]

exports_files(["python"] + glob(["bin/**", "lib/**"], exclude = _BYTECODE))

filegroup(
    name = "runtime",
    srcs = glob(["lib/**"], exclude = _BYTECODE),
)
""",
    )
    if hasattr(ctx, "repo_metadata"):
        return ctx.repo_metadata(reproducible = True)
    return None

debian_python_repo = repository_rule(
    implementation = _impl,
)
