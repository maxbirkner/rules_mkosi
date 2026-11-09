"""Analysis tests for the signing material that an image declares when it derives its version from its inputs."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")
load(
    "//mkosi:defs.bzl",
    "MkosiImageInfo",
    "SecureBootSignedBinaryInfo",
    "SysupdatePayloadInfo",
    "mkosi_image",
    "secure_boot_ephemeral_test_fixture",
    "secure_boot_import_response",
    "secure_boot_signed_image",
    "secure_boot_signing_request",
    "sysupdate_payload",
)
load(
    ":analysis_test_helpers.bzl",
    "assert_artifact_tools_are_hashed",
    "expected_failure_test",
    "option_value",
    "single_action",
)

_INPUTS = "testdata/secure-boot-inputs/"
_SIGNER = _INPUTS + "signer.crt"
_AUTO_ENROLL_KEYS = [_INPUTS + name + ".auth" for name in ("PK", "KEK", "db")]
_DECLARED = "but the image's version_signing_certificates declare"

def _unverified_signed_uki_impl(ctx):
    """Returns a signed UKI provider without certificate_source, as a rule outside rules_mkosi could."""
    signed_uki = ctx.actions.declare_file(ctx.label.name + ".signed.efi")
    ctx.actions.write(signed_uki, "")
    return [SecureBootSignedBinaryInfo(
        certificate = signed_uki,
        esp_path = "",
        format_version = "mkosi-secure-boot-signed-binary-v3",
        request = signed_uki,
        signed_binary = signed_uki,
        verification_metadata = signed_uki,
    )]

_unverified_signed_uki = rule(implementation = _unverified_signed_uki_impl)

def _declarations_test_impl(ctx):
    env = analysistest.begin(ctx)
    info = analysistest.target_under_test(env)[MkosiImageInfo]
    asserts.equals(env, {"": ctx.file.signer}, info.version_signing_certificates)
    asserts.equals(env, ctx.files.keys, info.version_auto_enroll_keys)
    asserts.equals(env, ctx.files.inputs, info.version_inputs)
    argv = single_action(env, "MkosiInputVersion").argv

    # Analysis tests see the expanded inputs param files between the last option and the command line.
    hashed = argv[argv.index("--digest-output") + 2:argv.index("--command-line")]
    image_inputs = single_action(env, "MkosiImage").inputs.to_list()
    for file in [ctx.file.signer] + ctx.files.keys + ctx.files.inputs:
        asserts.true(env, file.path in hashed, "unhashed declaration " + file.path)
        asserts.false(env, file in image_inputs, "the build must not read declaration " + file.path)
    declared = {
        "auto_enroll_keys": sorted([file.path for file in ctx.files.keys]),
        "signing_certificates": {"": ctx.file.signer.path},
    }
    asserts.equals(env, declared, json.decode(option_value(argv, "--declared-json")))
    return analysistest.end(env)

_declarations_test = analysistest.make(
    _declarations_test_impl,
    attrs = {
        "inputs": attr.label_list(allow_files = True),
        "keys": attr.label_list(allow_files = True),
        "signer": attr.label(allow_single_file = True, mandatory = True),
    },
)

def _payload_test_impl(ctx):
    env = analysistest.begin(ctx)
    info = analysistest.target_under_test(env)[SysupdatePayloadInfo]
    image = ctx.attr.image[MkosiImageInfo]
    asserts.equals(env, image.image_version_file, info.image_version_file)
    asserts.true(env, image.input_digest != None)
    return analysistest.end(env)

_payload_test = analysistest.make(
    _payload_test_impl,
    attrs = {"image": attr.label(providers = [MkosiImageInfo], mandatory = True)},
)

def _signed_image_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    signed = target[MkosiImageInfo]
    image = ctx.attr.image[MkosiImageInfo]
    fields = ("image_version_file", "input_digest", "version_auto_enroll_keys", "version_inputs", "version_signing_certificates")
    for field in fields:
        asserts.equals(env, getattr(image, field), getattr(signed, field), field)
    asserts.equals(env, [image.image_version_file, image.input_digest], target[OutputGroupInfo].image_version.to_list())
    assert_artifact_tools_are_hashed(env, single_action(env, "SecureBootSignedImage"))
    return analysistest.end(env)

_signed_image_test = analysistest.make(
    _signed_image_test_impl,
    attrs = {"image": attr.label(providers = [MkosiImageInfo], mandatory = True)},
)

def _subjects():
    """Declares images that derive their version and UKIs signed for them with each certificate or a test fixture."""
    for image, certificates, keys in (
        ("signing_declared", {"": _SIGNER}, _AUTO_ENROLL_KEYS),
        ("signing_certificate_only", {"": _SIGNER}, []),
        ("signing_undeclared", {}, []),
    ):
        mkosi_image(
            name = image,
            config_tree = ":immutable_release_config_tree",
            debian_snapshot = "@mkosi_debian_snapshot//:repository",
            image_id = "rules-ab-sig",
            image_version_from_inputs = True,
            mode = "release",
            release_seed = "00000000-0000-4000-8000-000000000007",
            release_source_date_epoch = 0,
            unified_kernel_image = "unsigned",
            verity = "hash",
            version_auto_enroll_keys = keys,
            version_inputs = [_INPUTS + "README.md"] if keys else [],
            version_signing_certificates = certificates,
            tags = ["manual"],
        )
        secure_boot_ephemeral_test_fixture(name = image + "_fixture", images = [":" + image], tags = ["manual"])
        _signed_ukis(image)
    _unverified_signed_uki(name = "signing_unverified_uki", tags = ["manual"])

def _signed_ukis(image):
    for signer, certificate in (("signer", _SIGNER), ("other", _INPUTS + "other.crt"), ("fixture", ":" + image + "_fixture")):
        secure_boot_signing_request(
            name = "%s_%s_request" % (image, signer),
            certificate = certificate,
            image = ":" + image,
            tags = ["manual"],
        )
        secure_boot_import_response(
            name = "%s_%s_uki" % (image, signer),
            request = ":%s_%s_request" % (image, signer),
            signed_binary = ":" + image + "_fixture" if signer == "fixture" else _INPUTS + "uki.signed.efi",
            tags = ["manual"],
        )

def _payload_tests():
    """Declares payloads that agree with the image's declarations, or not, and returns their tests."""
    tests = []
    for name, image, signed_uki, expected_error in (
        ("declared_signer", "signing_declared", ":signing_declared_signer_uki", None),
        ("declared_fixture", "signing_declared", ":signing_declared_fixture_uki", None),
        ("undeclared_fixture", "signing_undeclared", ":signing_undeclared_fixture_uki", None),
        ("other_signer", "signing_declared", ":signing_declared_other_uki", "signs with [UKI: mkosi/tests/" + _INPUTS + "other.crt], " + _DECLARED),
        ("undeclared_signer", "signing_undeclared", ":signing_undeclared_signer_uki", "signs with [UKI: mkosi/tests/" + _SIGNER + "], " + _DECLARED + " [none]"),
        ("declared_unsigned", "signing_declared", None, "signs with [none], " + _DECLARED + " [UKI: mkosi/tests/" + _SIGNER + "]"),
        ("unverified", "signing_declared", ":signing_unverified_uki", "has no certificate_source"),
    ):
        sysupdate_payload(name = "signing_%s_payload" % name, image = ":" + image, signed_uki = signed_uki, tags = ["manual"])
        if expected_error:
            expected_failure_test(
                name = "signing_%s_payload_test" % name,
                expected_error = expected_error,
                target_under_test = ":signing_%s_payload" % name,
            )
        else:
            _payload_test(name = "signing_%s_payload_test" % name, image = ":" + image, target_under_test = ":signing_%s_payload" % name)
        tests.append(":signing_%s_payload_test" % name)
    return tests

