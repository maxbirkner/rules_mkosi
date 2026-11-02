"""QEMU accelerator policy shared by every QEMU test adapter."""

QEMU_ACCELERATORS = ["auto", "tcg"]

QEMU_ACCELERATOR_DOC = """QEMU accelerator policy: `auto` (default) or `tcg`.

`auto` lists KVM before TCG. QEMU uses KVM when the test process can open `/dev/kvm` for reading and writing and
otherwise falls back to TCG software emulation in the same process. `tcg` always uses TCG, for example to keep
software-emulation coverage on hosts that provide KVM. The guest CPU model is the same for both accelerators.
The accelerator QEMU actually selected is recorded in the test log and boot evidence.
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
