"""Native test launcher for a Bazel-managed Python interpreter."""

ManagedPythonTestInfo = provider(
    "Managed interpreter test launcher contract.",
    fields = ["source", "timeout"],
)

def _managed_python_test_impl(ctx):
    runtime = ctx.toolchains["@rules_python//python:toolchain_type"].py3_runtime
    if runtime.interpreter == None:
        fail("managed_python_test requires an in-build Python interpreter")

    executable = ctx.actions.declare_file(ctx.label.name)
    ctx.actions.symlink(
        output = executable,
        target_file = runtime.interpreter,
        is_executable = True,
    )

    transitive_files = [runtime.files or depset()]
    for data in ctx.attr.data:
        transitive_files.append(data[DefaultInfo].files)
    runfiles = ctx.runfiles(
        files = [ctx.file.src],
        transitive_files = depset(transitive = transitive_files),
    )
    for data in ctx.attr.data:
        runfiles = runfiles.merge(data[DefaultInfo].default_runfiles)

    return [
        DefaultInfo(
            executable = executable,
            runfiles = runfiles,
        ),
        ManagedPythonTestInfo(
            source = ctx.file.src,
            timeout = ctx.attr.timeout,
        ),
        RunEnvironmentInfo(
            environment = {
                "PATH": "",
                "PYTHONNOUSERSITE": "1",
            },
        ),
    ]

_managed_python_attrs = {
    "src": attr.label(
        allow_single_file = [".py"],
        mandatory = True,
        doc = "Python script automatically passed as the interpreter's first argument.",
    ),
    "data": attr.label_list(allow_files = True),
}

_managed_python_binary_rule = rule(
    implementation = _managed_python_test_impl,
    executable = True,
    attrs = _managed_python_attrs,
    toolchains = ["@rules_python//python:toolchain_type"],
    doc = "Runs src with the registered managed interpreter, followed by arguments.",
)

_managed_python_test = rule(
    implementation = _managed_python_test_impl,
    test = True,
    attrs = _managed_python_attrs,
    toolchains = ["@rules_python//python:toolchain_type"],
    doc = "Tests src with the registered managed interpreter, followed by args.",
)

def _src_arg(src):
    return ["$(rootpath %s)" % src]

def managed_python_binary(name, src, args = [], data = [], tags = []):
    _managed_python_binary_rule(
        name = name,
        src = src,
        args = _src_arg(src) + args,
        data = data,
        tags = tags,
    )

def managed_python_test(name, src, args = [], data = [], timeout = "moderate", tags = []):
    _managed_python_test(
        name = name,
        src = src,
        args = _src_arg(src) + args,
        data = data,
        timeout = timeout,
        tags = tags,
    )
