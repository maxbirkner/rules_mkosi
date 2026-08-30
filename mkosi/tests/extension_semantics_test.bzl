"""Unit tests for mkosi module-extension version selection."""

load("@bazel_skylib//lib:unittest.bzl", "asserts", "unittest")
load("//mkosi:extensions.bzl", "resolve_mkosi_name", "resolve_mkosi_version")
load(
    "//mkosi:qemu_versions.bzl",
    "RULES_MKOSI_BAZEL_MIN_VERSION",
    "RULES_QEMU_BAZEL_MIN_VERSION",
)

def _default_test_impl(ctx):
    env = unittest.begin(ctx)
    selection = resolve_mkosi_version(None, [])
    asserts.equals(env, "27", selection.version)
    asserts.equals(env, "", selection.error)
    return unittest.end(env)

default_version_test = unittest.make(_default_test_impl)

def _explicit_test_impl(ctx):
    env = unittest.begin(ctx)
    selection = resolve_mkosi_version("27", ["27"])
    asserts.equals(env, "27", selection.version)
    asserts.equals(env, "", selection.error)
    return unittest.end(env)

explicit_version_test = unittest.make(_explicit_test_impl)

def _unsupported_test_impl(ctx):
    env = unittest.begin(ctx)
    selection = resolve_mkosi_version("26", [])
    asserts.equals(env, None, selection.version)
    asserts.equals(env, "Unsupported mkosi version 26. Supported versions: 27.", selection.error)
    return unittest.end(env)

unsupported_version_test = unittest.make(_unsupported_test_impl)

def _conflicting_root_test_impl(ctx):
    env = unittest.begin(ctx)
    selection = resolve_mkosi_name(["mkosi", "alternate"])
    asserts.equals(env, None, selection.name)
    asserts.equals(env, "Only one mkosi toolchain may be configured.", selection.error)
    return unittest.end(env)

conflicting_root_test = unittest.make(_conflicting_root_test_impl)

def _root_dependency_test_impl(ctx):
    env = unittest.begin(ctx)
    selection = resolve_mkosi_version("27", ["26"])
    asserts.equals(env, None, selection.version)
    asserts.equals(env, "Conflicting mkosi versions: root requests 27, dependency requests 26.", selection.error)
    return unittest.end(env)

root_dependency_test = unittest.make(_root_dependency_test_impl)

def _qemu_bazel_compatibility_test_impl(ctx):
    env = unittest.begin(ctx)

    # Keep the dependency and public module floors distinct.
    asserts.equals(env, "7.7.0", RULES_QEMU_BAZEL_MIN_VERSION)
    asserts.equals(env, "8.5.1", RULES_MKOSI_BAZEL_MIN_VERSION)
    return unittest.end(env)

qemu_bazel_compatibility_test = unittest.make(_qemu_bazel_compatibility_test_impl)
