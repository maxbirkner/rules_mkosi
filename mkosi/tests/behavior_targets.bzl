"""Analysis-time ownership of root behavior-matrix labels."""

def _behavior_targets_impl(ctx):
    output = ctx.actions.declare_file(ctx.label.name + ".txt")
    ctx.actions.write(
        output,
        "\n".join(sorted([str(target.label) for target in ctx.attr.targets])) + "\n",
    )
    return [DefaultInfo(files = depset([output]))]

behavior_targets = rule(
    implementation = _behavior_targets_impl,
    attrs = {
        "targets": attr.label_list(
            allow_files = True,
            doc = "Mapped test targets that Bazel must resolve during analysis.",
        ),
    },
    doc = "Resolves mapped test labels and exports their canonical names.",
)
