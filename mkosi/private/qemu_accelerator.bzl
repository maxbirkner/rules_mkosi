"""QEMU accelerator policy shared by every QEMU test adapter."""

QEMU_ACCELERATORS = ["auto", "tcg"]

QEMU_ACCELERATOR_DOC = """QEMU accelerator: `auto` (default) or `tcg`.

`auto` uses KVM when the test can open `/dev/kvm` for reading and writing, and TCG software emulation otherwise; for
a guest of another architecture than the execution platform, such as an arm64 image on Linux x86-64, it uses TCG.
`tcg` always uses TCG.
Both use the same guest CPU model.
The test log records the accelerator QEMU used.
"""

def qemu_accelerator_args(accelerator, native = True):
    """Returns the QEMU `-accel` arguments for an accelerator policy.

    Args:
      accelerator: One of QEMU_ACCELERATORS.
      native: Whether the guest has the architecture of the execution platform, so that KVM can run it.

    Returns:
      A list of QEMU command-line arguments in preference order.
    """
    if accelerator == "auto" and native:
        return ["-accel", "kvm", "-accel", "tcg"]
    if accelerator == "auto":
        return ["-accel", "tcg"]
    if accelerator == "tcg":
        return ["-accel", "tcg"]
    fail("accelerator must be one of %s, got %r" % (QEMU_ACCELERATORS, accelerator))