def _signed_image_tests():
    """Declares Secure Boot images that agree with the image's declarations, or not, and returns their tests."""
    tests = []
    for name, image, signed_uki, keys, expected_error in (
        ("declared", "signing_declared", "signer", _AUTO_ENROLL_KEYS, None),
        ("fixture_keys", "signing_declared", "signer", [":signing_declared_fixture"], None),
        ("other_signer", "signing_declared", "other", _AUTO_ENROLL_KEYS, _DECLARED),
        ("undeclared_keys", "signing_certificate_only", "signer", _AUTO_ENROLL_KEYS, "but the image's version_auto_enroll_keys are []"),
    ):
        secure_boot_signed_image(
            name = "signing_%s_image" % name,
            auto_enroll_keys = keys,
            image = ":" + image,
            signed_binaries = [":%s_%s_uki" % (image, signed_uki)],
            tags = ["manual"],
        )
        if expected_error:
            expected_failure_test(name = "signing_%s_image_test" % name, expected_error = expected_error, target_under_test = ":signing_%s_image" % name)
        else:
            _signed_image_test(name = "signing_%s_image_test" % name, image = ":" + image, target_under_test = ":signing_%s_image" % name)
        tests.append(":signing_%s_image_test" % name)
    return tests

def _attribute_failure_tests():
    """Declares images that set version declarations without deriving their version, and returns their tests."""
    tests = []
    for name, kwargs in (
        ("version_inputs", {"version_inputs": [_SIGNER]}),
        ("signing_certificates", {"version_signing_certificates": {"": _SIGNER}}),
        ("auto_enroll_keys", {"version_auto_enroll_keys": _AUTO_ENROLL_KEYS}),
    ):
        mkosi_image(name = "invalid_%s_subject" % name, config = "testdata/minimal.conf", image_id = "rules", tags = ["manual"], **kwargs)
        expected_failure_test(
            name = "invalid_%s_test" % name,
            expected_error = "version_inputs, version_signing_certificates and version_auto_enroll_keys require " +
                             "image_version_from_inputs",
            target_under_test = ":invalid_%s_subject" % name,
        )
        tests.append(":invalid_%s_test" % name)
    return tests

def version_signing_test_suite(name):
    """Defines analysis tests for version_inputs, version_signing_certificates and version_auto_enroll_keys.

    The subjects reuse configuration trees declared by mkosi_image_test_suite in the same package.

    Args:
      name: Name of the generated test suite.
    """
    _subjects()
    _declarations_test(
        name = "signing_declarations_test",
        inputs = [_INPUTS + "README.md"],
        keys = _AUTO_ENROLL_KEYS,
        signer = _SIGNER,
        target_under_test = ":signing_declared",
    )
    native.test_suite(
        name = name,
        tests = [":signing_declarations_test"] + _payload_tests() + _signed_image_tests() + _attribute_failure_tests(),
    )
