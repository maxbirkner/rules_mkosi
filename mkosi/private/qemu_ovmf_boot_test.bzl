"""Reusable OVMF adapter for the generic serial boot lifecycle."""

load(":managed_python_test.bzl", "managed_python_test")

_QEMU_TOOLCHAIN_TYPE = "//mkosi/toolchain:qemu_toolchain_type"

def _qemu_ovmf_boot_config_impl(ctx):
    qemu = ctx.toolchains[_QEMU_TOOLCHAIN_TYPE].qemu
    output = ctx.actions.declare_file(ctx.label.name + ".json")
    config = {
        "boot_timeout_seconds": ctx.attr.boot_timeout_seconds,
        "diagnostic_bytes": ctx.attr.diagnostic_bytes,
        "firmware_code": qemu.ovmf_code.short_path,
        "firmware_vars": qemu.ovmf_vars.short_path,
        "image": ctx.file.image.short_path,
        "qemu_args": ctx.attr.machine_args + [
            "-drive",
            "if=pflash,format=raw,readonly=on,file={firmware_code}",
            "-drive",
            "if=pflash,format=raw,file={firmware_vars}",
        ],
        "qemu": qemu.qemu_files_to_run.executable.short_path,
        "qmp_initialization_timeout_seconds": ctx.attr.qmp_initialization_timeout_seconds,
        "readiness_marker": ctx.attr.readiness_marker,
        "shutdown_markers": ctx.attr.shutdown_markers,
        "shutdown_timeout_seconds": ctx.attr.shutdown_timeout_seconds,
        "system_data": qemu.system_data_anchor.short_path,
    }
    ctx.actions.write(
        output = output,
        content = json.encode(config) + "\n",
    )
    runfiles = ctx.runfiles(
        files = [
            ctx.file.image,
            qemu.ovmf_code,
            qemu.ovmf_vars,
            qemu.qemu_files_to_run.executable,
            qemu.system_data_anchor,
        ],
        transitive_files = depset(transitive = [
            qemu.qemu_runfiles.files,
            qemu.system_data_files,
        ]),
    )
    return [DefaultInfo(files = depset([output]), runfiles = runfiles)]

_qemu_ovmf_boot_config = rule(
    implementation = _qemu_ovmf_boot_config_impl,
    attrs = {
        "image": attr.label(
            allow_single_file = True,
            mandatory = True,
            doc = "Raw guest image to boot read-only through a snapshot.",
        ),
        "readiness_marker": attr.string(
            mandatory = True,
            doc = "Exact serial marker proving guest userspace readiness.",
        ),
        "shutdown_markers": attr.string_list(
            mandatory = True,
            doc = "Exact serial markers proving guest-initiated clean shutdown.",
        ),
        "machine_args": attr.string_list(
            mandatory = True,
            doc = "QEMU machine and memory arguments for the OVMF adapter.",
        ),
        "boot_timeout_seconds": attr.int(mandatory = True),
        "qmp_initialization_timeout_seconds": attr.int(mandatory = True),
        "shutdown_timeout_seconds": attr.int(mandatory = True),
        "diagnostic_bytes": attr.int(mandatory = True),
    },
    toolchains = [_QEMU_TOOLCHAIN_TYPE],
)

def qemu_ovmf_boot_test(
        name,
        image,
        readiness_marker = "systemd[1]: Hostname set to <rules-mkosi-tracer>.",
        shutdown_markers = [
            "systemd-shutdown[1]: Powering off.",
            "reboot: Power down",
        ],
        machine_args = ["-machine", "q35", "-m", "512M"],
        boot_timeout_seconds = 180,
        qmp_initialization_timeout_seconds = 15,
        shutdown_timeout_seconds = 30,
        diagnostic_bytes = 65536,
        tags = []):
    """Boots an image with OVMF and verifies exact serial lifecycle markers.

    The adapter owns only OVMF firmware and QEMU command construction. The
    serial state machine is firmware-neutral, allowing a future SeaBIOS
    adapter to reuse the same lifecycle and diagnostics.
    """
    config_name = name + "_config"
    _qemu_ovmf_boot_config(
        name = config_name,
        image = image,
        readiness_marker = readiness_marker,
        shutdown_markers = shutdown_markers,
        machine_args = machine_args,
        boot_timeout_seconds = boot_timeout_seconds,
        qmp_initialization_timeout_seconds = qmp_initialization_timeout_seconds,
        shutdown_timeout_seconds = shutdown_timeout_seconds,
        diagnostic_bytes = diagnostic_bytes,
        tags = ["manual"],
    )
    managed_python_test(
        name = name,
        src = "@rules_mkosi//mkosi/private:boot_test.py",
        args = ["$(rootpath :{})".format(config_name)],
        data = [
            "@rules_mkosi//mkosi/private:boot_test.py",
            ":{}".format(config_name),
        ],
        tags = tags,
    )
