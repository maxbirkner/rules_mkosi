"""Reusable OVMF adapter for the generic serial boot lifecycle."""

load(":managed_python_test.bzl", "managed_python_test")
load(":mkosi_image.bzl", "MkosiImageInfo")

_QEMU_TOOLCHAIN_TYPE = "//mkosi/toolchain:qemu_toolchain_type"
_TEST_TIMEOUT_SECONDS = {
    "short": 60,
    "moderate": 300,
    "long": 900,
}
_CLEANUP_MARGIN_SECONDS = 30

QemuOvmfBootConfigInfo = provider(
    "Validated lifecycle deadlines and Bazel timeout category.",
    fields = [
        "test_timeout",
        "qmp_initialization_timeout_seconds",
        "boot_timeout_seconds",
        "shutdown_timeout_seconds",
        "cleanup_margin_seconds",
    ],
)

def _qemu_ovmf_boot_config_impl(ctx):
    image = ctx.attr.image[MkosiImageInfo].raw_image
    if image == None:
        fail("image must provide MkosiImageInfo.raw_image for the OVMF raw-disk adapter")
    if ctx.attr.boot_timeout_seconds <= 0:
        fail("boot_timeout_seconds must be positive")
    if ctx.attr.qmp_initialization_timeout_seconds <= 0:
        fail("qmp_initialization_timeout_seconds must be positive")
    if ctx.attr.shutdown_timeout_seconds <= 0:
        fail("shutdown_timeout_seconds must be positive")
    if ctx.attr.diagnostic_bytes <= 0:
        fail("diagnostic_bytes must be positive")
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
        fail(
            ("boot lifecycle deadlines (%d seconds including cleanup margin) " +
             "exceed the %s test timeout category (%d seconds)") % (
                lifecycle_seconds,
                ctx.attr.test_timeout,
                _TEST_TIMEOUT_SECONDS[ctx.attr.test_timeout],
            ),
        )
    qemu = ctx.toolchains[_QEMU_TOOLCHAIN_TYPE].qemu
    output = ctx.actions.declare_file(ctx.label.name + ".json")
    config = {
        "boot_timeout_seconds": ctx.attr.boot_timeout_seconds,
        "diagnostic_bytes": ctx.attr.diagnostic_bytes,
        "firmware_code": qemu.ovmf_code.short_path,
        "firmware_vars": qemu.ovmf_vars.short_path,
        "image": image.short_path,
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
        "test_timeout": ctx.attr.test_timeout,
    }
    ctx.actions.write(
        output = output,
        content = json.encode(config) + "\n",
    )
    runfiles = ctx.runfiles(
        files = [
            image,
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

qemu_ovmf_boot_config = rule(
    implementation = _qemu_ovmf_boot_config_impl,
    attrs = {
        "image": attr.label(
            mandatory = True,
            providers = [MkosiImageInfo],
            doc = "mkosi_image target whose MkosiImageInfo.raw_image is booted read-only through a snapshot.",
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
        "test_timeout": attr.string(default = "moderate"),
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
        timeout = "moderate",
        tags = []):
    """Boots an image with OVMF and verifies exact serial lifecycle markers.

    The adapter owns only OVMF firmware and QEMU command construction. The
    serial state machine is firmware-neutral, allowing a future SeaBIOS
    adapter to reuse the same lifecycle and diagnostics.
    """
    config_name = name + "_config"
    qemu_ovmf_boot_config(
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
            ":{}".format(config_name),
        ],
        timeout = timeout,
        tags = tags,
    )
