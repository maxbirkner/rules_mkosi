"""OVMF adapter for the serial boot lifecycle."""

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

_SECURE_BOOT_CODE = Label("@mkosi_ovmf_secure_boot//:OVMF_CODE_4M.secboot.fd")
_SECURE_BOOT_VARS = Label("@mkosi_ovmf_secure_boot//:OVMF_VARS_4M.fd")

# QEMU rejects virtio-9p mount tags longer than 31 bytes.
_MAX_MOUNT_TAG_LENGTH = 31
_MOUNT_TAG_CHARACTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"

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

_HTTP_PATH_CHARACTERS = _MOUNT_TAG_CHARACTERS

def _http_shares(shares):
    """Validates http_shares and returns (URL path, files) pairs sorted by path."""
    validated = {}
    for target, path in shares.items():
        if not path or path.strip(_HTTP_PATH_CHARACTERS) or path in (".", ".."):
            fail("http_shares path %r must be letters, digits, '.', '_' or '-'" % path)
        if path in validated:
            fail("http_shares path %r is used more than once" % path)
        validated[path] = target[DefaultInfo].files.to_list()
        if not validated[path]:
            fail("http_shares key %s provides no files" % target.label)
    return sorted(validated.items())

def _firmware(ctx, qemu):
    """Returns the OVMF code and variable store files and the QEMU arguments that the firmware needs."""
    if (ctx.file.secure_boot_code == None) != (ctx.file.secure_boot_vars == None):
        fail("secure_boot_code and secure_boot_vars must be set together")
    if ctx.file.secure_boot_code == None:
        return qemu.ovmf_code, qemu.ovmf_vars, []

    # The Secure Boot firmware keeps its authenticated variables in SMM-protected flash.
    return ctx.file.secure_boot_code, ctx.file.secure_boot_vars, [
        "-machine",
        "smm=on",
        "-global",
        "driver=cfi.pflash01,property=secure,value=on",
    ]

def _shares(ctx):
    """Returns the boot_test.py configuration of read_only_shares and http_shares, and the files they expose."""
    shares = _read_only_shares(ctx.attr.read_only_shares)
    http_shares = _http_shares(ctx.attr.http_shares)
    config = {
        "http_shares": [
            {"files": [file.short_path for file in files], "path": path}
            for path, files in http_shares
        ],
        "read_only_shares": [
            {"directory": directory.short_path, "mount_tag": mount_tag}
            for directory, mount_tag in shares
        ],
    }
    return config, [directory for directory, _ in shares] + [file for _, files in http_shares for file in files]

def _qemu_ovmf_boot_config_impl(ctx):
    image = ctx.attr.image[MkosiImageInfo].raw_image
    if image == None:
        fail("image must provide MkosiImageInfo.raw_image for the OVMF raw-disk adapter")
    validate_lifecycle(ctx)
    if any([not marker for marker in ctx.attr.progress_markers]):
        fail("progress_markers must contain only nonempty markers")
    if ctx.attr.progress_markers and ctx.attr.expected_failure_marker:
        fail("progress_markers cannot be combined with expected_failure_marker")
    share_config, share_files = _shares(ctx)
    validate_deadlines(ctx)
    qemu = ctx.toolchains[QEMU_TOOLCHAIN_TYPE].qemu
    firmware_code, firmware_vars, firmware_args = _firmware(ctx, qemu)
    config = boot_config(ctx, qemu, image, firmware_args + [
        "-drive",
        "if=pflash,format=raw,readonly=on,file={firmware_code}",
        "-drive",
        "if=pflash,format=raw,file={firmware_vars}",
    ]) | share_config | {
        "allow_reboot": ctx.attr.allow_reboot,
        "expected_failure_marker": ctx.attr.expected_failure_marker,
        "firmware_code": firmware_code.short_path,
        "firmware_vars": firmware_vars.short_path,
        "progress_markers": ctx.attr.progress_markers,
        "stop_after_readiness": ctx.attr.stop_after_readiness,
    }
    return boot_config_outputs(
        ctx,
        qemu,
        config,
        image,
        firmware_files = [firmware_code, firmware_vars],
        extra_files = share_files,
    )

