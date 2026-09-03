"""SeaBIOS adapter for the reusable serial boot lifecycle."""

load(":managed_python_test.bzl", "managed_python_test")
load(":mkosi_image.bzl", "MkosiImageInfo")
load(":qemu_ovmf_boot_test.bzl", "QemuOvmfBootConfigInfo")

_QEMU_TOOLCHAIN_TYPE = "//mkosi/toolchain:qemu_toolchain_type"
_TEST_TIMEOUT_SECONDS = {"short": 60, "moderate": 300, "long": 900}
_CLEANUP_MARGIN_SECONDS = 30

def _qemu_seabios_boot_config_impl(ctx):
    image = ctx.attr.image[MkosiImageInfo]
    if image.raw_image == None:
        fail("image must provide MkosiImageInfo.raw_image for the SeaBIOS raw-disk adapter")
    if image.firmware != "bios":
        fail("SeaBIOS boot tests require an image with firmware = \"bios\"")
    for value, message in (
        (ctx.attr.boot_timeout_seconds, "boot_timeout_seconds"),
        (ctx.attr.qmp_initialization_timeout_seconds, "qmp_initialization_timeout_seconds"),
        (ctx.attr.shutdown_timeout_seconds, "shutdown_timeout_seconds"),
        (ctx.attr.diagnostic_bytes, "diagnostic_bytes"),
    ):
        if value <= 0:
            fail(message + " must be positive")
    if not ctx.attr.readiness_marker:
        fail("readiness_marker must not be empty")
    if not ctx.attr.shutdown_markers or any([not marker for marker in ctx.attr.shutdown_markers]):
        fail("shutdown_markers must contain nonempty markers")
    if ctx.attr.test_timeout not in _TEST_TIMEOUT_SECONDS:
        fail("timeout must be short, moderate, or long; eternal is not supported")
    lifecycle_seconds = (
        ctx.attr.qmp_initialization_timeout_seconds +
        ctx.attr.boot_timeout_seconds +
        ctx.attr.shutdown_timeout_seconds +
        _CLEANUP_MARGIN_SECONDS
    )
    if lifecycle_seconds > _TEST_TIMEOUT_SECONDS[ctx.attr.test_timeout]:
        fail("boot lifecycle deadlines exceed the Bazel test timeout category")

    qemu = ctx.toolchains[_QEMU_TOOLCHAIN_TYPE].qemu
    output = ctx.actions.declare_file(ctx.label.name + ".json")
    config = {
        "boot_timeout_seconds": ctx.attr.boot_timeout_seconds,
        "diagnostic_bytes": ctx.attr.diagnostic_bytes,
        "disk_interface": "virtio",
        "firmware": qemu.seabios.short_path,
        "firmware_kind": "seabios",
        "image": image.raw_image.short_path,
        "kernel_preflight": ctx.executable._kernel_preflight.short_path,
        "qemu": qemu.qemu_files_to_run.executable.short_path,
        "qemu_args": ctx.attr.machine_args + [
            "-bios",
            "{firmware}",
            "-chardev",
            "file,id=firmware,path={firmware_log}",
            "-device",
            "isa-debugcon,iobase=0x402,chardev=firmware",
        ],
        "qmp_initialization_timeout_seconds": ctx.attr.qmp_initialization_timeout_seconds,
        "readiness_marker": ctx.attr.readiness_marker,
        "shutdown_markers": ctx.attr.shutdown_markers,
        "shutdown_timeout_seconds": ctx.attr.shutdown_timeout_seconds,
        "system_data": qemu.system_data_anchor.short_path,
        "test_timeout": ctx.attr.test_timeout,
    }
    ctx.actions.write(output = output, content = json.encode(config) + "\n")
    runfiles = ctx.runfiles(
        files = [
            image.raw_image,
            qemu.seabios,
            qemu.qemu_files_to_run.executable,
            qemu.system_data_anchor,
            ctx.executable._kernel_preflight,
        ],
        transitive_files = depset(transitive = [
            qemu.qemu_runfiles.files,
            qemu.system_data_files,
            ctx.attr._kernel_preflight[DefaultInfo].default_runfiles.files,
        ]),
    )
    return [
        DefaultInfo(files = depset([output]), runfiles = runfiles),
        QemuOvmfBootConfigInfo(
            test_timeout = ctx.attr.test_timeout,
            qmp_initialization_timeout_seconds = ctx.attr.qmp_initialization_timeout_seconds,
            boot_timeout_seconds = ctx.attr.boot_timeout_seconds,
            shutdown_timeout_seconds = ctx.attr.shutdown_timeout_seconds,
            cleanup_margin_seconds = _CLEANUP_MARGIN_SECONDS,
        ),
    ]

qemu_seabios_boot_config = rule(
    implementation = _qemu_seabios_boot_config_impl,
    attrs = {
        "image": attr.label(mandatory = True, providers = [MkosiImageInfo]),
        "readiness_marker": attr.string(mandatory = True),
        "shutdown_markers": attr.string_list(mandatory = True),
        "machine_args": attr.string_list(mandatory = True),
        "boot_timeout_seconds": attr.int(mandatory = True),
        "qmp_initialization_timeout_seconds": attr.int(mandatory = True),
        "shutdown_timeout_seconds": attr.int(mandatory = True),
        "diagnostic_bytes": attr.int(mandatory = True),
        "test_timeout": attr.string(default = "moderate"),
        "_kernel_preflight": attr.label(
            cfg = "exec",
            default = "//mkosi/private:kernel_preflight",
            executable = True,
        ),
    },
    toolchains = [_QEMU_TOOLCHAIN_TYPE],
)

def qemu_seabios_boot_test(
        name,
        image,
        readiness_marker = "systemd[1]: Hostname set to <rules-mkosi-bios>.",
        shutdown_markers = ["systemd-shutdown[1]: Powering off.", "reboot: Power down"],
        machine_args = ["-machine", "pc", "-m", "512M"],
        boot_timeout_seconds = 180,
        qmp_initialization_timeout_seconds = 15,
        shutdown_timeout_seconds = 30,
        diagnostic_bytes = 65536,
        timeout = "moderate",
        tags = []):
    """Boots a BIOS image with pinned SeaBIOS and verifies its serial lifecycle."""
    config_name = name + "_config"
    qemu_seabios_boot_config(
        name = config_name,
        image = image,
        readiness_marker = readiness_marker,
        shutdown_markers = shutdown_markers,
        machine_args = machine_args,
        boot_timeout_seconds = boot_timeout_seconds,
        qmp_initialization_timeout_seconds = qmp_initialization_timeout_seconds,
        shutdown_timeout_seconds = shutdown_timeout_seconds,
        diagnostic_bytes = diagnostic_bytes,
        test_timeout = timeout,
        tags = ["manual"],
    )
    managed_python_test(
        name = name,
        src = "@rules_mkosi//mkosi/private:boot_test.py",
        args = ["$(rootpath :{})".format(config_name)],
        data = [
            "@rules_mkosi//mkosi/private:boot_test.py",
            "@rules_mkosi//mkosi/private:diagnostics.py",
            ":{}".format(config_name),
        ],
        timeout = timeout,
        tags = tags,
    )
