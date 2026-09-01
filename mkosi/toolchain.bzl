"""Toolchain rule and provider for mkosi image assembly."""

load("//mkosi:versions.bzl", "MKOSI_VERSIONS")

_PYTHON_TOOLCHAIN_TYPE = "@rules_python//python:toolchain_type"

_ManagedPythonRuntimeInfo = provider(
    doc = "Managed in-build interpreter selected through Python toolchain resolution.",
    fields = {
        "interpreter": "The selected toolchain's original interpreter artifact.",
        "runtime_files": "Complete managed runtime closure.",
        "version": "Resolved interpreter version.",
    },
)

MkosiToolchainInfo = provider(
    doc = "Information used to execute an mkosi image build.",
    fields = {
        "format_version": "String identifying the toolchain output contract.",
        "name": "Logical name of the selected toolchain.",
        "version": "Pinned mkosi version.",
        "source_url": "Immutable URL used to fetch the mkosi source.",
        "source_sha256": "SHA-256 integrity hash of the mkosi source archive.",
        "integrity": "SRI integrity string for the mkosi source archive.",
        "python_version": "Required Bazel-managed Python major/minor line.",
        "resolved_python_version": "Concrete version supplied by the selected Python toolchain.",
        "resolved_python_interpreter": "Original interpreter selected by Python toolchain resolution.",
        "executable": "The Bazel-managed Python executable used to run mkosi.",
        "python": "The Bazel-managed Python executable used to run mkosi.",
        "python_files_to_run": "FilesToRunProvider for the managed Python executable.",
        "files_to_run": "Compatibility alias for the managed Python FilesToRunProvider.",
        "python_runtime_files": "Complete files from the managed Python runtime.",
        "script": "The exact mkosi Python entrypoint script.",
        "pefile": "The pinned pefile module used by mkosi.",
        "runfiles": "Runfiles object preserving mappings for mkosi and its dependencies.",
        "runfiles_files": "Complete mkosi source and dependency runfiles.",
    },
)

def _managed_python_tool_impl(ctx):
    runtime = ctx.toolchains[_PYTHON_TOOLCHAIN_TYPE].py3_runtime
    if runtime == None or runtime.interpreter == None:
        fail("managed_python_tool requires an in-build Python interpreter")
    version_info = runtime.interpreter_version_info
    if version_info == None:
        fail("the selected Python runtime must declare interpreter_version_info")

    required = ctx.attr.python_version.split(".")
    actual_minor = "{}.{}".format(version_info.major, version_info.minor)
    if len(required) < 2 or actual_minor != ".".join(required[:2]):
        fail(
            "the selected Python runtime is {}, but rules_mkosi requires {}.x".format(
                actual_minor,
                ctx.attr.python_version,
            ),
        )
    actual = actual_minor
    if version_info.micro != None:
        actual += "." + str(version_info.micro)

    executable = ctx.actions.declare_file("python3")
    ctx.actions.symlink(
        output = executable,
        target_file = runtime.interpreter,
        is_executable = True,
    )
    runtime_files = runtime.files or depset()
    files = depset([executable], transitive = [runtime_files])
    return [
        DefaultInfo(
            executable = executable,
            files = files,
            runfiles = ctx.runfiles(transitive_files = files),
        ),
        _ManagedPythonRuntimeInfo(
            interpreter = runtime.interpreter,
            runtime_files = files,
            version = actual,
        ),
    ]

managed_python_tool = rule(
    implementation = _managed_python_tool_impl,
    executable = True,
    attrs = {
        "python_version": attr.string(
            mandatory = True,
            doc = "Required Python major and minor version.",
        ),
    },
    toolchains = [_PYTHON_TOOLCHAIN_TYPE],
    doc = "Exposes the root-selected compatible Python toolchain as an executable.",
)

def _mkosi_toolchain_impl(ctx):
    if ctx.attr.version not in MKOSI_VERSIONS:
        fail("Unsupported mkosi version {}.".format(ctx.attr.version))
    python = ctx.attr.python[DefaultInfo]
    managed_python = ctx.attr.python[_ManagedPythonRuntimeInfo]
    python_runtime_files = managed_python.runtime_files
    pefile = None
    for file in ctx.files.python_dependency:
        if file.basename == "pefile.py":
            pefile = file
            break
    if pefile == None:
        fail("The mkosi Python dependency must provide pefile.py.")
    runfiles_files = depset(
        [ctx.file.script, pefile],
        transitive = [
            ctx.attr.runfiles[DefaultInfo].files,
            python_runtime_files,
        ],
    )
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
                resolved_python_version = managed_python.version,
                resolved_python_interpreter = managed_python.interpreter,
                executable = python.files_to_run.executable,
                python = python.files_to_run.executable,
                python_files_to_run = python.files_to_run,
                files_to_run = python.files_to_run,
                python_runtime_files = python_runtime_files,
                script = ctx.file.script,
                pefile = pefile,
                runfiles = ctx.runfiles(transitive_files = runfiles_files),
                runfiles_files = runfiles_files,
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
        "python": attr.label(
            allow_files = True,
            cfg = "exec",
            executable = True,
            mandatory = True,
            providers = [_ManagedPythonRuntimeInfo],
            doc = "The Bazel-managed Python executable.",
        ),
        "script": attr.label(
            allow_single_file = True,
            mandatory = True,
            doc = "The mkosi Python entrypoint script.",
        ),
        "python_dependency": attr.label(
            allow_files = True,
            mandatory = True,
            doc = "The pinned Python dependency containing pefile.py.",
        ),
        "runfiles": attr.label(
            mandatory = True,
            doc = "The complete mkosi source and dependency runfiles.",
        ),
    },
    doc = "Defines an mkosi toolchain.",
)
