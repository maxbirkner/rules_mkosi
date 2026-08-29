"""Bazelmod extension for rules_mkosi toolchains."""

load("//mkosi/private:toolchains_repo.bzl", "toolchains_repo")

_toolchain = tag_class(
    attrs = {
        "name": attr.string(
            default = "mkosi",
            doc = "Logical toolchain name. Only the root module may override it.",
        ),
    },
)

def _mkosi_impl(module_ctx):
    names = []

    for mod in module_ctx.modules:
        for toolchain in mod.tags.toolchain:
            if toolchain.name != "mkosi" and not mod.is_root:
                fail("Only the root module may override the mkosi toolchain name.")
            if toolchain.name not in names:
                names.append(toolchain.name)

    if not names:
        names.append("mkosi")

    if len(names) > 1:
        fail("Only one mkosi toolchain may be configured.")

    toolchains_repo(
        name = "mkosi_toolchains",
        toolchain_name = names[0],
    )

    return module_ctx.extension_metadata(reproducible = True)

mkosi = module_extension(
    implementation = _mkosi_impl,
    tag_classes = {"toolchain": _toolchain},
    arch_dependent = False,
    os_dependent = False,
)
