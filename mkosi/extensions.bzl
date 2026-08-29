"""Bazelmod extension for rules_mkosi toolchains."""

load("//mkosi:versions.bzl", "DEFAULT_MKOSI_VERSION", "MKOSI_VERSIONS")
load("//mkosi/private:toolchains_repo.bzl", "toolchains_repo")

_toolchain = tag_class(
    attrs = {
        "name": attr.string(
            default = "mkosi",
            doc = "Logical toolchain name. Only the root module may override it.",
        ),
        "version": attr.string(
            default = DEFAULT_MKOSI_VERSION,
            doc = "mkosi version from the supported pinned-version table.",
        ),
    },
)

def resolve_mkosi_version(root_version, dependency_versions):
    """Select a supported version and report any module-graph conflict.

    Args:
      root_version: Version explicitly requested by the root module, or None.
      dependency_versions: Versions requested by dependency modules.

    Returns:
      A struct containing selected version and an error message.
    """
    requested_versions = [version for version in dependency_versions]
    if root_version != None:
        requested_versions.append(root_version)

    for version in requested_versions:
        if version not in MKOSI_VERSIONS:
            return struct(
                error = "Unsupported mkosi version {}. Supported versions: {}.".format(
                    version,
                    ", ".join(sorted(MKOSI_VERSIONS.keys())),
                ),
                version = None,
            )

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

def _mkosi_impl(module_ctx):
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

    name_selection = resolve_mkosi_name(names)
    if name_selection.error:
        fail(name_selection.error)

    selection = resolve_mkosi_version(root_version, versions)
    if selection.error:
        fail(selection.error)
    selected_version = selection.version
    release = MKOSI_VERSIONS[selected_version]
    toolchains_repo(
        name = "mkosi_toolchains",
        toolchain_name = name_selection.name,
        version = selected_version,
        source_url = release.source_url,
        source_sha256 = release.source_sha256,
        source_integrity = release.source_integrity,
        strip_prefix = release.strip_prefix,
        python_version = release.python_version,
        python_dependencies = release.python_dependencies,
        python_import_dependencies = release.python_import_dependencies,
    )

    return module_ctx.extension_metadata(reproducible = True)

mkosi = module_extension(
    implementation = _mkosi_impl,
    tag_classes = {"toolchain": _toolchain},
    arch_dependent = False,
    os_dependent = False,
)
