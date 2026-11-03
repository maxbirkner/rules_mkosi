"""Repository rule for checksum-pinned Debian package inputs."""

load(":debian_snapshot_repo.bzl", "local_package_name", "locked_packages", "validate_lock")

_BUILD_TEMPLATE = """package(default_visibility = ["//visibility:public"])

exports_files({files} + ["package_manifest.txt"])

filegroup(
    name = "all",
    srcs = {files},
)
"""

def _impl(ctx):
    lock = json.decode(ctx.read(ctx.attr.lock))
    validate_lock(lock)
    files = []
    manifest = []
    for index, package in enumerate(locked_packages(lock)):
        output = local_package_name(index)
        ctx.download(
            url = package["urls"][0],
            output = output,
            sha256 = package["sha256"],
        )
        files.append(output)
        manifest.append("%s|%s|%s" % (output, package["sha256"], package["key"]))
    ctx.file("package_manifest.txt", "\n".join(manifest) + "\n")
    ctx.file("BUILD.bazel", _BUILD_TEMPLATE.format(files = repr(files)))
    if hasattr(ctx, "repo_metadata"):
        return ctx.repo_metadata(reproducible = True)
    return None

debian_package_repo = repository_rule(
    implementation = _impl,
    attrs = {
        "lock": attr.label(mandatory = True, allow_single_file = True, doc = "Debian snapshot lock."),
    },
)
