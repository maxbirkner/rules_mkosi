"""QEMU accelerator policy shared by every QEMU test adapter."""

QEMU_ACCELERATORS = ["auto", "tcg"]

QEMU_ACCELERATOR_DOC = """QEMU accelerator: `auto` (default) or `tcg`.

`auto` uses KVM when the test can open `/dev/kvm` for reading and writing, and TCG software emulation otherwise.
`tcg` always uses TCG.
Both use the same guest CPU model.
The test log records the accelerator QEMU used.
"""

def qemu_accelerator_args(accelerator):
    """Returns the QEMU `-accel` arguments for an accelerator policy.

    Args:
      accelerator: One of QEMU_ACCELERATORS.

    Returns:
      A list of QEMU command-line arguments in preference order.
    """
    if accelerator == "auto":
        return ["-accel", "kvm", "-accel", "tcg"]
    if accelerator == "tcg":
        return ["-accel", "tcg"]
    fail("accelerator must be one of %s, got %r" % (QEMU_ACCELERATORS, accelerator))
