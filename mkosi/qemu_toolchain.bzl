"""Toolchain rule and provider for Bazel-managed QEMU and OVMF."""

MkosiQemuToolchainInfo = provider(
    doc = "Information used by tests to execute QEMU with OVMF.",
    fields = {
        "format_version": "String identifying the toolchain output contract.",
        "execution_os": "Execution operating system constraint.",
        "execution_cpu": "Execution CPU constraint.",
        "qemu_version": "Pinned QEMU prebuilt release version.",
        "qemu_source_url": "Immutable QEMU artifact URL.",
        "qemu_sha256": "SHA-256 integrity hash of the QEMU system artifact.",
        "qemu_integrity": "SRI integrity string of the QEMU system artifact.",
        "qemu_system": "The QEMU system executable.",
        "qemu_files_to_run": "FilesToRunProvider for the QEMU executable.",
        "qemu_runfiles": "Runfiles needed by the QEMU executable.",
        "qemu_img": "The qemu-img executable.",
        "system_data_anchor": "The QEMU share/qemu data directory.",
        "system_data_files": "Files in the QEMU data directory.",
        "seabios_version": "Pinned SeaBIOS build identifier.",
        "seabios": "SeaBIOS x86 firmware artifact.",
        "seabios_sha256": "SHA-256 hash of the SeaBIOS artifact.",
        "ovmf_version": "Pinned OVMF release version.",
        "ovmf_source_url": "Immutable OVMF artifact URL.",
        "ovmf_sha256": "SHA-256 integrity hash of the OVMF artifact.",
        "ovmf_integrity": "SRI integrity string of the OVMF artifact.",
        "ovmf_code": "OVMF_CODE firmware artifact.",
        "ovmf_vars": "OVMF_VARS firmware artifact.",
        "ovmf_shell": "UEFI shell executable used for readiness.",
        "ovmf_code_sha256": "SHA-256 hash of OVMF_CODE.fd.",
        "ovmf_vars_sha256": "SHA-256 hash of OVMF_VARS.fd.",
        "ovmf_shell_sha256": "SHA-256 hash of shell.efi.",
    },
)

QemuExecutableInfo = provider(
    doc = "Underlying artifact for a wrapped QEMU executable.",
    fields = {"source": "The underlying QEMU executable artifact."},
)

def _qemu_executable_impl(ctx):
    executable = ctx.actions.declare_file(ctx.label.name)
    ctx.actions.symlink(
        output = executable,
        target_file = ctx.file.qemu,
        is_executable = True,
    )
    return [
        DefaultInfo(
            executable = executable,
            files = depset([executable]),
            runfiles = ctx.runfiles(
                files = [executable],
                transitive_files = depset(transitive = [
                    ctx.attr.qemu[DefaultInfo].default_runfiles.files,
                    ctx.attr.system_data[DefaultInfo].default_runfiles.files,
                ]),
            ),
        ),
        QemuExecutableInfo(source = ctx.file.qemu),
    ]

qemu_executable = rule(
    implementation = _qemu_executable_impl,
    attrs = {
        "qemu": attr.label(
            allow_single_file = True,
            cfg = "exec",
            mandatory = True,
        ),
        "system_data": attr.label(
            allow_files = True,
            cfg = "exec",
            mandatory = True,
        ),
    },
    executable = True,
)

