"""SeaBIOS adapter for the serial boot lifecycle."""

load(":mkosi_image.bzl", "MkosiImageInfo")
load(
    ":qemu_boot_test.bzl",
    "QEMU_TOOLCHAIN_TYPE",
    "QemuBootConfigInfo",
    "adapter_attrs",
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
    doc = """Writes the configuration of a qemu_seabios_boot_test, which declares it as `<name>_config`.

Use it directly only to inspect the validated deadlines through QemuBootConfigInfo.""",
    attrs = adapter_attrs(
        readiness_marker = "systemd[1]: Hostname set to <rules-mkosi-bios>.",
        machine = "pc",
        shutdown_timeout_seconds = 60,
    ),
    provides = [QemuBootConfigInfo],
    toolchains = [QEMU_TOOLCHAIN_TYPE],
)

def qemu_seabios_boot_test(name, image, timeout = "moderate", tags = [], **kwargs):
    """Boots a BIOS image with the pinned SeaBIOS and checks its serial lifecycle markers.

    The test waits for readiness_marker on the serial console and then for the guest to power off by itself.

    Args:
      name: Name of the test. The configuration target is `<name>_config`.
      image: mkosi_image with `firmware = "bios"` to boot.
      timeout: Bazel timeout category of the test, passed to the configuration as test_timeout.
      tags: Tags of the test.
      **kwargs: Further attributes of qemu_seabios_boot_config, such as readiness_marker. `testonly` applies to the
        test; `visibility`, `target_compatible_with`, and `exec_compatible_with` apply to the test and its
        configuration. The configuration is always testonly, so the image may be testonly.
    """
    boot_test(
        name = name,
        config_rule = qemu_seabios_boot_config,
        timeout = timeout,
        tags = tags,
        image = image,
        **kwargs
    )
