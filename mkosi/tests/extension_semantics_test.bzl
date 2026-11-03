"""Unit tests for mkosi module-extension version selection."""

load("@bazel_skylib//lib:unittest.bzl", "asserts", "unittest")
load("//mkosi:extensions.bzl", "resolve_mkosi_name", "resolve_mkosi_version")
load(
    "//mkosi:qemu_versions.bzl",
    "RULES_MKOSI_BAZEL_MIN_VERSION",
    "RULES_QEMU_BAZEL_MIN_VERSION",
)
load("//mkosi/debian:extensions.bzl", "snapshot_declaration_error")

def _default_test_impl(ctx):
    env = unittest.begin(ctx)
    selection = resolve_mkosi_version(None, [])
    asserts.equals(env, "27.1", selection.version)
    asserts.equals(env, "", selection.error)
    return unittest.end(env)

default_version_test = unittest.make(_default_test_impl)

def _explicit_test_impl(ctx):
    env = unittest.begin(ctx)
    selection = resolve_mkosi_version("27.1", ["27.1"])
    asserts.equals(env, "27.1", selection.version)
    asserts.equals(env, "", selection.error)
    return unittest.end(env)

explicit_version_test = unittest.make(_explicit_test_impl)

def _unsupported_test_impl(ctx):
    env = unittest.begin(ctx)
    selection = resolve_mkosi_version("27", [])
    asserts.equals(env, None, selection.version)
    asserts.equals(env, "Unsupported mkosi version 27. Supported versions: 27.1.", selection.error)
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
    selection = resolve_mkosi_version("27.1", ["26"])
    asserts.equals(env, None, selection.version)
    asserts.equals(env, "Conflicting mkosi versions: root requests 27.1, dependency requests 26.", selection.error)
    return unittest.end(env)

root_dependency_test = unittest.make(_root_dependency_test_impl)

def _qemu_bazel_compatibility_test_impl(ctx):
    env = unittest.begin(ctx)

    # Keep the dependency and public module floors distinct.
    asserts.equals(env, "7.7.0", RULES_QEMU_BAZEL_MIN_VERSION)
    asserts.equals(env, "8.8.2", RULES_MKOSI_BAZEL_MIN_VERSION)
    return unittest.end(env)

qemu_bazel_compatibility_test = unittest.make(_qemu_bazel_compatibility_test_impl)

def _snapshot_declaration_test_impl(ctx):
    env = unittest.begin(ctx)
    digest = "a" * 64
    asserts.equals(env, "", snapshot_declaration_error([]))
    asserts.equals(env, "", snapshot_declaration_error([
        ("consumer", "os_debian", ""),
        ("consumer", "Firmware.Debian-2", digest),
    ]))
    for declarations, expected in [
        ([("consumer", "", "")], "must be a valid repository name"),
        ([("consumer", "1debian", "")], "must be a valid repository name"),
        ([("consumer", "os/debian", "")], "must be a valid repository name"),
        (
            [("consumer", "mkosi_debian_snapshot", "")],
            "repository mkosi_debian_snapshot requested by consumer is already declared by rules_mkosi",
        ),
        (
            [("first", "os", ""), ("second", "os", "")],
            "repository os requested by second is already declared by first",
        ),
        (
            [("first", "os", ""), ("second", "os_packages", "")],
            "repository os_packages requested by second is already declared by first",
        ),
        ([("consumer", "os", "A" * 64)], "lowercase SHA-256"),
        ([("consumer", "os", "a" * 63)], "lowercase SHA-256"),
    ]:
        error = snapshot_declaration_error(declarations)
        asserts.true(env, expected in error, "%r did not report %r: %r" % (declarations, expected, error))
    return unittest.end(env)

snapshot_declaration_test = unittest.make(_snapshot_declaration_test_impl)
