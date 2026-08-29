"""Repository rule that exposes registered mkosi and QEMU toolchains."""

def _toolchains_repo_impl(repository_ctx):
    python_label = "@python_{}//:python3".format(
        repository_ctx.attr.python_version.replace(".", "_"),
    )
    repository_ctx.download_and_extract(
        url = repository_ctx.attr.source_url,
        sha256 = repository_ctx.attr.source_sha256,
        stripPrefix = repository_ctx.attr.strip_prefix,
    )
    repository_ctx.download_and_extract(
        url = repository_ctx.attr.ovmf_source_url,
        sha256 = repository_ctx.attr.ovmf_sha256,
        stripPrefix = repository_ctx.attr.ovmf_strip_prefix,
    )

    mkosi_build = '''load("@rules_mkosi//mkosi:toolchain.bzl", "mkosi_toolchain")
load("@rules_shell//shell:sh_binary.bzl", "sh_binary")

package(default_visibility = ["//visibility:public"])

genrule(
    name = "mkosi_launcher_script",
    outs = ["mkosi_launcher.sh"],
    srcs = glob(["mkosi/**/*.py", "mkosi/resources/**"]) + [
        {python_label_repr},
    ] + {python_dependencies},
    cmd = """cat > "$@" <<'EOF'
#!/bin/sh
set -eu
runfiles_root="$${{RUNFILES_DIR:-$$0.runfiles}}"
python_path="$(rootpath {python_label})"
main_path="$(rootpath mkosi/__main__.py)"
dependency_paths="$(locations {python_import_dependency})"
for dependency_path in $$dependency_paths
do
    case "$$dependency_path" in
        */pefile.py) break ;;
    esac
done
main_path="$${{main_path#../}}"
python_path="$${{python_path#external/}}"
main_path="$${{main_path#external/}}"
dependency_path="$${{dependency_path#../}}"
dependency_path="$${{dependency_path#external/}}"
PYTHONPATH="$$runfiles_root/$${{main_path%/mkosi/__main__.py}}:$$runfiles_root/$${{dependency_path%/pefile.py}}:$${{PYTHONPATH:-}}" \
export PYTHONPATH
python_executable="$$runfiles_root/$${{python_path#../}}"
main_executable="$$runfiles_root/$$main_path"
if [ "$$#" -ge 2 ] && [ "$$1" = "--write-version" ]; then
    version_file="$$2"
    "$$python_executable" "$$main_executable" --version > "$$version_file"
    exit 0
fi
exec "$$python_executable" "$$main_executable" "$$@"
EOF
chmod +x "$@"
""",
)

sh_binary(
    name = "mkosi_cli",
    srcs = [":mkosi_launcher_script"],
    data = glob(["mkosi/**/*.py", "mkosi/resources/**"]) + [
        {python_label_repr},
    ] + {python_dependencies},
)

alias(
    name = "mkosi",
    actual = ":mkosi_cli",
)

mkosi_toolchain(
    name = "mkosi_toolchain",
    toolchain_name = {toolchain_name},
    version = {version},
    source_url = {source_url},
    source_sha256 = {source_sha256},
    source_integrity = {source_integrity},
    python_version = {python_version},
    executable = ":mkosi_cli",
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
'''.format(
        toolchain_name = repr(repository_ctx.attr.toolchain_name),
        version = repr(repository_ctx.attr.version),
        source_url = repr(repository_ctx.attr.source_url),
        source_sha256 = repr(repository_ctx.attr.source_sha256),
        source_integrity = repr(repository_ctx.attr.source_integrity),
        python_version = repr(repository_ctx.attr.python_version),
        python_label = python_label,
        python_label_repr = repr(python_label),
        python_dependencies = repr(repository_ctx.attr.python_dependencies),
        python_import_dependency = repository_ctx.attr.python_import_dependencies[0],
    )

    qemu_build = '''load("@rules_mkosi//mkosi:defs.bzl", "qemu_executable", "qemu_ovmf_toolchain")

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
    ovmf_version = {ovmf_version},
    ovmf_source_url = {ovmf_source_url},
    ovmf_sha256 = {ovmf_sha256},
    ovmf_integrity = {ovmf_integrity},
    ovmf_code = ":ovmf_code",
    ovmf_vars = ":ovmf_vars",
)

filegroup(
    name = "ovmf_code",
    srcs = ["x64/code.fd"],
)

filegroup(
    name = "ovmf_vars",
    srcs = ["x64/vars.fd"],
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
'''.format(
        qemu_system = repr(repository_ctx.attr.qemu_system),
        qemu_img = repr(repository_ctx.attr.qemu_img),
        system_data = repr(repository_ctx.attr.system_data),
        qemu_version = repr(repository_ctx.attr.qemu_version),
        qemu_source_url = repr(repository_ctx.attr.qemu_source_url),
        qemu_sha256 = repr(repository_ctx.attr.qemu_sha256),
        qemu_integrity = repr(repository_ctx.attr.qemu_integrity),
        ovmf_version = repr(repository_ctx.attr.ovmf_version),
        ovmf_source_url = repr(repository_ctx.attr.ovmf_source_url),
        ovmf_sha256 = repr(repository_ctx.attr.ovmf_sha256),
        ovmf_integrity = repr(repository_ctx.attr.ovmf_integrity),
    )
    repository_ctx.file("BUILD.bazel", mkosi_build + qemu_build)

    if hasattr(repository_ctx, "repo_metadata"):
        return repository_ctx.repo_metadata(reproducible = True)
    return None

toolchains_repo = repository_rule(
    implementation = _toolchains_repo_impl,
    attrs = {
        "toolchain_name": attr.string(mandatory = True),
        "version": attr.string(mandatory = True),
        "source_url": attr.string(mandatory = True),
        "source_sha256": attr.string(mandatory = True),
        "source_integrity": attr.string(mandatory = True),
        "strip_prefix": attr.string(mandatory = True),
        "python_version": attr.string(mandatory = True),
        "python_dependencies": attr.string_list(),
        "python_import_dependencies": attr.string_list(mandatory = True),
        "qemu_system": attr.string(mandatory = True),
        "qemu_img": attr.string(mandatory = True),
        "system_data": attr.string(mandatory = True),
        "qemu_version": attr.string(mandatory = True),
        "qemu_source_url": attr.string(mandatory = True),
        "qemu_sha256": attr.string(mandatory = True),
        "qemu_integrity": attr.string(mandatory = True),
        "ovmf_version": attr.string(mandatory = True),
        "ovmf_source_url": attr.string(mandatory = True),
        "ovmf_sha256": attr.string(mandatory = True),
        "ovmf_integrity": attr.string(mandatory = True),
        "ovmf_strip_prefix": attr.string(mandatory = True),
    },
)
