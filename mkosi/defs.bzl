"""Public API for rules_mkosi."""

load("//mkosi:toolchain.bzl", _MkosiToolchainInfo = "MkosiToolchainInfo")
load(
    "//mkosi/private:mkosi_image.bzl",
    _MkosiImageInfo = "MkosiImageInfo",
    _mkosi_image = "mkosi_image",
)

MkosiImageInfo = _MkosiImageInfo
MkosiToolchainInfo = _MkosiToolchainInfo
mkosi_image = _mkosi_image
