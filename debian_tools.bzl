"""Compatibility wrapper for the public Debian userspace toolchain API."""

load("//mkosi:debian_tools.bzl", _DebianToolsInfo = "DebianToolsInfo")

DebianToolsInfo = _DebianToolsInfo
