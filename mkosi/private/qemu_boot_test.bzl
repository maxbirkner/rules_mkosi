"""Shared parts of the QEMU firmware adapters for the serial boot lifecycle in boot_test.py."""

load(":managed_python_test.bzl", "managed_python_test")
load(":mkosi_image.bzl", "MkosiImageInfo")
load(":qemu_accelerator.bzl", "QEMU_ACCELERATOR_DOC", "qemu_accelerator_args")

QEMU_TOOLCHAIN_TYPE = "//mkosi/toolchain:qemu_toolchain_type"

_TEST_TIMEOUT_SECONDS = {
    "long": 900,
    "moderate": 300,
    "short": 60,
}
_CLEANUP_MARGIN_SECONDS = 30

QemuBootConfigInfo = provider(
    "Validated lifecycle deadlines of a QEMU boot test configuration.",
    fields = {
        "boot_timeout_seconds": "Deadline for the readiness marker.",
        "cleanup_margin_seconds": "Time reserved within the test timeout for cleanup.",
        "qmp_initialization_timeout_seconds": "Deadline for QMP to become ready.",
        "shutdown_timeout_seconds": "Deadline for the clean shutdown.",
        "test_timeout": "Bazel test timeout category.",
    },
)

_SHUTDOWN_MARKERS = [
    "systemd-shutdown[1]: Powering off.",
    "reboot: Power down",
]

# Attributes of every firmware adapter; the adapters add readiness_marker, machine_args and shutdown_timeout_seconds
# with their own defaults.
BOOT_CONFIG_ATTRS = {
    "accelerator": attr.string(
        default = "auto",
        doc = QEMU_ACCELERATOR_DOC,
    ),
    "boot_timeout_seconds": attr.int(
        default = 180,
        doc = "Seconds that QEMU may take after QMP is ready until readiness_marker appears on the serial console.",
    ),
    "diagnostic_bytes": attr.int(
        default = 65536,
        doc = "Bytes of the end of each log printed on failure; the retained test outputs are capped at 256 KiB.",
    ),
    "image": attr.label(
        mandatory = True,
        providers = [MkosiImageInfo],
        doc = "mkosi_image whose raw_image is booted through a QEMU snapshot, leaving the image unchanged.",
    ),
    "qmp_initialization_timeout_seconds": attr.int(
        default = 15,
        doc = "Seconds that QEMU may take to accept QMP connections.",
    ),
    "shutdown_markers": attr.string_list(
        default = _SHUTDOWN_MARKERS,
        doc = "Exact serial markers proving guest-initiated clean shutdown; one of them must appear.",
    ),
    "test_timeout": attr.string(
        default = "moderate",
        doc = """Bazel timeout category of the test: `short`, `moderate`, or `long`.

The QMP, boot and shutdown deadlines plus a 30 second cleanup margin must fit it (60, 300, or 900 seconds).""",
    ),
    "_kernel_preflight": attr.label(
        cfg = "exec",
        default = "//mkosi/private:kernel_preflight",
        executable = True,
    ),
}

def adapter_attrs(readiness_marker, machine, shutdown_timeout_seconds):
    """Returns the BOOT_CONFIG_ATTRS whose defaults differ between the firmware adapters.

    Args:
      readiness_marker: Default readiness_marker.
      machine: Default QEMU machine type.
      shutdown_timeout_seconds: Default shutdown_timeout_seconds.
    """
    return BOOT_CONFIG_ATTRS | {
        "machine_args": attr.string_list(
            default = ["-machine", machine, "-m", "512M"],
            doc = "QEMU machine and memory arguments.",
        ),
        "readiness_marker": attr.string(
            default = readiness_marker,
            doc = """Exact serial marker proving guest userspace readiness.

The default is the hostname line of rules_mkosi's own test images; set it for your image, for example to
`systemd[1]: Hostname set to <myhost>.`""",
        ),
        "shutdown_timeout_seconds": attr.int(
            default = shutdown_timeout_seconds,
            doc = "Seconds after readiness that the guest may take to power off by itself.",
        ),
    }

def validate_lifecycle(ctx):
    """Fails unless the lifecycle limits are positive and the readiness and shutdown markers are set.

    Args:
      ctx: Rule context with BOOT_CONFIG_ATTRS.
    """
    for value, attribute in (
        (ctx.attr.boot_timeout_seconds, "boot_timeout_seconds"),
        (ctx.attr.qmp_initialization_timeout_seconds, "qmp_initialization_timeout_seconds"),
        (ctx.attr.shutdown_timeout_seconds, "shutdown_timeout_seconds"),
        (ctx.attr.diagnostic_bytes, "diagnostic_bytes"),
    ):
        if value <= 0:
            fail(attribute + " must be positive")
    if not ctx.attr.readiness_marker:
        fail("readiness_marker must not be empty")
    if not ctx.attr.shutdown_markers or any([not marker for marker in ctx.attr.shutdown_markers]):
        fail("shutdown_markers must contain nonempty markers")

