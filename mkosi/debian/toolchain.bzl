"""Debian build-time userspace toolchain."""

DebianToolsInfo = provider(
    doc = "Pinned Debian userspace tools and provenance.",
    fields = {
        "format_version": "Toolchain contract version.",
        "distribution": "Distribution name.",
        "release": "Numeric Debian release.",
        "codename": "Debian codename.",
        "architecture": "Debian package architecture.",
        "snapshot": "Pinned snapshot identifier.",
        "snapshot_url": "Pinned snapshot URL.",
        "lock_sha256": "SHA-256 digest of the checked-in package lockfile.",
        "archive_sha256": "SHA-256 digest of the flattened package archive.",
        "python_version": "Pinned static Python bootstrap version.",
        "tree": "Flattened tar archive containing the installed package tree.",
        "tree_root": "Extracted Debian tools TreeArtifact.",
        "launcher": "FilesToRunProvider for the root-isolated executable launcher.",
        "python": "Pinned static Python bootstrap interpreter.",
        "python_files_to_run": "FilesToRunProvider for the static interpreter.",
        "launcher_script": "Click launcher implementation source retained for compatibility.",
        "extractor": "Shared strict extraction implementation.",
        "tree_files_to_run": "FilesToRunProvider preserving tree mappings.",
        "tree_runfiles": "Runfiles for the package tree.",
        "provenance": "Checked-in package provenance metadata.",
        "components": "Checked-in required component manifest.",
        "required_components": "Initial tracer-required component names.",
    },
)

_LINUX_X86_64 = [
    "@platforms//os:linux",
    "@platforms//cpu:x86_64",
]

_STATIC_PYTHON_ATTRS = {
    "_python": attr.label(
        allow_files = True,
        executable = True,
        cfg = "exec",
        default = "@mkosi_debian_python//:python",
    ),
    "_python_runtime": attr.label(
        cfg = "exec",
        default = "@mkosi_debian_python//:runtime",
    ),
}

def _run_static_python(ctx, arguments, inputs, output, mnemonic, progress_message):
    """Runs a script with the static bootstrap interpreter in isolated mode."""
    python = ctx.executable._python
    ctx.actions.run(
        executable = python,
        arguments = ["-I"] + arguments,
        inputs = depset(inputs, transitive = [ctx.attr._python_runtime[DefaultInfo].files]),
        tools = [python],
        outputs = [output],
        env = {
            "PYTHONHOME": python.path[:python.path.rfind("/")],
            "PYTHONNOUSERSITE": "1",
            "PATH": "",
        },
        mnemonic = mnemonic,
        progress_message = progress_message,
    )

def _tree_impl(ctx):
    root = ctx.actions.declare_directory(ctx.label.name + "_root")
    _run_static_python(
        ctx,
        arguments = [ctx.file.extractor.path, ctx.file.archive.path, root.path, ctx.attr.archive_sha256],
        inputs = [ctx.file.extractor, ctx.file.archive],
        output = root,
        mnemonic = "ExtractDebianTools",
        progress_message = "Extracting Debian tools tree %{label}",
    )
    return [DefaultInfo(files = depset([root]))]

def _archive_impl(ctx):
    output = ctx.actions.declare_file("flat.tar")
    _run_static_python(
        ctx,
        arguments = [ctx.file.archive_builder.path, output.path, ctx.file.package_manifest.path] +
                    [package.path for package in ctx.files.packages],
        inputs = [ctx.file.archive_builder, ctx.file._extract_tree, ctx.file.package_manifest] + ctx.files.packages,
        output = output,
        mnemonic = "BuildDebianToolsArchive",
        progress_message = "Building Debian tools archive %{label}",
    )
    return [DefaultInfo(files = depset([output]))]

