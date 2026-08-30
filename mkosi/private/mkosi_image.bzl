"""Implementation of the public mkosi_image rule."""

MkosiImageInfo = provider(
    doc = "Information about an image produced by mkosi_image.",
    fields = {
        "image": "The generated raw disk image artifact.",
    },
)

def _mkosi_image_impl(ctx):
    mkosi = ctx.toolchains["//mkosi/toolchain:toolchain_type"].mkosi
    debian_tools = ctx.toolchains["//mkosi/toolchain:debian_tools_toolchain_type"].debian_tools
    image = ctx.actions.declare_file(ctx.label.name + ".raw")
    output_name = image.basename[:-len(".raw")]
    workspace = image.dirname + "/." + ctx.label.name + "-mkosi"

    arguments = ctx.actions.args()
    arguments.add("-I")
    arguments.add(ctx.file.config.path)
    arguments.add("--tools-tree")
    arguments.add(debian_tools.tree_root.path)
    arguments.add("--output-directory")
    arguments.add(image.dirname)
    arguments.add("--output")
    arguments.add(output_name)
    arguments.add("--workspace-directory")
    arguments.add(workspace)
    arguments.add("--cache-directory")
    arguments.add(workspace + "/cache")
    arguments.add("--package-cache-directory")
    arguments.add(workspace + "/package-cache")
    arguments.add("--build-directory")
    arguments.add(workspace + "/build")
    arguments.add("--build-sources=")
    arguments.add("--no-pager")
    arguments.add("build")

    ctx.actions.run(
        executable = mkosi.executable,
        arguments = [arguments],
        inputs = depset([ctx.file.config, debian_tools.tree_root]),
        tools = [mkosi.files_to_run],
        outputs = [image],
        env = {
            "PATH": "",
        },
        execution_requirements = {
            "no-cache": "1",
            "no-remote-exec": "1",
            "requires-network": "1",
        },
        mnemonic = "MkosiImage",
        progress_message = "Building mkosi image %{label}",
    )

    return [
        DefaultInfo(files = depset([image])),
        MkosiImageInfo(image = image),
    ]

mkosi_image = rule(
    implementation = _mkosi_image_impl,
    attrs = {
        "config": attr.label(
            mandatory = True,
            allow_single_file = True,
            doc = "The mkosi configuration file to include.",
        ),
    },
    doc = """Builds a raw disk image using the pinned mkosi and Debian toolchains.

The action downloads target Debian packages over the network and requires the
Linux namespace and mount capabilities documented by the host-kernel contract.
It is intentionally non-cacheable and does not claim remote-execution or
offline hermeticity.
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
