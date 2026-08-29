"""Public API for rules_mkosi."""

load(
    "//mkosi:qemu_toolchain.bzl",
    _MkosiQemuToolchainInfo = "MkosiQemuToolchainInfo",
    _qemu_executable = "qemu_executable",
    _qemu_ovmf_toolchain = "qemu_ovmf_toolchain",
)
load("//mkosi:toolchain.bzl", _MkosiToolchainInfo = "MkosiToolchainInfo")
load(
    "//mkosi/private:mkosi_image.bzl",
    _MkosiImageInfo = "MkosiImageInfo",
    _mkosi_image = "mkosi_image",
)
load(
    "//mkosi/private:qemu_ovmf_smoke_test.bzl",
    _qemu_ovmf_smoke_test = "qemu_ovmf_smoke_test",
)

MkosiImageInfo = _MkosiImageInfo
MkosiQemuToolchainInfo = _MkosiQemuToolchainInfo
MkosiToolchainInfo = _MkosiToolchainInfo
mkosi_image = _mkosi_image
qemu_ovmf_smoke_test = _qemu_ovmf_smoke_test
qemu_executable = _qemu_executable
qemu_ovmf_toolchain = _qemu_ovmf_toolchain
