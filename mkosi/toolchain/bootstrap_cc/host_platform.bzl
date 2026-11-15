"""Selects the static musl bootstrap platform of the host."""

load("@platforms//host:constraints.bzl", "HOST_CONSTRAINTS")

def select_host_bootstrap_platform(host_constraints):
    """Returns the label of the static musl bootstrap platform for a host.

    Bootstrap executables run on the execution platform, which for local execution is the host. Their default target
    platform and first execution platform therefore follow a Linux aarch64 host. Every other host, including an aarch64
    host of another operating system that executes remotely on Linux x86-64, keeps linux_x86_64_musl.

    Args:
      host_constraints: The constraint labels of the host, as in HOST_CONSTRAINTS.

    Returns:
      The label string of linux_aarch64_musl or linux_x86_64_musl.
    """
    if "@platforms//os:linux" in host_constraints and "@platforms//cpu:aarch64" in host_constraints:
        return "//mkosi/toolchain/bootstrap_cc:linux_aarch64_musl"
    return "//mkosi/toolchain/bootstrap_cc:linux_x86_64_musl"

HOST_BOOTSTRAP_PLATFORM = select_host_bootstrap_platform(HOST_CONSTRAINTS)
