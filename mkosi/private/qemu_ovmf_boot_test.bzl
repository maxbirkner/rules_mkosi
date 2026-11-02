"""Reusable OVMF adapter for the generic serial boot lifecycle."""

load(":managed_python_test.bzl", "managed_python_test")
load(":mkosi_image.bzl", "MkosiImageInfo")
load(":qemu_accelerator.bzl", "QEMU_ACCELERATOR_DOC", "qemu_accelerator_args")

_QEMU_TOOLCHAIN_TYPE = "//mkosi/toolchain:qemu_toolchain_type"
_TEST_TIMEOUT_SECONDS = {
    "short": 60,
    "moderate": 300,
    "long": 900,
}
_CLEANUP_MARGIN_SECONDS = 30

# QEMU rejects virtio-9p mount tags longer than 31 bytes.
_MAX_MOUNT_TAG_LENGTH = 31
_MOUNT_TAG_CHARACTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"

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

def _read_only_shares(shares):
    """Validates read_only_shares and returns (directory, mount tag) pairs sorted by tag."""
    validated = []
    tags = {}
    for target, mount_tag in shares.items():
        files = target[DefaultInfo].files.to_list()
        if len(files) != 1 or not files[0].is_directory:
            fail("read_only_shares key %s must provide exactly one directory" % target.label)
        if (not mount_tag or len(mount_tag) > _MAX_MOUNT_TAG_LENGTH or
            mount_tag.strip(_MOUNT_TAG_CHARACTERS)):
            fail(
                ("read_only_shares mount tag %r must be 1 to %d letters, digits, " +
                 "'.', '_' or '-'") % (mount_tag, _MAX_MOUNT_TAG_LENGTH),
            )
        if mount_tag in tags:
            fail("read_only_shares mount tag %r is used more than once" % mount_tag)
        tags[mount_tag] = True
        validated.append((mount_tag, files[0]))
    return [(directory, mount_tag) for mount_tag, directory in sorted(validated)]

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
    if any([not marker for marker in ctx.attr.progress_markers]):
        fail("progress_markers must contain only nonempty markers")
    if ctx.attr.progress_markers and ctx.attr.expected_failure_marker:
        fail("progress_markers cannot be combined with expected_failure_marker")
    shares = _read_only_shares(ctx.attr.read_only_shares)
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
        "accelerator_args": qemu_accelerator_args(ctx.attr.accelerator),
        "boot_timeout_seconds": ctx.attr.boot_timeout_seconds,
        "diagnostic_bytes": ctx.attr.diagnostic_bytes,
        "firmware_code": qemu.ovmf_code.short_path,
        "firmware_vars": qemu.ovmf_vars.short_path,
        "image": image.short_path,
        "kernel_preflight": ctx.executable._kernel_preflight.short_path,
        "qemu_args": ctx.attr.machine_args + [
            "-drive",
            "if=pflash,format=raw,readonly=on,file={firmware_code}",
            "-drive",
            "if=pflash,format=raw,file={firmware_vars}",
        ],
        "qemu": qemu.qemu_files_to_run.executable.short_path,
        "qmp_initialization_timeout_seconds": ctx.attr.qmp_initialization_timeout_seconds,
        "readiness_marker": ctx.attr.readiness_marker,
        "progress_markers": ctx.attr.progress_markers,
        "expected_failure_marker": ctx.attr.expected_failure_marker,
        "stop_after_readiness": ctx.attr.stop_after_readiness,
        "allow_reboot": ctx.attr.allow_reboot,
        "read_only_shares": [
            {"directory": directory.short_path, "mount_tag": mount_tag}
            for directory, mount_tag in shares
        ],
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
            ctx.executable._kernel_preflight,
        ] + [directory for directory, _ in shares],
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

qemu_ovmf_boot_config = rule(
    implementation = _qemu_ovmf_boot_config_impl,
    attrs = {
        "accelerator": attr.string(
            default = "auto",
            doc = QEMU_ACCELERATOR_DOC,
        ),
        "image": attr.label(
            mandatory = True,
            providers = [MkosiImageInfo],
            doc = "mkosi_image target whose MkosiImageInfo.raw_image is booted read-only through a snapshot.",
        ),
        "readiness_marker": attr.string(
            mandatory = True,
            doc = "Exact serial marker proving guest userspace readiness.",
        ),
        "progress_markers": attr.string_list(
            doc = "Exact serial markers that must appear in this order before readiness_marker.",
        ),
        "expected_failure_marker": attr.string(
            doc = "Exact serial marker that makes an intentional negative boot pass before readiness.",
        ),
        "allow_reboot": attr.bool(
            doc = """Keep QEMU running across guest reboots instead of treating a reboot as an exit.

The image snapshot and the copied OVMF variables persist across reboots for the lifetime of the test.
""",
        ),
        "read_only_shares": attr.label_keyed_string_dict(
            allow_files = True,
            doc = "Directory targets exposed to the guest as read-only virtio-9p shares, keyed to their mount tags.",
        ),
        "stop_after_readiness": attr.bool(
            doc = "Terminate QEMU successfully as soon as readiness is observed.",
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
        "_kernel_preflight": attr.label(
            cfg = "exec",
            default = "//mkosi/private:kernel_preflight",
            executable = True,
        ),
    },
    toolchains = [_QEMU_TOOLCHAIN_TYPE],
)

def qemu_ovmf_boot_test(
        name,
        image,
        readiness_marker = "systemd[1]: Hostname set to <rules-mkosi-tracer>.",
        progress_markers = [],
        expected_failure_marker = "",
        stop_after_readiness = False,
        allow_reboot = False,
        read_only_shares = {},
        shutdown_markers = [
            "systemd-shutdown[1]: Powering off.",
            "reboot: Power down",
        ],
        machine_args = ["-machine", "q35", "-m", "512M"],
        accelerator = "auto",
        boot_timeout_seconds = 180,
        qmp_initialization_timeout_seconds = 15,
        shutdown_timeout_seconds = 30,
        diagnostic_bytes = 65536,
        timeout = "moderate",
        tags = []):
    """Boots an image with OVMF and verifies exact serial lifecycle markers.

    The adapter owns only OVMF firmware and QEMU command construction. The
    serial state machine is firmware-neutral and is also used by the SeaBIOS
    adapter.

    Multi-boot lifecycles, such as an A/B update followed by a reboot, set
    allow_reboot so that one QEMU process keeps the writable image snapshot
    and firmware variables across guest reboots, list their ordered
    checkpoints in progress_markers, and may expose directory artifacts such
    as update payloads through read_only_shares.

    accelerator selects KVM with a TCG fallback (`auto`, the default) or
    forces TCG (`tcg`); the accelerator QEMU actually used is recorded in the
    test log and boot evidence.
    """
    config_name = name + "_config"
    qemu_ovmf_boot_config(
        name = config_name,
        image = image,
        readiness_marker = readiness_marker,
        progress_markers = progress_markers,
        expected_failure_marker = expected_failure_marker,
        stop_after_readiness = stop_after_readiness,
        allow_reboot = allow_reboot,
        read_only_shares = read_only_shares,
        shutdown_markers = shutdown_markers,
        machine_args = machine_args,
        accelerator = accelerator,
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
