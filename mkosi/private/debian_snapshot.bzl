"""Public rule for a content-addressed Debian APT snapshot tree."""

load(":python_action.bzl", "run_python", "static_python_interpreter")

DebianSnapshotInfo = provider(
    doc = "Authenticated, content-addressed Debian snapshot repository.",
    fields = {
        "architecture": "Debian package architecture, such as `amd64`.",
        "codename": "Debian codename, such as `trixie`.",
        "components": "Archive components staged in the repository, starting with main.",
        "distribution": "mkosi distribution name, `debian`.",
        "format_version": "Repository layout contract version.",
        "inrelease": "Authenticated InRelease metadata.",
        "lock_sha256": "Digest of the package and repository lock.",
        "package_files": "Locked package files staged in the repository.",
        "packages_metadata": "Authenticated Packages metadata of every staged component.",
        "release": "Numeric Debian release, such as `13`.",
        "release_metadata": "Authenticated Release metadata.",
        "repository": "TreeArtifact containing the local APT repository.",
        "snapshot": "Immutable snapshot identifier.",
        "snapshot_url": "Immutable snapshot URL.",
    },
)

def _component_indexes(ctx):
    if len(ctx.attr.component_packages) != len(ctx.attr.component_package_records):
        fail("component_packages and component_package_records must have the same length")
    files = []
    for target in ctx.attr.component_packages:
        target_files = target.files.to_list()
        if len(target_files) != 1:
            fail("component_packages entry %s must provide exactly one file" % target.label)
        files.append(target_files[0])
    components = ["main"]
    architectures = {}
    for record in ctx.attr.component_package_records:
        fields = record.split("|")
        if len(fields) != 4:
            fail("component package record must be component|architecture|path|sha256: %s" % record)
        component, architecture, path, _ = fields
        if component == "main" or not component or "/" in component:
            fail("invalid additional Debian component: %s" % component)
        expected_path = "dists/%s/%s/binary-%s/Packages.xz" % (ctx.attr.codename, component, architecture)
        if path != expected_path:
            fail("Debian component index %s must use path %s" % (record, expected_path))
        if component not in architectures:
            components.append(component)
            architectures[component] = []
        if architecture in architectures[component]:
            fail("duplicate Debian component index: %s %s" % (component, architecture))
        architectures[component].append(architecture)
    for component, indexed in architectures.items():
        if sorted(indexed) != ["all", "amd64"]:
            fail("Debian component %s must provide binary-amd64 and binary-all indexes" % component)
    return components, files

_METADATA_OPTIONS = [
    ("inrelease", "inrelease"),
    ("release", "release"),
    ("release_gpg", "release-gpg"),
    ("packages_xz", "packages-xz"),
    ("packages_all_xz", "packages-all-xz"),
]

def _stager_arguments(ctx, launcher, output, scratch, component_indexes):
    arguments = ctx.actions.args()
    arguments.add("--inrelease", ctx.file.inrelease.path)
    arguments.add("--release", ctx.file.release_metadata.path)
    arguments.add("--release-gpg", ctx.file.release_gpg.path)
    arguments.add("--packages-xz", ctx.file.packages_xz.path)
    arguments.add("--packages-all-xz", ctx.file.packages_all_xz.path)
    arguments.add("--output", output.path)
    arguments.add("--scratch", scratch.path)
    arguments.add("--launcher", launcher.executable.path)
    arguments.add("--codename", ctx.attr.codename)
    for name, option in _METADATA_OPTIONS:
        arguments.add("--%s-sha256" % option, ctx.attr.metadata_digests[name])
    arguments.add("--packages-path", ctx.attr.packages_path)
    arguments.add("--packages-all-path", ctx.attr.packages_all_path)
    for index, record in zip(component_indexes, ctx.attr.component_package_records):
        arguments.add("--component-index", record)
        arguments.add("--component-index-file", index.path)
    for package in ctx.attr.package_records:
        arguments.add("--package", package)
    for package, name in zip(ctx.files.package_files, ctx.attr.package_names):
        arguments.add("--package-file", package.path)
        arguments.add("--package-name", name)
    return arguments

def _metadata_files(ctx):
    return [
        ctx.file.inrelease,
        ctx.file.release_metadata,
        ctx.file.release_gpg,
        ctx.file.packages_xz,
        ctx.file.packages_all_xz,
    ]

def _stage_repository(ctx, component_indexes, output, scratch):
    debian_tools = ctx.toolchains["//mkosi/toolchain:debian_tools_toolchain_type"].debian_tools
    run_python(
        ctx,
        arguments = [
            ctx.file._stager.path,
            _stager_arguments(ctx, debian_tools.launcher, output, scratch, component_indexes),
        ],
        inputs = _metadata_files(ctx) + [ctx.file._stager] + ctx.files._stager_modules + component_indexes + ctx.files.package_files,
        outputs = [output, scratch],
        mnemonic = "StageDebianSnapshot",
        tools = [debian_tools.launcher],
        interpreter = static_python_interpreter(debian_tools.python, debian_tools.python_files_to_run),
        progress_message = "Staging authenticated Debian snapshot %{label}",
    )