qemu_ovmf_boot_config = rule(
    implementation = _qemu_ovmf_boot_config_impl,
    attrs = BOOT_CONFIG_ATTRS | {
        "allow_reboot": attr.bool(
            doc = """Keep QEMU running across guest reboots instead of treating a reboot as an exit.

The image snapshot and the copied OVMF variables persist across reboots for the lifetime of the test.
""",
        ),
        "expected_failure_marker": attr.string(
            doc = "Exact serial marker that makes an intentionally failing boot pass before readiness.",
        ),
        "http_shares": attr.label_keyed_string_dict(
            allow_files = True,
            doc = """Targets whose files the guest can download from http://10.0.2.100/<path>/, keyed to their path.

The files of a directory appear at the top of its path. The guest gets a virtio network interface on QEMU's user
network, which reaches only this server; configure it with the static address 10.0.2.15/24 or DHCP.""",
        ),
        "progress_markers": attr.string_list(
            doc = "Exact serial markers that must appear in this order before readiness_marker.",
        ),
        "read_only_shares": attr.label_keyed_string_dict(
            allow_files = True,
            doc = "Directory targets exposed to the guest as read-only virtio-9p shares, keyed to their mount tags.",
        ),
        "secure_boot_code": attr.label(
            allow_single_file = True,
            doc = "Secure Boot capable OVMF code that replaces the toolchain's OVMF; needs secure_boot_vars.",
        ),
        "secure_boot_vars": attr.label(
            allow_single_file = True,
            doc = "Variable store template for secure_boot_code.",
        ),
        "stop_after_readiness": attr.bool(
            doc = "Terminate QEMU successfully as soon as readiness is observed.",
        ),
    },
    provides = [QemuBootConfigInfo],
    toolchains = [QEMU_TOOLCHAIN_TYPE],
)

def _secure_boot_firmware(secure_boot):
    """Returns the qemu_ovmf_boot_config attributes that select the Secure Boot firmware, which only then is fetched."""
    if not secure_boot:
        return {}
    return {"secure_boot_code": _SECURE_BOOT_CODE, "secure_boot_vars": _SECURE_BOOT_VARS}

_SHUTDOWN_MARKERS = [
    "systemd-shutdown[1]: Powering off.",
    "reboot: Power down",
]

def qemu_ovmf_boot_test(
        name,
        image,
        readiness_marker = "systemd[1]: Hostname set to <rules-mkosi-tracer>.",
        progress_markers = [],
        expected_failure_marker = "",
        stop_after_readiness = False,
        allow_reboot = False,
        read_only_shares = {},
        http_shares = {},
        secure_boot = False,
        shutdown_markers = _SHUTDOWN_MARKERS,
        machine_args = ["-machine", "q35", "-m", "512M"],
        accelerator = "auto",
        boot_timeout_seconds = 180,
        qmp_initialization_timeout_seconds = 15,
        shutdown_timeout_seconds = 30,
        diagnostic_bytes = 65536,
        timeout = "moderate",
        tags = []):
    """Boots an image with OVMF and checks its serial lifecycle markers.

    Multi-boot lifecycles, such as an A/B update followed by a reboot, set allow_reboot so that one QEMU process keeps
    the image snapshot and the firmware variables across guest reboots and list their ordered checkpoints in
    progress_markers; read_only_shares (virtio-9p) and http_shares (HTTP) expose update payloads to the guest.
    accelerator selects KVM with a TCG fallback (`auto`, the default) or forces TCG (`tcg`); the test log records it.
    secure_boot boots Debian's Secure Boot capable OVMF in Setup Mode on q35 instead; see docs/secure-boot.md.
    """
    boot_test(
        name = name,
        config_rule = qemu_ovmf_boot_config,
        timeout = timeout,
        tags = tags,
        image = image,
        readiness_marker = readiness_marker,
        progress_markers = progress_markers,
        expected_failure_marker = expected_failure_marker,
        stop_after_readiness = stop_after_readiness,
        allow_reboot = allow_reboot,
        read_only_shares = read_only_shares,
        http_shares = http_shares,
        shutdown_markers = shutdown_markers,
        machine_args = machine_args,
        accelerator = accelerator,
        boot_timeout_seconds = boot_timeout_seconds,
        qmp_initialization_timeout_seconds = qmp_initialization_timeout_seconds,
        shutdown_timeout_seconds = shutdown_timeout_seconds,
        diagnostic_bytes = diagnostic_bytes,
        **_secure_boot_firmware(secure_boot)
    )
