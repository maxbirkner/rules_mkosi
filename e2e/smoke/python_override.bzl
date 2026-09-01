"""Consumer-owned executable wrapper used to prove Python toolchain selection."""

def _consumer_python_impl(ctx):
    executable = ctx.actions.declare_file(ctx.label.name)
    ctx.actions.symlink(
        output = executable,
        target_file = ctx.executable.interpreter,
        is_executable = True,
    )
    runtime_files = ctx.attr.runtime[DefaultInfo].files
    files = depset([executable], transitive = [runtime_files])
    return [
        DefaultInfo(
            executable = executable,
            files = files,
            runfiles = ctx.runfiles(transitive_files = files),
        ),
    ]

consumer_python = rule(
    implementation = _consumer_python_impl,
    executable = True,
    attrs = {
        "interpreter": attr.label(
            allow_files = True,
            cfg = "exec",
            executable = True,
            mandatory = True,
            doc = "Consumer-selected in-build Python interpreter.",
        ),
        "runtime": attr.label(
            cfg = "exec",
            mandatory = True,
            doc = "Complete files for the selected interpreter.",
        ),
    },
    doc = "Wraps a consumer-owned interpreter with a recognizable executable.",
)
