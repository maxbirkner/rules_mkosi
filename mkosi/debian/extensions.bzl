"""Bzlmod extension for the pinned Debian userspace tree."""

load(
    "//mkosi/debian:provenance.bzl",
    "DEBIAN_TOOLS_ARCHIVE_SHA256",
    "DEBIAN_TOOLS_LOCK_SHA256",
    "DEBIAN_TOOLS_PYTHON_VERSION",
    "DEBIAN_TOOLS_REQUIRED_COMPONENTS",
)
load("//mkosi/private:debian_package_repo.bzl", "debian_package_repo")
load("//mkosi/private:debian_python_repo.bzl", "debian_python_repo")
load("//mkosi/private:debian_snapshot_repo.bzl", "debian_snapshot_repo")
load("//mkosi/private:debian_tools_repo.bzl", "debian_tools_repo")

_toolchain = tag_class(
    attrs = {},
)

def _debian_tools_impl(module_ctx):
    debian_package_repo(
        name = "mkosi_debian_package_inputs",
        lock = "@rules_mkosi//mkosi/debian:debian13.lock.json",
    )
    debian_snapshot_repo(
        name = "mkosi_debian_snapshot",
        lock = "@rules_mkosi//mkosi/debian:debian13.lock.json",
        package_repo = "@mkosi_debian_package_inputs",
        lock_sha256 = DEBIAN_TOOLS_LOCK_SHA256,
    )
    debian_python_repo(name = "mkosi_debian_python")
    debian_tools_repo(
        name = "mkosi_debian_tools",
        package_repo = "@mkosi_debian_package_inputs",
        provenance = "@rules_mkosi//mkosi/debian:provenance.bzl",
        components = "@rules_mkosi//mkosi/debian:components.txt",
        required_components = DEBIAN_TOOLS_REQUIRED_COMPONENTS,
        lock_sha256 = DEBIAN_TOOLS_LOCK_SHA256,
        archive_sha256 = DEBIAN_TOOLS_ARCHIVE_SHA256,
        python_version = DEBIAN_TOOLS_PYTHON_VERSION,
    )
    return module_ctx.extension_metadata(reproducible = True)

debian_tools = module_extension(
    implementation = _debian_tools_impl,
    tag_classes = {"toolchain": _toolchain},
    arch_dependent = False,
    os_dependent = True,
)
