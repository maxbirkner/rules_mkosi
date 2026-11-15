"""Selects the static musl bootstrap platform of the host's CPU."""

load("@platforms//host:constraints.bzl", "HOST_CONSTRAINTS")

# Bootstrap executables run on the execution platform, which for local execution is the host. Their default target
# platform and first execution platform therefore follow the host's CPU: Linux aarch64 hosts build them for and with
# linux_aarch64_musl, all other hosts for and with linux_x86_64_musl.
HOST_BOOTSTRAP_PLATFORM = (
    "//mkosi/toolchain/bootstrap_cc:linux_aarch64_musl" if "@platforms//cpu:aarch64" in HOST_CONSTRAINTS else "//mkosi/toolchain/bootstrap_cc:linux_x86_64_musl"
)
