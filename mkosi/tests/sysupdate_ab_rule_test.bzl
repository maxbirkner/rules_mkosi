"""Analysis coverage for the public systemd-sysupdate A/B contract."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")
load(
    "//mkosi:defs.bzl",
    "MkosiImageInfo",
    "SecureBootSignedUkiInfo",
    "SysupdateAbInfo",
    "sysupdate_ab",
)

def _image_fixture_impl(ctx):
    root = ctx.actions.declare_file(ctx.label.name + ".root.raw")
    verity = ctx.actions.declare_file(ctx.label.name + ".verity.raw")
    ctx.actions.write(root, "root")
    ctx.actions.write(verity, "verity")
    return [
        DefaultInfo(files = depset([root, verity])),
        MkosiImageInfo(
            format_version = "mkosi-image-v2",
            raw_image = None,
            manifest = None,
            partition_metadata = None,
            uki = None,
            root_image = root,
            root_hash = None,
            root_hash_image = verity,
            root_hash_signature = None,
            uki_metadata = None,
            verity_metadata = None,
            build_metadata = None,
            firmware = ctx.attr.firmware,
            image = None,
        ),
    ]

_image_fixture = rule(
    implementation = _image_fixture_impl,
    attrs = {"firmware": attr.string(default = "uefi")},
)

def _signed_fixture_impl(ctx):
    uki = ctx.actions.declare_file(ctx.label.name + ".efi")
    ctx.actions.write(uki, "signed")
    return [
        DefaultInfo(files = depset([uki])),
        SecureBootSignedUkiInfo(
            format_version = "mkosi-secure-boot-signed-uki-v2",
            request = None,
            signed_uki = uki,
            verification_metadata = None,
        ),
    ]

_signed_fixture = rule(implementation = _signed_fixture_impl)

def _provider_test_impl(ctx):
    env = analysistest.begin(ctx)
    info = analysistest.target_under_test(env)[SysupdateAbInfo]
    asserts.equals(env, "rules-mkosi-sysupdate-ab-v1", info.format_version)
    asserts.equals(env, "uefi", info.firmware)
    asserts.equals(env, "1.0.0", info.slot_a.version)
    asserts.equals(env, "2.0.0", info.slot_b.version)
    asserts.equals(env, 3, info.boot_attempts)
    asserts.true(env, info.layout.basename.endswith(".layout.json"))
    asserts.true(env, info.root_transfer.basename.endswith(".root.transfer"))
    asserts.equals(env, "/usr/lib/systemd/systemd-sysupdate", info.sysupdate_binary)
    return analysistest.end(env)

_provider_test = analysistest.make(_provider_test_impl)

def _failure_test_impl(ctx):
    env = analysistest.begin(ctx)
    asserts.expect_failure(env, "uefi")
    return analysistest.end(env)

_failure_test = analysistest.make(_failure_test_impl, expect_failure = True)

def sysupdate_ab_test_suite(name):
    """Instantiates analysis coverage for the systemd-sysupdate A/B rule.

    Args:
      name: Prefix for generated fixture and test targets.
    """
    _image_fixture(name = name + "_image_a")
    _image_fixture(name = name + "_image_b")
    _signed_fixture(name = name + "_signed_a")
    _signed_fixture(name = name + "_signed_b")
    sysupdate_ab(
        name = name + "_subject",
        slot_a_image = name + "_image_a",
        slot_a_signed_uki = name + "_signed_a",
        slot_a_version = "1.0.0",
        slot_b_image = name + "_image_b",
        slot_b_signed_uki = name + "_signed_b",
        slot_b_version = "2.0.0",
        tags = ["manual"],
    )
    _provider_test(
        name = name + "_provider_test",
        target_under_test = name + "_subject",
    )
    sysupdate_ab(
        name = name + "_bios_subject",
        firmware = "bios",
        slot_a_image = name + "_image_a",
        slot_a_signed_uki = name + "_signed_a",
        slot_a_version = "1",
        slot_b_image = name + "_image_b",
        slot_b_signed_uki = name + "_signed_b",
        slot_b_version = "2",
        tags = ["manual"],
    )
    _failure_test(
        name = name + "_bios_rejection_test",
        target_under_test = name + "_bios_subject",
    )