debian_tools_archive = rule(
    implementation = _archive_impl,
    attrs = {
        "packages": attr.label_list(mandatory = True, allow_files = True, doc = "Pinned .deb files."),
        "package_manifest": attr.label(
            mandatory = True,
            allow_single_file = True,
            doc = "Manifest of the expected packages.",
        ),
        "archive_builder": attr.label(
            mandatory = False,
            allow_single_file = True,
            default = "//mkosi/debian:package_archive.py",
            doc = "Script that builds the archive.",
        ),
        # package_archive.py loads its member path validation from this sibling.
        "_extract_tree": attr.label(default = "//mkosi/debian:extract_tree.py", allow_single_file = True),
    } | _STATIC_PYTHON_ATTRS,
    exec_compatible_with = _LINUX_X86_64,
    doc = "Builds a flattened archive of the installed tree of checksum-pinned Debian packages.",
)

debian_tools_tree = rule(
    implementation = _tree_impl,
    attrs = {
        "archive": attr.label(mandatory = True, allow_single_file = True, doc = "debian_tools_archive output."),
        "extractor": attr.label(mandatory = True, allow_single_file = True, doc = "Script that extracts the archive."),
        "archive_sha256": attr.string(mandatory = True, doc = "Expected SHA-256 of the archive."),
    } | _STATIC_PYTHON_ATTRS,
    exec_compatible_with = _LINUX_X86_64,
    doc = "Extracts a debian_tools_archive into a directory after verifying its digest.",
)

_PREFLIGHT_SCRIPT = """#!/bin/sh
set -eu
PATH=
export PATH
runfiles_root="${{RUNFILES_DIR:-$0.runfiles}}"
runfile() {{
    path="$1"
    path="${{path#../}}"
    path="${{path#external/}}"
    if [ -e "$runfiles_root/$path" ]; then printf '%s/%s' "$runfiles_root" "$path"
    elif [ -e "$runfiles_root/_main/$path" ]; then printf '%s/_main/%s' "$runfiles_root" "$path"
    else printf '%s/%s' "$runfiles_root" "$path"; fi
}}
launcher="$(runfile {launcher})"
provenance="$(runfile {provenance})"
components="$(runfile {components})"
[ -x "$launcher" ] || {{ echo "Debian root-isolated launcher is missing: $launcher" >&2; exit 1; }}
[ -s "$provenance" ] || {{ echo "Debian tools provenance is missing: $provenance" >&2; exit 1; }}
[ -s "$components" ] || {{ echo "Debian tools component manifest is missing: $components" >&2; exit 1; }}
for component in {required}
do
    found=0
    while IFS='|' read -r declared_name declared_path declared_package
    do
        if [ "$declared_name" = "$component" ]; then
            found=1
            break
        fi
    done < "$components"
    if [ "$found" -ne 1 ]; then
        echo "Debian tools component is missing from the pinned tree: $component" >&2
        exit 1
    fi
    echo "validated Debian tools component: $component"
done
"$launcher" --validate-only /bin/sh
"""

def _preflight_impl(ctx):
    output = ctx.actions.declare_file(ctx.label.name + ".sh")
    ctx.actions.write(
        output = output,
        is_executable = True,
        content = _PREFLIGHT_SCRIPT.format(
            launcher = repr(ctx.attr.launcher[DefaultInfo].files_to_run.executable.short_path),
            provenance = repr(ctx.file.provenance.short_path),
            components = repr(ctx.file.components.short_path),
            required = " ".join(ctx.attr.required_components),
        ),
    )
    runfiles = ctx.runfiles(files = [output, ctx.file.provenance, ctx.file.components])
    runfiles = runfiles.merge(ctx.attr.launcher[DefaultInfo].default_runfiles)
    return [DefaultInfo(executable = output, runfiles = runfiles)]

_PREFLIGHT_ATTRS = {
    "tree": attr.label(mandatory = True),
    "launcher": attr.label(mandatory = True, allow_files = True, executable = True, cfg = "exec"),
    "provenance": attr.label(mandatory = True, allow_single_file = True),
    "components": attr.label(mandatory = True, allow_single_file = True),
    "required_components": attr.string_list(mandatory = True),
}

debian_tools_preflight = rule(
    implementation = _preflight_impl,
    executable = True,
    attrs = _PREFLIGHT_ATTRS,
    doc = "Checks the pinned tree and every required tracer component.",
)

