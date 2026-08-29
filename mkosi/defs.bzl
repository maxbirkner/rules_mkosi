"""Public API for rules_mkosi."""

load(
    "//mkosi/private:mkosi_image.bzl",
    _MkosiImageInfo = "MkosiImageInfo",
    _mkosi_image = "mkosi_image",
)

MkosiImageInfo = _MkosiImageInfo
mkosi_image = _mkosi_image
