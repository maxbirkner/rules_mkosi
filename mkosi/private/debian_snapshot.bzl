"""Public rule for a content-addressed Debian APT snapshot tree."""

DebianSnapshotInfo = provider(
    doc = "Authenticated, content-addressed Debian snapshot repository.",
    fields = {
        "format_version": "Repository layout contract version.",
        "distribution": "Distribution name.",
        "release": "Numeric Debian release.",
        "codename": "Debian codename.",
        "architecture": "Package architecture.",
        "snapshot": "Immutable snapshot identifier.",
        "snapshot_url": "Immutable snapshot URL.",
        "lock_sha256": "Digest of the package and repository lock.",
        "repository": "TreeArtifact containing the local APT repository.",
        "inrelease": "Authenticated InRelease metadata.",
        "release_metadata": "Authenticated Release metadata.",
        "packages_metadata": "Authenticated Packages metadata.",
        "package_files": "Locked package files staged in the repository.",
    },
)

def _impl(ctx):
    if len(ctx.files.package_files) != len(ctx.attr.package_names):
        fail("package_files and package_names must have the same length")
    debian_tools = ctx.toolchains["//mkosi/toolchain:debian_tools_toolchain_type"].debian_tools
    output = ctx.actions.declare_directory(ctx.label.name + "_repository")
    scratch = ctx.actions.declare_directory(ctx.label.name + "_scratch")
    arguments = ctx.actions.args()
    arguments.add("--inrelease", ctx.file.inrelease.path)
    arguments.add("--release", ctx.file.release_metadata.path)
    arguments.add("--release-gpg", ctx.file.release_gpg.path)
    arguments.add("--packages-xz", ctx.file.packages_xz.path)
    arguments.add("--packages-all-xz", ctx.file.packages_all_xz.path)
    arguments.add("--output", output.path)
    arguments.add("--scratch", scratch.path)
    arguments.add("--launcher", debian_tools.launcher.executable.path)
    for name, option in [
        ("inrelease", "inrelease"),
        ("release", "release"),
        ("release_gpg", "release-gpg"),
        ("packages_xz", "packages-xz"),
        ("packages_all_xz", "packages-all-xz"),
    ]:
        arguments.add("--%s-sha256" % option, ctx.attr.metadata_digests[name])
    arguments.add("--packages-path", ctx.attr.packages_path)
    arguments.add("--packages-all-path", ctx.attr.packages_all_path)
    for package in ctx.attr.package_records:
        arguments.add("--package", package)
    for package, name in zip(ctx.files.package_files, ctx.attr.package_names):
        arguments.add("--package-file", package.path)
        arguments.add("--package-name", name)
    runtime = debian_tools.python_files_to_run
    ctx.actions.run(
        executable = debian_tools.python,
        arguments = ["-I", ctx.file._stager.path, arguments],
        inputs = depset(
            [
                ctx.file.inrelease,
                ctx.file.release_metadata,
                ctx.file.release_gpg,
                ctx.file.packages_xz,
                ctx.file.packages_all_xz,
                ctx.file._stager,
            ] + ctx.files.package_files,
        ),
        tools = [runtime, debian_tools.launcher],
        outputs = [output, scratch],
        env = {
            "PATH": "",
            "PYTHONNOUSERSITE": "1",
        },
        mnemonic = "StageDebianSnapshot",
        progress_message = "Staging authenticated Debian snapshot %{label}",
    )
    repository = DebianSnapshotInfo(
        format_version = ctx.attr.format_version,
        distribution = ctx.attr.distribution,
        release = ctx.attr.release,
        codename = ctx.attr.codename,
        architecture = ctx.attr.architecture,
        snapshot = ctx.attr.snapshot,
        snapshot_url = ctx.attr.snapshot_url,
        lock_sha256 = ctx.attr.lock_sha256,
        repository = output,
        inrelease = ctx.file.inrelease,
        release_metadata = ctx.file.release_metadata,
        packages_metadata = depset([ctx.file.packages_xz, ctx.file.packages_all_xz]),
        package_files = depset(ctx.files.package_files),
    )
    return [repository, DefaultInfo(files = depset([output]))]

debian_snapshot = rule(
    implementation = _impl,
    attrs = {
        "format_version": attr.string(default = "debian-snapshot-v1"),
        "distribution": attr.string(default = "debian"),
        "release": attr.string(default = "13"),
        "codename": attr.string(default = "trixie"),
        "architecture": attr.string(default = "amd64"),
        "snapshot": attr.string(mandatory = True),
        "snapshot_url": attr.string(mandatory = True),
        "lock_sha256": attr.string(mandatory = True),
        "inrelease": attr.label(mandatory = True, allow_single_file = True),
        "release_metadata": attr.label(mandatory = True, allow_single_file = True),
        "release_gpg": attr.label(mandatory = True, allow_single_file = True),
        "packages_xz": attr.label(mandatory = True, allow_single_file = True),
        "packages_all_xz": attr.label(mandatory = True, allow_single_file = True),
        "package_files": attr.label_list(mandatory = True, allow_files = True),
        "package_names": attr.string_list(mandatory = True),
        "package_records": attr.string_list(mandatory = True),
        "packages_path": attr.string(default = "dists/trixie/main/binary-amd64/Packages.xz"),
        "packages_all_path": attr.string(default = "dists/trixie/main/binary-all/Packages.xz"),
        "metadata_digests": attr.string_dict(mandatory = True),
        "_stager": attr.label(
            allow_single_file = True,
            default = "//mkosi/private:debian_snapshot.py",
        ),
    },
    toolchains = ["//mkosi/toolchain:debian_tools_toolchain_type"],
    exec_compatible_with = [
        "@platforms//os:linux",
        "@platforms//cpu:x86_64",
    ],
    doc = "Materializes an authenticated local APT repository from a pinned Debian snapshot.",
)