debian_tools_preflight_test = rule(
    implementation = _preflight_impl,
    test = True,
    attrs = _PREFLIGHT_ATTRS,
    doc = "Checks the pinned tree and every required tracer component.",
)

def _debian_tools_toolchain_impl(ctx):
    tree_info = ctx.attr.tree[DefaultInfo]
    tree_file = ctx.file.tree
    tree_root = ctx.attr.tree_root[DefaultInfo].files.to_list()[0]
    launcher = ctx.attr.launcher[DefaultInfo]
    info = DebianToolsInfo(
        format_version = ctx.attr.format_version,
        distribution = ctx.attr.distribution,
        release = ctx.attr.release,
        codename = ctx.attr.codename,
        architecture = ctx.attr.architecture,
        snapshot = ctx.attr.snapshot,
        snapshot_url = ctx.attr.snapshot_url,
        lock_sha256 = ctx.attr.lock_sha256,
        archive_sha256 = ctx.attr.archive_sha256,
        python_version = ctx.attr.python_version,
        tree = tree_file,
        tree_root = tree_root,
        launcher = launcher.files_to_run,
        python = ctx.attr.python[DefaultInfo].files_to_run.executable,
        python_files_to_run = ctx.attr.python[DefaultInfo].files_to_run,
        launcher_script = ctx.file.launcher_script,
        extractor = ctx.file.extractor,
        tree_files_to_run = tree_info.files_to_run,
        tree_runfiles = tree_info.default_runfiles,
        provenance = ctx.file.provenance,
        components = ctx.file.components,
        required_components = ctx.attr.required_components,
    )
    return [platform_common.ToolchainInfo(debian_tools = info), info]

debian_tools_toolchain = rule(
    implementation = _debian_tools_toolchain_impl,
    attrs = {
        "format_version": attr.string(default = "debian-tools-v1"),
        "distribution": attr.string(default = "debian"),
        "release": attr.string(mandatory = True),
        "codename": attr.string(mandatory = True),
        "architecture": attr.string(mandatory = True),
        "snapshot": attr.string(mandatory = True),
        "snapshot_url": attr.string(mandatory = True),
        "lock_sha256": attr.string(mandatory = True),
        "archive_sha256": attr.string(mandatory = True),
        "python_version": attr.string(mandatory = True),
        "tree": attr.label(mandatory = True, allow_single_file = True),
        "tree_root": attr.label(mandatory = True),
        "launcher": attr.label(mandatory = True, executable = True, cfg = "exec"),
        "python": attr.label(mandatory = True, allow_files = True, executable = True, cfg = "exec"),
        "launcher_script": attr.label(mandatory = True, allow_single_file = True),
        "extractor": attr.label(mandatory = True, allow_single_file = True),
        "provenance": attr.label(mandatory = True, allow_single_file = True),
        "components": attr.label(mandatory = True, allow_single_file = True),
        "required_components": attr.string_list(mandatory = True),
    },
    doc = "Defines the pinned Debian userspace toolchain.",
)

def _launcher_probe_impl(ctx):
    debian_tools = ctx.toolchains["//mkosi/toolchain:debian_tools_toolchain_type"].debian_tools
    output = ctx.actions.declare_file(ctx.label.name + ".txt")
    scratch = ctx.actions.declare_directory(ctx.label.name + ".scratch")
    ctx.actions.run(
        executable = debian_tools.launcher,
        arguments = [
            "--write-version",
            output.path,
            "/usr/bin/dpkg",
            "--version",
        ],
        env = {
            "PATH": "",
            "MKOSI_DEBIAN_TOOLS_SCRATCH": scratch.path,
        },
        tools = [debian_tools.launcher],
        outputs = [output, scratch],
        mnemonic = "DebianToolsLauncherProbe",
    )
    return [DefaultInfo(files = depset([output]))]

debian_tools_launcher_probe = rule(
    implementation = _launcher_probe_impl,
    attrs = {},
    toolchains = ["//mkosi/toolchain:debian_tools_toolchain_type"],
    exec_compatible_with = _LINUX_X86_64,
    doc = "Invokes the public DebianToolsInfo launcher through an action.",
)
