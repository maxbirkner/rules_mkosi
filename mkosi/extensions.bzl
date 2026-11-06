"""Bazelmod extension for rules_mkosi toolchains."""

load(
    "//mkosi:qemu_versions.bzl",
    "OVMF_CODE_SHA256",
    "OVMF_INTEGRITY",
    "OVMF_SHA256",
    "OVMF_SHELL_SHA256",
    "OVMF_STRIP_PREFIX",
    "OVMF_URL",
    "OVMF_VARS_SHA256",
    "OVMF_VERSION",
    "QEMU_SYSTEM_INTEGRITY",
    "QEMU_SYSTEM_SHA256",
    "QEMU_SYSTEM_URL",
    "QEMU_VERSION",
    "SEABIOS_SHA256",
    "SEABIOS_VERSION",
)
load("//mkosi:versions.bzl", "DEFAULT_MKOSI_VERSION", "MKOSI_VERSIONS")
load("//mkosi/private:toolchains_repo.bzl", "mkosi_source_repo", "ovmf_repo", "seabios_repo", "toolchains_repo")

_QEMU_REPOSITORY_ATTRS = {
    "ovmf_code_sha256": OVMF_CODE_SHA256,
    "ovmf_integrity": OVMF_INTEGRITY,
    "ovmf_repo": "@mkosi_ovmf",
    "ovmf_sha256": OVMF_SHA256,
    "ovmf_shell_sha256": OVMF_SHELL_SHA256,
    "ovmf_source_url": OVMF_URL,
    "ovmf_vars_sha256": OVMF_VARS_SHA256,
    "ovmf_version": OVMF_VERSION,
    "qemu_img": "@qemu_img_prebuilt_linux_amd64//:qemu-img",
    "qemu_integrity": QEMU_SYSTEM_INTEGRITY,
    "qemu_sha256": QEMU_SYSTEM_SHA256,
    "qemu_source_url": QEMU_SYSTEM_URL,
    "qemu_system": "@qemu_system_bin_prebuilt_linux_amd64_x86_64_softmmu//:qemu-system-x86_64",
    "qemu_version": QEMU_VERSION,
    "seabios_repo": "@mkosi_seabios",
    "seabios_sha256": SEABIOS_SHA256,
    "seabios_version": SEABIOS_VERSION,
    "system_data": "@qemu_system_data_prebuilt_linux_amd64//:qemu-system-data",
}

_toolchain = tag_class(
    doc = """Selects the mkosi version of the `@mkosi_toolchains` repository.

The selected version is the root module's, or the default without one; a dependency module that requests another
version fails module resolution.""",
    attrs = {
        "name": attr.string(
            default = "mkosi",
            doc = "Logical toolchain name. Only the root module may override it.",
        ),
        "version": attr.string(
            default = DEFAULT_MKOSI_VERSION,
            doc = "mkosi version, one of: " + ", ".join(sorted(MKOSI_VERSIONS.keys())) + ".",
        ),
    },
)

def _unsupported_version(version):
    return struct(
        error = "Unsupported mkosi version {}. Supported versions: {}.".format(
            version,
            ", ".join(sorted(MKOSI_VERSIONS.keys())),
        ),
        version = None,
    )

def resolve_mkosi_version(root_version, dependency_versions):
    """Select a supported version and report any module-graph conflict.

    Args:
      root_version: Version explicitly requested by the root module, or None.
      dependency_versions: Versions requested by dependency modules.

    Returns:
      A struct containing selected version and an error message.
    """
    if root_version != None and root_version not in MKOSI_VERSIONS:
        return _unsupported_version(root_version)

    selected_version = root_version or DEFAULT_MKOSI_VERSION
    for version in dependency_versions:
        if version != selected_version:
            return struct(
                error = "Conflicting mkosi versions: root requests {}, dependency requests {}.".format(
                    selected_version,
                    version,
                ),
                version = None,
            )
    return struct(error = "", version = selected_version)

def resolve_mkosi_name(names):
    if len(names) > 1:
        return struct(error = "Only one mkosi toolchain may be configured.", name = None)
    return struct(error = "", name = names[0] if names else "mkosi")

def _requested_toolchains(module_ctx):
    """Returns the requested toolchain names, the root module's version or None, and the dependency versions."""
    names = []
    versions = []
    root_version = None
    for mod in module_ctx.modules:
        for toolchain in mod.tags.toolchain:
            if toolchain.name != "mkosi" and not mod.is_root:
                fail("Only the root module may override the mkosi toolchain name.")
            if toolchain.name not in names:
                names.append(toolchain.name)
            if mod.is_root:
                if root_version != None and root_version != toolchain.version:
                    fail("The root module may configure only one mkosi version.")
                root_version = toolchain.version
            elif toolchain.version not in versions:
                versions.append(toolchain.version)
    return names, root_version, versions

def _mkosi_impl(module_ctx):
    names, root_version, versions = _requested_toolchains(module_ctx)
    name_selection = resolve_mkosi_name(names)
    if name_selection.error:
        fail(name_selection.error)
    selection = resolve_mkosi_version(root_version, versions)
    if selection.error:
        fail(selection.error)
    release = MKOSI_VERSIONS[selection.version]
    mkosi_source_repo(
        name = "mkosi_source",
        source_url = release.source_url,
        source_sha256 = release.source_sha256,
        strip_prefix = release.strip_prefix,
    )
    ovmf_repo(
        name = "mkosi_ovmf",
        source_url = OVMF_URL,
        sha256 = OVMF_SHA256,
        strip_prefix = OVMF_STRIP_PREFIX,
    )
    seabios_repo(
        name = "mkosi_seabios",
        qemu_data = "@qemu_system_data_prebuilt_linux_amd64//:share/qemu",
    )
    toolchains_repo(
        name = "mkosi_toolchains",
        toolchain_name = name_selection.name,
        version = selection.version,
        source_repo = "@mkosi_source",
        source_url = release.source_url,
        source_sha256 = release.source_sha256,
        source_integrity = release.source_integrity,
        python_version = release.python_version,
        python_dependencies = release.python_dependencies,
        python_import_dependencies = release.python_import_dependencies,
        **_QEMU_REPOSITORY_ATTRS
    )
    return module_ctx.extension_metadata(reproducible = True)

mkosi = module_extension(
    implementation = _mkosi_impl,
    doc = """Creates `@mkosi_toolchains`: the pinned mkosi with its Python runtime, and QEMU, OVMF, and SeaBIOS.

rules_mkosi registers these toolchains itself. `@mkosi_toolchains` downloads nothing; mkosi, QEMU, and the firmware are
fetched only when a target uses one of these toolchains.""",
    tag_classes = {"toolchain": _toolchain},
    arch_dependent = False,
    os_dependent = False,
)
