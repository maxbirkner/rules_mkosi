"""Repository rule that exposes registered mkosi and QEMU toolchains."""

_MKOSI_BUILD = '''load("@rules_mkosi//mkosi:toolchain.bzl", "managed_python_tool", "mkosi_toolchain")

package(default_visibility = ["//visibility:public"])

managed_python_tool(
    name = "mkosi_python",
    python_version = {python_version},
)

filegroup(
    name = "mkosi_runfiles",
    srcs = glob(["mkosi/**/*.py", "mkosi/resources/**"]) + [
        ":mkosi_python",
    ] + {python_dependencies},
)

filegroup(
    name = "mkosi_script",
    srcs = ["mkosi/__main__.py"],
)

filegroup(
    name = "mkosi_runtime",
    srcs = [":mkosi_python"],
)

mkosi_toolchain(
    name = "mkosi_toolchain",
    toolchain_name = {toolchain_name},
    version = {version},
    source_url = {source_url},
    source_sha256 = {source_sha256},
    source_integrity = {source_integrity},
    python_version = {python_version},
    python = ":mkosi_python",
    script = "mkosi/__main__.py",
    python_dependency = {python_import_dependency_repr},
    runfiles = ":mkosi_runfiles",
)

toolchain(
    name = "linux_x86_64",
    exec_compatible_with = [
        "@platforms//os:linux",
        "@platforms//cpu:x86_64",
    ],
    toolchain = ":mkosi_toolchain",
    toolchain_type = "@rules_mkosi//mkosi/toolchain:toolchain_type",
)
'''

_QEMU_BUILD = '''load("@rules_mkosi//mkosi:defs.bzl", "qemu_executable", "qemu_ovmf_toolchain")

qemu_executable(
    name = "qemu_system_executable",
    qemu = {qemu_system},
    system_data = {system_data},
)

qemu_ovmf_toolchain(
    name = "qemu_ovmf_toolchain",
    qemu_version = {qemu_version},
    qemu_source_url = {qemu_source_url},
    qemu_sha256 = {qemu_sha256},
    qemu_integrity = {qemu_integrity},
    qemu_system = ":qemu_system_executable",
    qemu_img = {qemu_img},
    system_data = {system_data},
    system_data_anchor = {system_data},
    seabios_version = {seabios_version},
    seabios = ":seabios",
    seabios_sha256 = {seabios_sha256},
    ovmf_version = {ovmf_version},
    ovmf_source_url = {ovmf_source_url},
    ovmf_sha256 = {ovmf_sha256},
    ovmf_integrity = {ovmf_integrity},
    ovmf_code = ":ovmf_code",
    ovmf_vars = ":ovmf_vars",
    ovmf_shell = ":ovmf_shell",
    ovmf_code_sha256 = {ovmf_code_sha256},
    ovmf_vars_sha256 = {ovmf_vars_sha256},
    ovmf_shell_sha256 = {ovmf_shell_sha256},
)

filegroup(
    name = "seabios",
    srcs = ["seabios.bin"],
)

filegroup(
    name = "ovmf_code",
    srcs = ["x64/code.fd"],
)

filegroup(
    name = "ovmf_vars",
    srcs = ["x64/vars.fd"],
)

filegroup(
    name = "ovmf_shell",
    srcs = ["x64/shell.efi"],
)

toolchain(
    name = "qemu_linux_x86_64",
    exec_compatible_with = [
        "@platforms//os:linux",
        "@platforms//cpu:x86_64",
    ],
    toolchain = ":qemu_ovmf_toolchain",
    toolchain_type = "@rules_mkosi//mkosi/toolchain:qemu_toolchain_type",
)
'''

_MKOSI_BUILD_ATTRS = [
    "toolchain_name",
    "version",
    "source_url",
    "source_sha256",
    "source_integrity",
    "python_version",
    "python_dependencies",
]

_QEMU_BUILD_ATTRS = [
    "qemu_system",
    "qemu_img",
    "system_data",
    "seabios_version",
    "seabios_sha256",
    "qemu_version",
    "qemu_source_url",
    "qemu_sha256",
    "qemu_integrity",
    "ovmf_version",
    "ovmf_source_url",
    "ovmf_sha256",
    "ovmf_integrity",
    "ovmf_code_sha256",
    "ovmf_vars_sha256",
    "ovmf_shell_sha256",
]

def _repr_attrs(attrs, names):
    return {name: repr(getattr(attrs, name)) for name in names}

def _fetch_sources(repository_ctx):
    attrs = repository_ctx.attr
    repository_ctx.download_and_extract(
        url = attrs.source_url,
        sha256 = attrs.source_sha256,
        stripPrefix = attrs.strip_prefix,
    )
    repository_ctx.symlink(
        repository_ctx.path(attrs.seabios_source).get_child("bios-256k.bin"),
        "seabios.bin",
    )
    repository_ctx.download_and_extract(
        url = attrs.ovmf_source_url,
        sha256 = attrs.ovmf_sha256,
        stripPrefix = attrs.ovmf_strip_prefix,
    )

def _toolchains_repo_impl(repository_ctx):
    attrs = repository_ctx.attr
    _fetch_sources(repository_ctx)
    mkosi_build = _MKOSI_BUILD.format(
        python_import_dependency_repr = repr(attrs.python_import_dependencies[0]),
        **_repr_attrs(attrs, _MKOSI_BUILD_ATTRS)
    )
    qemu_build = _QEMU_BUILD.format(**_repr_attrs(attrs, _QEMU_BUILD_ATTRS))
    repository_ctx.file("BUILD.bazel", mkosi_build + qemu_build)

    if hasattr(repository_ctx, "repo_metadata"):
        return repository_ctx.repo_metadata(reproducible = True)
    return None

toolchains_repo = repository_rule(
    implementation = _toolchains_repo_impl,
    attrs = {
        "ovmf_code_sha256": attr.string(mandatory = True),
        "ovmf_integrity": attr.string(mandatory = True),
        "ovmf_sha256": attr.string(mandatory = True),
        "ovmf_shell_sha256": attr.string(mandatory = True),
        "ovmf_source_url": attr.string(mandatory = True),
        "ovmf_strip_prefix": attr.string(mandatory = True),
        "ovmf_vars_sha256": attr.string(mandatory = True),
        "ovmf_version": attr.string(mandatory = True),
        "python_dependencies": attr.string_list(),
        "python_import_dependencies": attr.string_list(mandatory = True),
        "python_version": attr.string(mandatory = True),
        "qemu_img": attr.string(mandatory = True),
        "qemu_integrity": attr.string(mandatory = True),
        "qemu_sha256": attr.string(mandatory = True),
        "qemu_source_url": attr.string(mandatory = True),
        "qemu_system": attr.string(mandatory = True),
        "qemu_version": attr.string(mandatory = True),
        "seabios_sha256": attr.string(mandatory = True),
        "seabios_source": attr.label(mandatory = True),
        "seabios_version": attr.string(mandatory = True),
        "source_integrity": attr.string(mandatory = True),
        "source_sha256": attr.string(mandatory = True),
        "source_url": attr.string(mandatory = True),
        "strip_prefix": attr.string(mandatory = True),
        "system_data": attr.string(mandatory = True),
        "toolchain_name": attr.string(mandatory = True),
        "version": attr.string(mandatory = True),
    },
)
