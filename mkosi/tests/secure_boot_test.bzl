"""Analysis tests for the offline Secure Boot signing rules."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")
load(
    "//mkosi:defs.bzl",
    "MkosiImageInfo",
    "SecureBootEphemeralTestFixtureInfo",
    "SecureBootSignedBinaryInfo",
    "SecureBootSigningRequestInfo",
    "secure_boot_ephemeral_test_fixture",
    "secure_boot_import_response",
    "secure_boot_signing_request",
)
load(":analysis_test_helpers.bzl", "expected_failure_test", "option_value", "single_action")

_SYSTEMD_BOOT = "EFI/systemd/systemd-bootx64.efi"

def _assert_extracts(env, action, image):
    """Asserts that action extracts systemd-boot from the ESP of image."""
    asserts.equals(env, _SYSTEMD_BOOT, option_value(action.argv, "--esp-path"))
    asserts.equals(env, image.raw_image.path, option_value(action.argv, "--image"))
    asserts.equals(env, image.partition_metadata.path, option_value(action.argv, "--partition-metadata"))
    inputs = action.inputs.to_list()
    asserts.true(env, image.raw_image in inputs and image.partition_metadata in inputs)

def _fixture_action_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    image = ctx.attr.image[MkosiImageInfo]
    extract = single_action(env, "SecureBootExtractEspFile")
    _assert_extracts(env, extract, image)
    action = single_action(env, "SecureBootEphemeralFixture")
    paths = [file.path for file in action.inputs.to_list()] + [file.path for file in action.outputs.to_list()] + action.argv
    asserts.false(env, any([".key" in path or "private.pem" in path for path in paths]))
    unsigned = [action.argv[index + 1] for index, value in enumerate(action.argv) if value == "--sign"]
    asserts.equals(env, [image.uki.path, extract.outputs.to_list()[0].path], unsigned)
    fixture = target[SecureBootEphemeralTestFixtureInfo]
    asserts.equals(env, 2, len(fixture.signed_binaries))
    asserts.equals(
        env,
        sorted([fixture.certificate] + fixture.signed_binaries),
        sorted(target[DefaultInfo].files.to_list()),
    )
    for requirement in ["no-cache", "no-remote", "no-remote-cache", "no-remote-exec"]:
        asserts.equals(env, "1", fixture.execution_requirements[requirement])
    asserts.false(env, "local" in fixture.execution_requirements, "the fixture must run under the sandbox strategy")
    return analysistest.end(env)

_fixture_action_test = analysistest.make(
    _fixture_action_test_impl,
    attrs = {"image": attr.label(mandatory = True, providers = [MkosiImageInfo])},
)

def _request_test_impl(ctx):
    env = analysistest.begin(ctx)
    request = analysistest.target_under_test(env)[SecureBootSigningRequestInfo]
    image = ctx.attr.image[MkosiImageInfo]
    action = single_action(env, "SecureBootSigningRequest")
    asserts.equals(env, ctx.attr.esp_path, request.esp_path)
    asserts.equals(env, ctx.attr.esp_path, option_value(action.argv, "--esp-path"))
    asserts.equals(env, request.unsigned_binary.path, option_value(action.argv, "--unsigned"))
    asserts.equals(env, "mkosi-secure-boot-signing-request-v3", request.format_version)
    extracts = [action for action in analysistest.target_actions(env) if action.mnemonic == "SecureBootExtractEspFile"]
    if ctx.attr.esp_path:
        asserts.equals(env, 1, len(extracts))
        _assert_extracts(env, extracts[0], image)
        asserts.equals(env, extracts[0].outputs.to_list(), [request.unsigned_binary])
    else:
        asserts.equals(env, 0, len(extracts))
        asserts.equals(env, image.uki, request.unsigned_binary)
    return analysistest.end(env)

_request_test = analysistest.make(
    _request_test_impl,
    attrs = {
        "esp_path": attr.string(),
        "image": attr.label(mandatory = True, providers = [MkosiImageInfo]),
    },
)

def _import_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    signed = target[SecureBootSignedBinaryInfo]
    action = single_action(env, "SecureBootImportAuthenticode")
    candidates = [action.argv[index + 1] for index, value in enumerate(action.argv) if value == "--signed"]
    fixture = ctx.attr.fixture[SecureBootEphemeralTestFixtureInfo]
    asserts.equals(env, [file.path for file in fixture.signed_binaries], candidates)
    asserts.equals(env, _SYSTEMD_BOOT, signed.esp_path)
    asserts.equals(env, "mkosi-secure-boot-signed-binary-v3", signed.format_version)
    asserts.true(env, signed.certificate.basename.endswith(".certificate.der"))
    asserts.equals(env, [signed.signed_binary, signed.verification_metadata], target[DefaultInfo].files.to_list())
    return analysistest.end(env)

_import_test = analysistest.make(
    _import_test_impl,
    attrs = {"fixture": attr.label(mandatory = True, providers = [SecureBootEphemeralTestFixtureInfo])},
)

def _request_tests(image):
    """Declares request tests for the UKI and systemd-boot of image and an import test; returns their labels."""
    for subject, esp_path in (("uki", ""), ("esp_file", _SYSTEMD_BOOT)):
        secure_boot_signing_request(
            name = "secure_boot_%s_request_subject" % subject,
            certificate = ":secure_boot_ephemeral_fixture",
            esp_path = esp_path,
            image = image,
            tags = ["manual"],
        )
        _request_test(
            name = "secure_boot_%s_request_test" % subject,
            esp_path = esp_path,
            image = image,
            target_under_test = ":secure_boot_%s_request_subject" % subject,
        )
    secure_boot_import_response(
        name = "secure_boot_esp_file_import_subject",
        request = ":secure_boot_esp_file_request_subject",
        signed_binary = ":secure_boot_ephemeral_fixture",
        tags = ["manual"],
    )
    _import_test(
        name = "secure_boot_esp_file_import_test",
        fixture = ":secure_boot_ephemeral_fixture",
        target_under_test = ":secure_boot_esp_file_import_subject",
    )
    return [
        ":secure_boot_esp_file_import_test",
        ":secure_boot_esp_file_request_test",
        ":secure_boot_uki_request_test",
    ]

def _invalid_esp_path_tests(image):
    """Declares tests that requests reject unsafe ESP paths and returns their labels."""
    tests = []
    for index, esp_path in enumerate(["/EFI/BOOT/BOOTX64.EFI", "EFI/../BOOTX64.EFI", "EFI//BOOTX64.EFI", "EFI/.x"]):
        secure_boot_signing_request(
            name = "secure_boot_invalid_esp_path_%d_subject" % index,
            certificate = ":secure_boot_ephemeral_fixture",
            esp_path = esp_path,
            image = image,
            tags = ["manual"],
        )
        expected_failure_test(
            name = "secure_boot_invalid_esp_path_%d_test" % index,
            expected_error = "esp_path %r must be a relative path" % esp_path,
            target_under_test = ":secure_boot_invalid_esp_path_%d_subject" % index,
        )
        tests.append(":secure_boot_invalid_esp_path_%d_test" % index)
    return tests

def secure_boot_test_suite(name, image):
    """Defines analysis tests for the Secure Boot signing rules.

    Args:
      name: Name of the generated test suite.
      image: UEFI release mkosi_image with an unsigned UKI.
    """
    secure_boot_ephemeral_test_fixture(
        name = "secure_boot_ephemeral_fixture",
        esp_paths = [_SYSTEMD_BOOT],
        images = [image],
        tags = ["manual"],
    )
    _fixture_action_test(
        name = "secure_boot_fixture_action_test",
        image = image,
        target_under_test = ":secure_boot_ephemeral_fixture",
    )
    native.test_suite(
        name = name,
        tests = [":secure_boot_fixture_action_test"] + _request_tests(image) + _invalid_esp_path_tests(image),
    )
