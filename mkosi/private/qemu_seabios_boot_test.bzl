"""SeaBIOS adapter for the serial boot lifecycle."""

load(":mkosi_image.bzl", "MkosiImageInfo")
load(
    ":qemu_boot_test.bzl",
    "BOOT_CONFIG_ATTRS",
    "QEMU_TOOLCHAIN_TYPE",
    "QemuBootConfigInfo",
    "boot_config",
    "boot_config_outputs",
    "boot_test",
    "validate_deadlines",
    "validate_lifecycle",
)

def _qemu_seabios_boot_config_impl(ctx):
    image = ctx.attr.image[MkosiImageInfo]
    if image.raw_image == None:
        fail("image must provide MkosiImageInfo.raw_image for the SeaBIOS raw-disk adapter")
    if image.firmware != "bios":
        fail("SeaBIOS boot tests require an image with firmware = \"bios\"")
    validate_lifecycle(ctx)
    validate_deadlines(ctx)
    qemu = ctx.toolchains[QEMU_TOOLCHAIN_TYPE].qemu
    config = boot_config(ctx, qemu, image.raw_image, [
        "-bios",
        "{firmware}",
        "-chardev",
        "file,id=firmware,path={firmware_log}",
        "-device",
        "isa-debugcon,iobase=0x402,chardev=firmware",
    ]) | {
        "disk_interface": "virtio",
        "firmware": qemu.seabios.short_path,
        "firmware_kind": "seabios",
    }
    return boot_config_outputs(ctx, qemu, config, image.raw_image, firmware_files = [qemu.seabios])

qemu_seabios_boot_config = rule(
    implementation = _qemu_seabios_boot_config_impl,
    attrs = BOOT_CONFIG_ATTRS,
    provides = [QemuBootConfigInfo],
    toolchains = [QEMU_TOOLCHAIN_TYPE],
)

def qemu_seabios_boot_test(
        name,
        image,
        readiness_marker = "systemd[1]: Hostname set to <rules-mkosi-bios>.",
        shutdown_markers = ["systemd-shutdown[1]: Powering off.", "reboot: Power down"],
        machine_args = ["-machine", "pc", "-m", "512M"],
        accelerator = "auto",
        boot_timeout_seconds = 180,
        qmp_initialization_timeout_seconds = 15,
        shutdown_timeout_seconds = 60,
        diagnostic_bytes = 65536,
        timeout = "moderate",
        tags = []):
    """Boots a BIOS image with the pinned SeaBIOS and checks its serial lifecycle markers.

    accelerator selects KVM with a TCG fallback (`auto`, the default) or
    forces TCG (`tcg`).
    """
    boot_test(
        name = name,
        config_rule = qemu_seabios_boot_config,
        timeout = timeout,
        tags = tags,
        image = image,
        readiness_marker = readiness_marker,
        shutdown_markers = shutdown_markers,
        machine_args = machine_args,
        accelerator = accelerator,
        boot_timeout_seconds = boot_timeout_seconds,
        qmp_initialization_timeout_seconds = qmp_initialization_timeout_seconds,
        shutdown_timeout_seconds = shutdown_timeout_seconds,
        diagnostic_bytes = diagnostic_bytes,
    )
