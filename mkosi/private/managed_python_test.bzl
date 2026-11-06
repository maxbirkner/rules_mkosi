"""Native test launcher for a Bazel-managed Python interpreter."""

ManagedPythonTestInfo = provider(
    "Managed interpreter test launcher contract.",
    fields = {
        "source": "The Python script File that the test runs.",
        "timeout": "Bazel timeout category of the test.",
    },
)

def _managed_python_test_impl(ctx):
    python = ctx.attr._python[DefaultInfo]
    executable = ctx.actions.declare_file(ctx.label.name)
    ctx.actions.symlink(
        output = executable,
        target_file = python.files_to_run.executable,
        is_executable = True,
    )

    transitive_files = []
    for data in ctx.attr.data:
        transitive_files.append(data[DefaultInfo].files)
    runfiles = ctx.runfiles(
        files = [ctx.file.src],
        transitive_files = depset(transitive = transitive_files),
    ).merge(python.default_runfiles)
    for data in ctx.attr.data:
        runfiles = runfiles.merge(data[DefaultInfo].default_runfiles)

    return [
        DefaultInfo(
            executable = executable,
            runfiles = runfiles,
        ),
        ManagedPythonTestInfo(
            source = ctx.file.src,
            timeout = getattr(ctx.attr, "timeout", "moderate"),
        ),
        RunEnvironmentInfo(
            environment = {"PYTHONNOUSERSITE": "1"},
        ),
    ]

_managed_python_attrs = {
    "data": attr.label_list(allow_files = True),
    "src": attr.label(
        allow_single_file = [".py"],
        mandatory = True,
        doc = "Python script automatically passed as the interpreter's first argument.",
    ),
    # The interpreter is resolved for rules_mkosi's Python line in its own configuration, so the test and its data
    # stay in the consumer's configuration.
    "_python": attr.label(
        default = Label("//mkosi/private:managed_python"),
        executable = True,
        cfg = "target",
    ),
}

_managed_python_test = rule(
    implementation = _managed_python_test_impl,
    test = True,
    attrs = _managed_python_attrs,
    doc = "Tests src with the registered managed interpreter of rules_mkosi's Python line, followed by args.",
)

def _src_arg(src):
    return [
        "$(rootpath @rules_mkosi//mkosi/private:managed_python_bootstrap.py)",
        "$(rootpath %s)" % src,
    ]

def managed_python_test(name, src, args = [], data = [], timeout = "moderate", tags = []):
    """Tests the Python script src with rules_mkosi's managed interpreter, independent of the consumer's Python.

    Args:
      name: Test name.
      src: Python script to run.
      args: Arguments passed to src.
      data: Files available to the test at run time.
      timeout: Bazel test timeout category.
      tags: Test tags.
    """
    _managed_python_test(
        name = name,
        src = src,
        args = _src_arg(src) + args,
        data = data + ["@rules_mkosi//mkosi/private:managed_python_bootstrap.py"],
        timeout = timeout,
        tags = tags,
    )
