"""Writable QEMU/OVMF systemd-sysupdate lifecycle test."""

load(":managed_python_test.bzl", "managed_python_test")
load(":qemu_ovmf_boot_test.bzl", "qemu_ovmf_boot_config")

def qemu_sysupdate_test(name, image, tags = []):
    """Runs update mutation followed by a boot of the installed slot.

    Args:
      name: Test target name.
      image: Initial release A/B disk target.
      tags: Additional Bazel tags.
    """
    config = name + "_config"
    qemu_ovmf_boot_config(
        name = config,
        image = image,
        readiness_marker = "unused",
        shutdown_markers = [
            "systemd-shutdown[1]: Powering off.",
            "reboot: Power down",
        ],
        machine_args = ["-machine", "q35", "-m", "2048M"],
        boot_timeout_seconds = 300,
        qmp_initialization_timeout_seconds = 15,
        shutdown_timeout_seconds = 60,
        diagnostic_bytes = 262144,
        test_timeout = "long",
        tags = ["manual"],
    )
    managed_python_test(
        name = name,
        src = "//mkosi/private:sysupdate_vm_test.py",
        args = ["$(rootpath :{})".format(config)],
        data = [
            "//mkosi/private:boot_test.py",
            "//mkosi/private:diagnostics.py",
            "//mkosi/private:partition_metadata.py",
            "//mkosi/private:sysupdate_vm_test.py",
            ":{}".format(config),
        ],
        timeout = "long",
        tags = tags,
    )