def validate_deadlines(ctx):
    """Fails unless the lifecycle deadlines and a cleanup margin fit the Bazel test timeout category.

    Args:
      ctx: Rule context with BOOT_CONFIG_ATTRS.
    """
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

def boot_config(ctx, qemu, image, firmware_args):
    """Returns the firmware-independent boot_test.py configuration.

    Args:
      ctx: Rule context with BOOT_CONFIG_ATTRS.
      qemu: MkosiQemuToolchainInfo.
      image: Raw disk image to boot.
      firmware_args: QEMU arguments that select the firmware, appended to machine_args.
    """
    return {
        "accelerator_args": qemu_accelerator_args(ctx.attr.accelerator),
        "boot_timeout_seconds": ctx.attr.boot_timeout_seconds,
        "diagnostic_bytes": ctx.attr.diagnostic_bytes,
        "image": image.short_path,
        "kernel_preflight": ctx.executable._kernel_preflight.short_path,
        "qemu": qemu.qemu_files_to_run.executable.short_path,
        "qemu_args": ctx.attr.machine_args + firmware_args,
        "qmp_initialization_timeout_seconds": ctx.attr.qmp_initialization_timeout_seconds,
        "readiness_marker": ctx.attr.readiness_marker,
        "shutdown_markers": ctx.attr.shutdown_markers,
        "shutdown_timeout_seconds": ctx.attr.shutdown_timeout_seconds,
        "system_data": qemu.system_data_anchor.short_path,
        "test_timeout": ctx.attr.test_timeout,
    }

def boot_config_outputs(ctx, qemu, config, image, firmware_files, extra_files = []):
    """Writes the configuration and returns the providers of a boot configuration rule.

    Args:
      ctx: Rule context with BOOT_CONFIG_ATTRS.
      qemu: MkosiQemuToolchainInfo.
      config: boot_test.py configuration.
      image: Raw disk image to boot.
      firmware_files: Firmware files read by QEMU.
      extra_files: Further files that the guest reads.

    Returns:
      A list of DefaultInfo and QemuBootConfigInfo.
    """
    output = ctx.actions.declare_file(ctx.label.name + ".json")
    ctx.actions.write(output = output, content = json.encode(config) + "\n")
    runfiles = ctx.runfiles(
        files = [image] + firmware_files + [
            qemu.qemu_files_to_run.executable,
            qemu.system_data_anchor,
            ctx.executable._kernel_preflight,
        ] + extra_files,
        transitive_files = depset(transitive = [
            qemu.qemu_runfiles.files,
            qemu.system_data_files,
            ctx.attr._kernel_preflight[DefaultInfo].default_runfiles.files,
        ]),
    )
    return [
        DefaultInfo(files = depset([output]), runfiles = runfiles),
        QemuBootConfigInfo(
            test_timeout = ctx.attr.test_timeout,
            qmp_initialization_timeout_seconds = ctx.attr.qmp_initialization_timeout_seconds,
            boot_timeout_seconds = ctx.attr.boot_timeout_seconds,
            shutdown_timeout_seconds = ctx.attr.shutdown_timeout_seconds,
            cleanup_margin_seconds = _CLEANUP_MARGIN_SECONDS,
        ),
    ]

# Common attributes that apply to both the test and its configuration.
_SHARED_COMMON_ATTRS = ["exec_compatible_with", "target_compatible_with", "visibility"]

def boot_test(name, config_rule, timeout, tags, testonly = None, **config_attrs):
    """Declares a boot configuration with config_rule and the boot_test.py test that uses it.

    Args:
      name: Test name; the configuration is named name + "_config".
      config_rule: Firmware adapter rule that writes the configuration.
      timeout: Bazel test timeout category.
      tags: Test tags.
      testonly: testonly of the test; None keeps the default of test rules.
      **config_attrs: Further config_rule attributes and the common attributes in _SHARED_COMMON_ATTRS.
    """
    common_attrs = {key: value for key, value in config_attrs.items() if key in _SHARED_COMMON_ATTRS}
    config_name = name + "_config"
    config_rule(
        name = config_name,
        test_timeout = timeout,
        tags = ["manual"],
        # Only tests use the configuration, and it must accept testonly images.
        testonly = True,
        **config_attrs
    )
    test_attrs = common_attrs if testonly == None else common_attrs | {"testonly": testonly}
    managed_python_test(
        name = name,
        src = "@rules_mkosi//mkosi/private:boot_test.py",
        args = ["$(rootpath :{})".format(config_name)],
        data = [
            "@rules_mkosi//mkosi/private:boot_test.py",
            "@rules_mkosi//mkosi/private:diagnostics.py",
            "@rules_mkosi//mkosi/private:http_share.py",
            "@rules_mkosi//mkosi/private:sibling_loader.py",
            ":{}".format(config_name),
        ],
        timeout = timeout,
        tags = tags,
        **test_attrs
    )
