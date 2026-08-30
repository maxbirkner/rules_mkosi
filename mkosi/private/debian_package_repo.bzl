"""Repository rule for checksum-pinned Debian package inputs."""

def _impl(ctx):
    lock = json.decode(ctx.read(ctx.attr.lock))
    packages = sorted(lock["packages"], key = lambda package: package["key"])
    files = []
    for index, package in enumerate(packages):
        index_string = str(index)
        if index < 10:
            index_string = "00" + index_string
        elif index < 100:
            index_string = "0" + index_string
        output = "pkg_" + index_string + ".deb"
        ctx.download(
            url = package["urls"][0],
            output = output,
            sha256 = package["sha256"],
        )
        files.append(output)
    ctx.file(
        "BUILD.bazel",
        """package(default_visibility = ["//visibility:public"])

exports_files({files})

filegroup(
    name = "all",
    srcs = {files},
)
""".format(files = repr(files)),
    )
    if hasattr(ctx, "repo_metadata"):
        return ctx.repo_metadata(reproducible = True)
    return None

debian_package_repo = repository_rule(
    implementation = _impl,
    attrs = {
        "lock": attr.label(mandatory = True, allow_single_file = True),
    },
)
