"""A native Bazel test rule for direct managed Python execution."""

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
        RunEnvironmentInfo(
            environment = {
                "PYTHONNOUSERSITE": "1",
            },
        ),
    ]

managed_python_test = rule(
    implementation = _managed_python_test_impl,
    test = True,
    attrs = {
        "src": attr.label(
            allow_single_file = [".py"],
        ),
        "data": attr.label_list(
            allow_files = True,
        ),
    },
    toolchains = ["@rules_python//python:toolchain_type"],
    doc = "Runs a Python test directly with the registered managed interpreter.",
)
