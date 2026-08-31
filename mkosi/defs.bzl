"""Public API for rules_mkosi."""

load(
    "//mkosi:qemu_toolchain.bzl",
    _MkosiQemuToolchainInfo = "MkosiQemuToolchainInfo",
    _qemu_executable = "qemu_executable",
    _qemu_ovmf_toolchain = "qemu_ovmf_toolchain",
)
load("//mkosi:toolchain.bzl", _MkosiToolchainInfo = "MkosiToolchainInfo")
load("//mkosi/debian:toolchain.bzl", _DebianToolsInfo = "DebianToolsInfo")
load(
    "//mkosi/private:debian_snapshot.bzl",
    _DebianSnapshotInfo = "DebianSnapshotInfo",
    _debian_snapshot = "debian_snapshot",
)
load(
    "//mkosi/private:managed_python_test.bzl",
    _ManagedPythonTestInfo = "ManagedPythonTestInfo",
    _managed_python_test = "managed_python_test",
)
load(
    "//mkosi/private:mkosi_image.bzl",
    _MkosiImageInfo = "MkosiImageInfo",
    _mkosi_image = "mkosi_image",
)
load(
    "//mkosi/private:qemu_ovmf_boot_test.bzl",
    _QemuOvmfBootConfigInfo = "QemuOvmfBootConfigInfo",
    _qemu_ovmf_boot_config = "qemu_ovmf_boot_config",
    _qemu_ovmf_boot_test = "qemu_ovmf_boot_test",
)
load(
    "//mkosi/private:qemu_ovmf_smoke_test.bzl",
    _qemu_ovmf_smoke_test = "qemu_ovmf_smoke_test",
)

MkosiImageInfo = _MkosiImageInfo
MkosiQemuToolchainInfo = _MkosiQemuToolchainInfo
MkosiToolchainInfo = _MkosiToolchainInfo
DebianToolsInfo = _DebianToolsInfo
DebianSnapshotInfo = _DebianSnapshotInfo
ManagedPythonTestInfo = _ManagedPythonTestInfo
QemuOvmfBootConfigInfo = _QemuOvmfBootConfigInfo
mkosi_image = _mkosi_image
debian_snapshot = _debian_snapshot
qemu_ovmf_smoke_test = _qemu_ovmf_smoke_test
qemu_ovmf_boot_test = _qemu_ovmf_boot_test
qemu_ovmf_boot_config = _qemu_ovmf_boot_config
managed_python_test = _managed_python_test
qemu_executable = _qemu_executable
qemu_ovmf_toolchain = _qemu_ovmf_toolchain
