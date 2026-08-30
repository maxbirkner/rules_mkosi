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
    debian_tools = ctx.toolchains["//mkosi/toolchain:debian_tools_toolchain_type"].debian_tools
    image = ctx.actions.declare_file(ctx.label.name + ".img")
    version = ctx.actions.declare_file(ctx.label.name + ".mkosi_version")
    scratch = ctx.actions.declare_directory(ctx.label.name + ".debian_tools_scratch")

    ctx.actions.run(
        executable = debian_tools.launcher_files_to_run,
        tools = [
            toolchain.files_to_run,
            debian_tools.tree,
            debian_tools.launcher_files_to_run,
        ],
        arguments = [
            "--write-image",
            image.path,
            version.path,
            ctx.attr.distribution,
            toolchain.format_version,
            "/usr/bin/apt-get",
            "--version",
        ],
        env = {
            "PATH": "",
            "MKOSI_DEBIAN_TOOLS_TREE": debian_tools.tree.path,
            "MKOSI_DEBIAN_TOOLS_LAUNCHER": debian_tools.launcher.path,
            "MKOSI_DEBIAN_TOOLS_SCRATCH": scratch.path,
            "DEBIAN_TOOLS_ARCHIVE": debian_tools.tree.path,
            "DEBIAN_TOOLS_ARCHIVE_SHA256": debian_tools.archive_sha256,
            "DEBIAN_TOOLS_EXTRACTOR": debian_tools.extractor.path,
        },
        outputs = [image, version, scratch],
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
    toolchains = [
        "//mkosi/toolchain:toolchain_type",
        "//mkosi/toolchain:debian_tools_toolchain_type",
    ],
    exec_compatible_with = [
        "@platforms//os:linux",
        "@platforms//cpu:x86_64",
    ],
)
