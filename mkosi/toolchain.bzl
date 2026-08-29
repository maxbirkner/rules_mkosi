"""Toolchain rule and provider for mkosi image assembly."""

load("//mkosi:versions.bzl", "MKOSI_VERSIONS")

MkosiToolchainInfo = provider(
    doc = "Information used to execute an mkosi image build.",
    fields = {
        "format_version": "String identifying the toolchain output contract.",
        "name": "Logical name of the selected toolchain.",
        "version": "Pinned mkosi version.",
        "source_url": "Immutable URL used to fetch the mkosi source.",
        "source_sha256": "SHA-256 integrity hash of the mkosi source archive.",
        "integrity": "SRI integrity string for the mkosi source archive.",
        "python_version": "Bazel-managed Python runtime version.",
        "executable": "The mkosi CLI executable.",
        "runfiles": "Runfiles object preserving repository mappings for the mkosi CLI.",
        "files_to_run": "FilesToRunProvider preserving executable and runfiles mappings.",
        "runfiles_files": "Complete runfiles files for inspection and compatibility.",
    },
)

def _mkosi_toolchain_impl(ctx):
    if ctx.attr.version not in MKOSI_VERSIONS:
        fail("Unsupported mkosi version {}.".format(ctx.attr.version))
    executable = ctx.attr.executable[DefaultInfo]
    return [
        platform_common.ToolchainInfo(
            mkosi = MkosiToolchainInfo(
                format_version = ctx.attr.format_version,
                name = ctx.attr.toolchain_name,
                version = ctx.attr.version,
                source_url = ctx.attr.source_url,
                source_sha256 = ctx.attr.source_sha256,
                integrity = ctx.attr.source_integrity,
                python_version = ctx.attr.python_version,
                executable = executable.files_to_run.executable,
                runfiles = executable.default_runfiles,
                files_to_run = executable.files_to_run,
                runfiles_files = depset(
                    [executable.files_to_run.executable],
                    transitive = [executable.default_runfiles.files],
                ),
            ),
        ),
    ]

mkosi_toolchain = rule(
    implementation = _mkosi_toolchain_impl,
    attrs = {
        "format_version": attr.string(
            default = "mkosi-v1",
            doc = "Output contract implemented by this toolchain.",
        ),
        "toolchain_name": attr.string(
            mandatory = True,
            doc = "Logical name exposed for diagnostics.",
        ),
        "version": attr.string(mandatory = True, doc = "Pinned mkosi version."),
        "source_url": attr.string(mandatory = True, doc = "Immutable source URL."),
        "source_sha256": attr.string(
            mandatory = True,
            doc = "SHA-256 integrity hash of the source archive.",
        ),
        "source_integrity": attr.string(
            mandatory = True,
            doc = "SRI integrity string for the source archive.",
        ),
        "python_version": attr.string(
            mandatory = True,
            doc = "Bazel-managed Python runtime version.",
        ),
        "executable": attr.label(
            cfg = "exec",
            executable = True,
            mandatory = True,
            doc = "The mkosi CLI target.",
        ),
    },
    doc = "Defines an mkosi toolchain.",
)