def _impl(ctx):
    if len(ctx.files.package_files) != len(ctx.attr.package_names):
        fail("package_files and package_names must have the same length")
    components, component_indexes = _component_indexes(ctx)
    output = ctx.actions.declare_directory(ctx.label.name + "_repository")
    scratch = ctx.actions.declare_directory(ctx.label.name + "_scratch")
    _stage_repository(ctx, component_indexes, output, scratch)
    repository = DebianSnapshotInfo(
        format_version = ctx.attr.format_version,
        distribution = ctx.attr.distribution,
        release = ctx.attr.release,
        codename = ctx.attr.codename,
        architecture = ctx.attr.architecture,
        components = components,
        snapshot = ctx.attr.snapshot,
        snapshot_url = ctx.attr.snapshot_url,
        lock_sha256 = ctx.attr.lock_sha256,
        repository = output,
        inrelease = ctx.file.inrelease,
        release_metadata = ctx.file.release_metadata,
        packages_metadata = depset([ctx.file.packages_xz, ctx.file.packages_all_xz] + component_indexes),
        package_files = depset(ctx.files.package_files),
    )
    return [repository, DefaultInfo(files = depset([output]))]

debian_snapshot = rule(
    implementation = _impl,
    attrs = {
        "architecture": attr.string(default = "amd64", doc = "Debian package architecture, such as `amd64`."),
        "codename": attr.string(default = "trixie", doc = "Debian codename, such as `trixie`."),
        "component_package_records": attr.string_list(
            doc = "component|architecture|path|sha256 records for component_packages.",
        ),
        "component_packages": attr.label_list(
            allow_files = True,
            doc = "Packages.xz indexes of components other than main, aligned with component_package_records.",
        ),
        "distribution": attr.string(default = "debian", doc = "mkosi distribution name, `debian`."),
        "format_version": attr.string(default = "debian-snapshot-v1", doc = "Repository layout contract version."),
        "inrelease": attr.label(mandatory = True, allow_single_file = True, doc = "Signed InRelease metadata."),
        "lock_sha256": attr.string(mandatory = True, doc = "SHA-256 of the lock that pins the repository and packages."),
        "metadata_digests": attr.string_dict(
            mandatory = True,
            doc = "SHA-256 of inrelease, release, release_gpg, packages_xz and packages_all_xz, keyed by those names.",
        ),
        "package_files": attr.label_list(mandatory = True, allow_files = True, doc = "Locked .deb files."),
        "package_names": attr.string_list(mandatory = True, doc = "Repository-local names of package_files, in order."),
        "package_records": attr.string_list(
            mandatory = True,
            doc = "name|version|architecture|filename|size|sha256|local name records of the locked packages.",
        ),
        "packages_all_path": attr.string(
            default = "dists/trixie/main/binary-all/Packages.xz",
            doc = "Repository path of packages_all_xz.",
        ),
        "packages_all_xz": attr.label(mandatory = True, allow_single_file = True, doc = "main binary-all Packages.xz."),
        "packages_path": attr.string(
            default = "dists/trixie/main/binary-amd64/Packages.xz",
            doc = "Repository path of packages_xz.",
        ),
        "packages_xz": attr.label(mandatory = True, allow_single_file = True, doc = "main binary-amd64 Packages.xz."),
        "release": attr.string(default = "13", doc = "Numeric Debian release, such as `13`."),
        "release_gpg": attr.label(mandatory = True, allow_single_file = True, doc = "Detached Release.gpg signature."),
        "release_metadata": attr.label(mandatory = True, allow_single_file = True, doc = "Release file of the snapshot, verified against inrelease."),
        "snapshot": attr.string(mandatory = True, doc = "Immutable snapshot identifier, such as 20250814T000000Z."),
        "snapshot_url": attr.string(mandatory = True, doc = "Immutable snapshot URL."),
        "_stager": attr.label(
            allow_single_file = True,
            cfg = "exec",
            default = "//mkosi/private:debian_snapshot.py",
        ),
        "_stager_modules": attr.label_list(
            allow_files = True,
            cfg = "exec",
            default = [
                "//mkosi/private:debian_control.py",
                "//mkosi/private:file_hashing.py",
                "//mkosi/private:sibling_loader.py",
            ],
        ),
    },
    toolchains = ["//mkosi/toolchain:debian_tools_toolchain_type"],
    exec_compatible_with = [
        "@platforms//os:linux",
        "@platforms//cpu:x86_64",
    ],
    doc = """Materializes an authenticated local APT repository from a pinned Debian snapshot.

Declare it through the debian_tools.snapshot module extension, which generates these attributes from a lock.
""",
)