def _qemu_ovmf_toolchain_impl(ctx):
    qemu = ctx.attr.qemu_system[DefaultInfo]
    qemu_system = ctx.attr.qemu_system[QemuExecutableInfo].source
    info = MkosiQemuToolchainInfo(
        format_version = ctx.attr.format_version,
        execution_os = "linux",
        execution_cpu = "x86_64",
        qemu_version = ctx.attr.qemu_version,
        qemu_source_url = ctx.attr.qemu_source_url,
        qemu_sha256 = ctx.attr.qemu_sha256,
        qemu_integrity = ctx.attr.qemu_integrity,
        qemu_system = qemu_system,
        qemu_files_to_run = qemu.files_to_run,
        qemu_runfiles = qemu.default_runfiles,
        qemu_img = ctx.file.qemu_img,
        system_data_anchor = ctx.files.system_data_anchor[0],
        system_data_files = depset(ctx.files.system_data),
        seabios_version = ctx.attr.seabios_version,
        seabios = ctx.file.seabios,
        seabios_sha256 = ctx.attr.seabios_sha256,
        ovmf_version = ctx.attr.ovmf_version,
        ovmf_source_url = ctx.attr.ovmf_source_url,
        ovmf_sha256 = ctx.attr.ovmf_sha256,
        ovmf_integrity = ctx.attr.ovmf_integrity,
        ovmf_code = ctx.file.ovmf_code,
        ovmf_vars = ctx.file.ovmf_vars,
        ovmf_shell = ctx.file.ovmf_shell,
        ovmf_code_sha256 = ctx.attr.ovmf_code_sha256,
        ovmf_vars_sha256 = ctx.attr.ovmf_vars_sha256,
        ovmf_shell_sha256 = ctx.attr.ovmf_shell_sha256,
    )
    return [
        platform_common.ToolchainInfo(qemu = info),
        info,
    ]

qemu_ovmf_toolchain = rule(
    implementation = _qemu_ovmf_toolchain_impl,
    attrs = {
        "format_version": attr.string(
            default = "qemu-ovmf-v1",
            doc = "Output contract implemented by this toolchain.",
        ),
        "qemu_version": attr.string(mandatory = True, doc = "Pinned QEMU version."),
        "qemu_source_url": attr.string(mandatory = True, doc = "Immutable QEMU URL."),
        "qemu_sha256": attr.string(mandatory = True, doc = "QEMU SHA-256 hash."),
        "qemu_integrity": attr.string(mandatory = True, doc = "QEMU SRI integrity."),
        "qemu_system": attr.label(
            cfg = "exec",
            executable = True,
            mandatory = True,
            doc = "The QEMU system executable target.",
        ),
        "qemu_img": attr.label(
            allow_single_file = True,
            cfg = "exec",
            mandatory = True,
            doc = "The qemu-img executable.",
        ),
        "system_data": attr.label(
            allow_files = True,
            cfg = "exec",
            mandatory = True,
            doc = "QEMU runtime data files.",
        ),
        "system_data_anchor": attr.label(
            allow_files = True,
            cfg = "exec",
            mandatory = True,
            doc = "QEMU runtime data directory.",
        ),
        "seabios_version": attr.string(mandatory = True, doc = "Pinned SeaBIOS build identifier."),
        "seabios": attr.label(
            allow_single_file = True,
            cfg = "exec",
            mandatory = True,
            doc = "Pinned SeaBIOS firmware.",
        ),
        "seabios_sha256": attr.string(mandatory = True, doc = "SeaBIOS firmware hash."),
        "ovmf_version": attr.string(mandatory = True, doc = "Pinned OVMF version."),
        "ovmf_source_url": attr.string(mandatory = True, doc = "Immutable OVMF URL."),
        "ovmf_sha256": attr.string(mandatory = True, doc = "OVMF SHA-256 hash."),
        "ovmf_integrity": attr.string(mandatory = True, doc = "OVMF SRI integrity."),
        "ovmf_code": attr.label(
            allow_single_file = True,
            cfg = "exec",
            mandatory = True,
            doc = "OVMF_CODE firmware.",
        ),
        "ovmf_vars": attr.label(
            allow_single_file = True,
            cfg = "exec",
            mandatory = True,
            doc = "OVMF_VARS firmware.",
        ),
        "ovmf_shell": attr.label(
            allow_single_file = True,
            cfg = "exec",
            mandatory = True,
            doc = "UEFI shell executable.",
        ),
        "ovmf_code_sha256": attr.string(mandatory = True, doc = "OVMF_CODE hash."),
        "ovmf_vars_sha256": attr.string(mandatory = True, doc = "OVMF_VARS hash."),
        "ovmf_shell_sha256": attr.string(mandatory = True, doc = "UEFI shell hash."),
    },
    doc = "Defines a Linux x86-64 QEMU and OVMF test toolchain.",
)
