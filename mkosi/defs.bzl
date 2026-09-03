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
    _MkosiConfigTreeInfo = "MkosiConfigTreeInfo",
    _MkosiImageInfo = "MkosiImageInfo",
    _MkosiRootfsPayloadInfo = "MkosiRootfsPayloadInfo",
    _MkosiSourceTreeInfo = "MkosiSourceTreeInfo",
    _mkosi_config_tree = "mkosi_config_tree",
    _mkosi_image = "mkosi_image",
    _mkosi_reproducibility_manifest = "mkosi_reproducibility_manifest",
    _mkosi_rootfs_payload = "mkosi_rootfs_payload",
    _mkosi_source_tree = "mkosi_source_tree",
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
load(
    "//mkosi/private:qemu_seabios_boot_test.bzl",
    _qemu_seabios_boot_config = "qemu_seabios_boot_config",
    _qemu_seabios_boot_test = "qemu_seabios_boot_test",
)
load(
    "//mkosi/private:secure_boot.bzl",
    _SecureBootEphemeralTestFixtureInfo = "SecureBootEphemeralTestFixtureInfo",
    _SecureBootSignedUkiInfo = "SecureBootSignedUkiInfo",
    _SecureBootSigningRequestInfo = "SecureBootSigningRequestInfo",
    _secure_boot_ephemeral_test_fixture = "secure_boot_ephemeral_test_fixture",
    _secure_boot_import_response = "secure_boot_import_response",
    _secure_boot_signing_request = "secure_boot_signing_request",
)
load(
    "//mkosi/private:sysupdate_ab.bzl",
    _SysupdateAbInfo = "SysupdateAbInfo",
    _sysupdate_ab = "sysupdate_ab",
)
load("//mkosi/private:sysupdate_payload.bzl", _sysupdate_update_payload = "sysupdate_update_payload")

MkosiImageInfo = _MkosiImageInfo
MkosiConfigTreeInfo = _MkosiConfigTreeInfo
MkosiSourceTreeInfo = _MkosiSourceTreeInfo
MkosiRootfsPayloadInfo = _MkosiRootfsPayloadInfo
MkosiQemuToolchainInfo = _MkosiQemuToolchainInfo
MkosiToolchainInfo = _MkosiToolchainInfo
DebianToolsInfo = _DebianToolsInfo
DebianSnapshotInfo = _DebianSnapshotInfo
ManagedPythonTestInfo = _ManagedPythonTestInfo
QemuOvmfBootConfigInfo = _QemuOvmfBootConfigInfo
mkosi_image = _mkosi_image
mkosi_reproducibility_manifest = _mkosi_reproducibility_manifest
debian_snapshot = _debian_snapshot
mkosi_config_tree = _mkosi_config_tree
mkosi_source_tree = _mkosi_source_tree
mkosi_rootfs_payload = _mkosi_rootfs_payload
qemu_ovmf_smoke_test = _qemu_ovmf_smoke_test
qemu_ovmf_boot_test = _qemu_ovmf_boot_test
qemu_ovmf_boot_config = _qemu_ovmf_boot_config
qemu_seabios_boot_test = _qemu_seabios_boot_test
qemu_seabios_boot_config = _qemu_seabios_boot_config
managed_python_test = _managed_python_test
qemu_executable = _qemu_executable
qemu_ovmf_toolchain = _qemu_ovmf_toolchain
SecureBootSigningRequestInfo = _SecureBootSigningRequestInfo
SecureBootSignedUkiInfo = _SecureBootSignedUkiInfo
SecureBootEphemeralTestFixtureInfo = _SecureBootEphemeralTestFixtureInfo
SysupdateAbInfo = _SysupdateAbInfo
sysupdate_ab = _sysupdate_ab
sysupdate_update_payload = _sysupdate_update_payload
secure_boot_signing_request = _secure_boot_signing_request
secure_boot_import_response = _secure_boot_import_response
secure_boot_ephemeral_test_fixture = _secure_boot_ephemeral_test_fixture
