"""Implementation of the public mkosi_image rule."""

MkosiImageInfo = provider(
    doc = "Information about an image produced by mkosi_image.",
    fields = {
        "distribution": "Distribution selected for the image.",
        "image": "The generated image artifact.",
        "toolchain_name": "Logical name of the toolchain used to build the image.",
    },
)

def _mkosi_image_impl(ctx):
    toolchain = ctx.toolchains["//mkosi/toolchain:toolchain_type"].mkosi
    image = ctx.actions.declare_file(ctx.label.name + ".img")
    version = ctx.actions.declare_file(ctx.label.name + ".mkosi_version")

    ctx.actions.run(
        executable = toolchain.files_to_run,
        tools = [toolchain.files_to_run],
        arguments = ["--write-version", version.path],
        env = {"PATH": ""},
        outputs = [version],
    )

    ctx.actions.write(
        output = image,
        content = "\n".join([
            "rules_mkosi placeholder image",
            "format={}".format(toolchain.format_version),
            "distribution={}".format(ctx.attr.distribution),
            "",
        ]),
    )

    return [
        DefaultInfo(files = depset([image])),
        MkosiImageInfo(
            distribution = ctx.attr.distribution,
            image = image,
            toolchain_name = toolchain.name,
        ),
    ]

mkosi_image = rule(
    implementation = _mkosi_image_impl,
    attrs = {
        "distribution": attr.string(
            default = "debian",
            doc = "Distribution to record in the placeholder image.",
            values = ["debian", "ubuntu"],
        ),
    },
    doc = """Creates a deterministic placeholder image.

This initial implementation validates the public rule, provider, module
extension, and toolchain architecture without invoking host tools. It will be
replaced by an mkosi-backed action.
""",
    provides = [MkosiImageInfo],
    toolchains = ["//mkosi/toolchain:toolchain_type"],
)
