"""Toolchain rule and provider for Bazel-managed QEMU and OVMF."""

MkosiQemuToolchainInfo = provider(
    doc = "Information used by tests to execute QEMU with OVMF.",
    fields = {
        "execution_cpu": "Execution CPU constraint.",
        "execution_os": "Execution operating system constraint.",
        "format_version": "String identifying the toolchain output contract.",
        "ovmf_code": "OVMF_CODE firmware artifact.",
        "ovmf_code_sha256": "SHA-256 hash of OVMF_CODE.fd.",
        "ovmf_integrity": "SRI integrity string of the OVMF artifact.",
        "ovmf_sha256": "SHA-256 integrity hash of the OVMF artifact.",
        "ovmf_shell": "UEFI shell executable used for readiness.",
        "ovmf_shell_sha256": "SHA-256 hash of shell.efi.",
        "ovmf_source_url": "Immutable OVMF artifact URL.",
        "ovmf_vars": "OVMF_VARS firmware artifact.",
        "ovmf_vars_sha256": "SHA-256 hash of OVMF_VARS.fd.",
        "ovmf_version": "Pinned OVMF release version.",
        "qemu_files_to_run": "FilesToRunProvider for the QEMU executable.",
        "qemu_img": "The qemu-img executable.",
        "qemu_integrity": "SRI integrity string of the QEMU system artifact.",
        "qemu_runfiles": "Runfiles needed by the QEMU executable.",
        "qemu_sha256": "SHA-256 integrity hash of the QEMU system artifact.",
        "qemu_source_url": "Immutable QEMU artifact URL.",
        "qemu_system": "The QEMU system executable.",
        "qemu_version": "Pinned QEMU prebuilt release version.",
        "seabios": "SeaBIOS x86 firmware artifact.",
        "seabios_sha256": "SHA-256 hash of the SeaBIOS artifact.",
        "seabios_version": "Pinned SeaBIOS build identifier.",
        "system_data_anchor": "The QEMU share/qemu data directory.",
        "system_data_files": "Files in the QEMU data directory.",
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
            doc = "The QEMU system emulator binary.",
        ),
        "system_data": attr.label(
            allow_files = True,
            cfg = "exec",
            mandatory = True,
            doc = "QEMU runtime data files.",
        ),
    },
    executable = True,
    doc = "Wraps a QEMU system emulator binary and its runtime data as an executable target.",
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

def _pinned_string(doc):
    return attr.string(mandatory = True, doc = doc)

def _pinned_file(doc):
    return attr.label(allow_single_file = True, cfg = "exec", mandatory = True, doc = doc)

qemu_ovmf_toolchain = rule(
    implementation = _qemu_ovmf_toolchain_impl,
    attrs = {
        "format_version": attr.string(
            default = "qemu-ovmf-v1",
            doc = "Output contract implemented by this toolchain.",
        ),
        "ovmf_code": _pinned_file("OVMF_CODE firmware."),
        "ovmf_code_sha256": _pinned_string("OVMF_CODE hash."),
        "ovmf_integrity": _pinned_string("OVMF SRI integrity."),
        "ovmf_sha256": _pinned_string("OVMF SHA-256 hash."),
        "ovmf_shell": _pinned_file("UEFI shell executable."),
        "ovmf_shell_sha256": _pinned_string("UEFI shell hash."),
        "ovmf_source_url": _pinned_string("Immutable OVMF URL."),
        "ovmf_vars": _pinned_file("OVMF_VARS firmware."),
        "ovmf_vars_sha256": _pinned_string("OVMF_VARS hash."),
        "ovmf_version": _pinned_string("Pinned OVMF version."),
        "qemu_img": _pinned_file("The qemu-img executable."),
        "qemu_integrity": _pinned_string("QEMU SRI integrity."),
        "qemu_sha256": _pinned_string("QEMU SHA-256 hash."),
        "qemu_source_url": _pinned_string("Immutable QEMU URL."),
        "qemu_system": attr.label(
            cfg = "exec",
            executable = True,
            mandatory = True,
            doc = "The qemu_executable target of the QEMU system emulator.",
        ),
        "qemu_version": _pinned_string("Pinned QEMU version."),
        "seabios": _pinned_file("Pinned SeaBIOS firmware."),
        "seabios_sha256": _pinned_string("SeaBIOS firmware hash."),
        "seabios_version": _pinned_string("Pinned SeaBIOS build identifier."),
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
    },
    doc = "Defines a Linux x86-64 QEMU and OVMF test toolchain.",
)
