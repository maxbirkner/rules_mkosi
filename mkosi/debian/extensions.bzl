"""Bzlmod extension for the pinned Debian userspace tree."""

load("//mkosi/debian:provenance.bzl", "DEBIAN_TOOLS_ARCHIVE_SHA256", "DEBIAN_TOOLS_LOCK_SHA256", "DEBIAN_TOOLS_REQUIRED_COMPONENTS")
load("//mkosi/private:debian_tools_repo.bzl", "debian_tools_repo")

_toolchain = tag_class(
    attrs = {},
)

def _debian_tools_impl(module_ctx):
    debian_tools_repo(
        name = "mkosi_debian_tools",
        package_repo = "@mkosi_debian_packages",
        provenance = "@rules_mkosi//mkosi/debian:provenance.bzl",
        components = "@rules_mkosi//mkosi/debian:components.txt",
        required_components = DEBIAN_TOOLS_REQUIRED_COMPONENTS,
        lock_sha256 = DEBIAN_TOOLS_LOCK_SHA256,
        archive_sha256 = DEBIAN_TOOLS_ARCHIVE_SHA256,
    )
    return module_ctx.extension_metadata(reproducible = True)

debian_tools = module_extension(
    implementation = _debian_tools_impl,
    tag_classes = {"toolchain": _toolchain},
    arch_dependent = False,
    os_dependent = True,
)
