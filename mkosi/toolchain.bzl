"""Toolchain rule and provider for mkosi image assembly."""

load("//mkosi:versions.bzl", "MKOSI_VERSIONS")

_PYTHON_TOOLCHAIN_TYPE = "@rules_python//python:toolchain_type"
_PYTHON_VERSION_SETTING = str(Label("@rules_python//python/config_settings:python_version"))

def _python_version_transition_impl(_settings, attr):
    return {_PYTHON_VERSION_SETTING: attr.python_version}

# Resolves the Python toolchain and locked pip dependencies for the rule's Python line rather than the consumer's
# default Python version.
_python_version_transition = transition(
    implementation = _python_version_transition_impl,
    inputs = [],
    outputs = [_PYTHON_VERSION_SETTING],
)

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
        "executable": "The Bazel-managed Python executable used to run mkosi.",
        "files_to_run": "Compatibility alias for the managed Python FilesToRunProvider.",
        "format_version": "String identifying the toolchain output contract.",
        "integrity": "SRI integrity string for the mkosi source archive.",
        "name": "Logical name of the selected toolchain.",
        "pefile": "The pinned pefile module used by mkosi.",
        "python": "The Bazel-managed Python executable used to run mkosi.",
        "python_files_to_run": "FilesToRunProvider for the managed Python executable.",
        "python_runtime_files": "Complete files from the managed Python runtime.",
        "python_version": "Required Bazel-managed Python major/minor line.",
        "resolved_python_interpreter": "Original interpreter selected by Python toolchain resolution.",
        "resolved_python_version": "Concrete version supplied by the selected Python toolchain.",
        "runfiles": "Runfiles object preserving mappings for mkosi and its dependencies.",
        "runfiles_files": "Complete mkosi source and dependency runfiles.",
        "script": "The exact mkosi Python entrypoint script.",
        "source_sha256": "SHA-256 integrity hash of the mkosi source archive.",
        "source_url": "Immutable URL used to fetch the mkosi source.",
        "version": "Pinned mkosi version.",
    },
)

def _resolved_python_version(runtime, required_version):
    """Returns the runtime's full version after checking that it matches the required major and minor version."""
    version_info = runtime.interpreter_version_info
    if version_info == None:
        fail("the selected Python runtime must declare interpreter_version_info")
    required = required_version.split(".")
    actual_minor = "{}.{}".format(version_info.major, version_info.minor)
    if len(required) < 2 or actual_minor != ".".join(required[:2]):
        fail(
            "the selected Python runtime is {}, but rules_mkosi requires {}.x".format(
                actual_minor,
                required_version,
            ),
        )
    if version_info.micro != None:
        return actual_minor + "." + str(version_info.micro)
    return actual_minor

def _managed_python_tool_impl(ctx):
    runtime = ctx.toolchains[_PYTHON_TOOLCHAIN_TYPE].py3_runtime
    if runtime == None or runtime.interpreter == None:
        fail("managed_python_tool requires an in-build Python interpreter")
    actual = _resolved_python_version(runtime, ctx.attr.python_version)

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
    cfg = _python_version_transition,
    executable = True,
    attrs = {
        "python_version": attr.string(
            mandatory = True,
            doc = "Required Python major and minor version. It is also selected for Python toolchain resolution, " +
                  "independent of the consumer's default Python version.",
        ),
    },
    toolchains = [_PYTHON_TOOLCHAIN_TYPE],
    doc = "Exposes the root-selected compatible Python toolchain as an executable.",
)

def _pefile(files):
    for file in files:
        if file.basename == "pefile.py":
            return file
    fail("The mkosi Python dependency must provide pefile.py.")

def _mkosi_toolchain_impl(ctx):
    if ctx.attr.version not in MKOSI_VERSIONS:
        fail("Unsupported mkosi version {}.".format(ctx.attr.version))
    python = ctx.attr.python[DefaultInfo]
    managed_python = ctx.attr.python[_ManagedPythonRuntimeInfo]
    python_runtime_files = managed_python.runtime_files
    pefile = _pefile(ctx.files.python_dependency)
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
    cfg = _python_version_transition,
    attrs = {
        "format_version": attr.string(
            default = "mkosi-v1",
            doc = "Output contract implemented by this toolchain.",
        ),
        "python": attr.label(
            allow_files = True,
            cfg = "exec",
            executable = True,
            mandatory = True,
            providers = [_ManagedPythonRuntimeInfo],
            doc = "The Bazel-managed Python executable.",
        ),
        "python_dependency": attr.label(
            allow_files = True,
            mandatory = True,
            doc = "The pinned Python dependency containing pefile.py.",
        ),
        "python_version": attr.string(
            mandatory = True,
            doc = "Bazel-managed Python runtime version. It is also selected for the locked Python dependencies, " +
                  "independent of the consumer's default Python version.",
        ),
        "runfiles": attr.label(
            mandatory = True,
            doc = "The complete mkosi source and dependency runfiles.",
        ),
        "script": attr.label(
            allow_single_file = True,
            mandatory = True,
            doc = "The mkosi Python entrypoint script.",
        ),
        "source_integrity": attr.string(
            mandatory = True,
            doc = "SRI integrity string for the source archive.",
        ),
        "source_sha256": attr.string(
            mandatory = True,
            doc = "SHA-256 integrity hash of the source archive.",
        ),
        "source_url": attr.string(mandatory = True, doc = "Immutable source URL."),
        "toolchain_name": attr.string(
            mandatory = True,
            doc = "Logical name exposed for diagnostics.",
        ),
        "version": attr.string(mandatory = True, doc = "Pinned mkosi version."),
    },
    doc = "Defines an mkosi toolchain.",
)
