"""Analysis tests for the offline Secure Boot signing rules."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")
load(
    "//mkosi:defs.bzl",
    "MkosiImageInfo",
    "SecureBootEphemeralTestFixtureInfo",
    "SecureBootSignedBinaryInfo",
    "SecureBootSigningRequestInfo",
    "qemu_ovmf_boot_config",
    "qemu_ovmf_boot_test",
    "secure_boot_ephemeral_test_fixture",
    "secure_boot_import_response",
    "secure_boot_signed_image",
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
    asserts.equals(env, ["PK.auth", "KEK.auth", "db.auth"], [file.basename for file in fixture.auto_enroll_keys])
    asserts.equals(
        env,
        sorted([fixture.certificate] + fixture.signed_binaries + fixture.auto_enroll_keys),
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

def _signed_image_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    image = ctx.attr.image[MkosiImageInfo]
    signed = target[MkosiImageInfo]
    action = single_action(env, "SecureBootSignedImage")
    asserts.equals(env, "force", option_value(action.argv, "--secure-boot-enroll"))
    keys = [action.argv[index + 1] for index, value in enumerate(action.argv) if value == "--auto-enroll-key"]
    asserts.equals(env, ["PK.auth", "KEK.auth", "db.auth"], [key.split("/")[-1] for key in keys])
    asserts.equals(env, 2, len([value for value in action.argv if value == "--signed"]))
    asserts.true(env, image.raw_image in action.inputs.to_list())
    outputs = target[DefaultInfo].files.to_list()
    asserts.equals(env, [signed.raw_image] + [file for file in outputs if file.extension == "json"], outputs)
    asserts.equals(env, "secure_boot_signed_image_subject.raw", signed.raw_image.basename)
    asserts.equals(env, signed.raw_image, signed.image)
    for field in ("uki", "partition_metadata", "root_hash", "image_id", "firmware"):
        asserts.equals(env, getattr(image, field), getattr(signed, field), field)
    return analysistest.end(env)

_signed_image_test = analysistest.make(
    _signed_image_test_impl,
    attrs = {"image": attr.label(mandatory = True, providers = [MkosiImageInfo])},
)

def _signed_image_tests(image):
    """Declares tests of secure_boot_signed_image and returns their labels."""
    secure_boot_signed_image(
        name = "secure_boot_signed_image_subject",
        auto_enroll_keys = [":secure_boot_ephemeral_fixture"],
        image = image,
        secure_boot_enroll = "force",
        signed_binaries = [":secure_boot_uki_import_subject", ":secure_boot_esp_file_import_subject"],
        tags = ["manual"],
    )
    _signed_image_test(
        name = "secure_boot_signed_image_test",
        image = image,
        target_under_test = ":secure_boot_signed_image_subject",
    )
    secure_boot_signed_image(
        name = "secure_boot_enroll_without_keys_subject",
        image = image,
        secure_boot_enroll = "force",
        signed_binaries = [":secure_boot_uki_import_subject"],
        tags = ["manual"],
    )
    expected_failure_test(
        name = "secure_boot_enroll_without_keys_test",
        expected_error = "secure_boot_enroll requires auto_enroll_keys",
        target_under_test = ":secure_boot_enroll_without_keys_subject",
    )
    return [":secure_boot_enroll_without_keys_test", ":secure_boot_signed_image_test"]

def _secure_boot_firmware_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    writes = [action for action in analysistest.target_actions(env) if action.mnemonic == "FileWrite"]
    asserts.equals(env, 1, len(writes))
    config = json.decode(writes[0].content)
    asserts.true(env, config["firmware_code"].endswith("/OVMF_CODE_4M.secboot.fd"), config["firmware_code"])
    asserts.true(env, config["firmware_vars"].endswith("/OVMF_VARS_4M.fd"), config["firmware_vars"])
    asserts.equals(
        env,
        ["-machine", "q35", "-m", "512M", "-machine", "smm=on", "-global", "driver=cfi.pflash01,property=secure,value=on"],
        config["qemu_args"][:8],
    )
    runfiles = [file.basename for file in target[DefaultInfo].default_runfiles.files.to_list()]
    asserts.true(env, "OVMF_CODE_4M.secboot.fd" in runfiles and "OVMF_VARS_4M.fd" in runfiles)
    asserts.false(env, "code.fd" in runfiles, "the toolchain's OVMF cannot enforce Secure Boot")
    return analysistest.end(env)

_secure_boot_firmware_test = analysistest.make(_secure_boot_firmware_test_impl)

def _credentials_test_impl(ctx):
    env = analysistest.begin(ctx)
    config = json.decode(single_action(env, "FileWrite").content)
    asserts.equals(
        env,
        [
            "-smbios",
            "type=11,value=io.systemd.credential:rules-mkosi.marker=a,,b",
            "-smbios",
            "type=11,value=io.systemd.credential:systemd.unit-dropin.ready.service=[Service]\nExecStart=true\n",
        ],
        config["qemu_args"][-4:],
    )
    return analysistest.end(env)

_credentials_test = analysistest.make(_credentials_test_impl)

def _boot_test_runfiles_test_impl(ctx):
    env = analysistest.begin(ctx)
    runfiles = analysistest.target_under_test(env)[DefaultInfo].default_runfiles.files.to_list()
    asserts.true(env, ctx.attr.config in [file.basename for file in runfiles])
    return analysistest.end(env)

_boot_test_runfiles_test = analysistest.make(
    _boot_test_runfiles_test_impl,
    attrs = {"config": attr.string(mandatory = True)},
)

def _testonly_image_tests(image):
    """Declares tests that a boot test accepts a testonly image and passes credentials; returns their labels."""
    secure_boot_signed_image(
        name = "secure_boot_testonly_signed_image_subject",
        testonly = True,
        auto_enroll_keys = [":secure_boot_ephemeral_fixture"],
        image = image,
        secure_boot_enroll = "force",
        signed_binaries = [":secure_boot_uki_import_subject", ":secure_boot_esp_file_import_subject"],
        tags = ["manual"],
    )

    # Not testonly itself: the macro makes its configuration testonly.
    qemu_ovmf_boot_test(
        name = "secure_boot_testonly_image_boot",
        credentials = {
            "rules-mkosi.marker": "a,b",
            "systemd.unit-dropin.ready.service": "[Service]\nExecStart=true\n",
        },
        image = ":secure_boot_testonly_signed_image_subject",
        secure_boot = True,
        tags = ["manual"],
    )
    _credentials_test(
        name = "secure_boot_testonly_image_boot_config_test",
        target_under_test = ":secure_boot_testonly_image_boot_config",
    )
    _boot_test_runfiles_test(
        name = "secure_boot_testonly_image_boot_runfiles_test",
        config = "secure_boot_testonly_image_boot_config.json",
        target_under_test = ":secure_boot_testonly_image_boot",
    )
    return [
        ":secure_boot_testonly_image_boot_config_test",
        ":secure_boot_testonly_image_boot_runfiles_test",
    ]

def _boot_attribute_failure_tests(image):
    """Declares tests that boot tests reject testonly = False and invalid credential names; returns their labels."""
    qemu_ovmf_boot_test(
        name = "not_testonly_boot",
        testonly = False,
        image = image,
        tags = ["manual"],
    )
    expected_failure_test(
        name = "not_testonly_boot_test",
        expected_error = "depends on testonly target",
        target_under_test = ":not_testonly_boot",
    )
    names = ["", "..", "a/b", "a:b", "a=b", "a b"]
    for index, name in enumerate(names):
        qemu_ovmf_boot_config(
            name = "invalid_credential_name_%d_subject" % index,
            credentials = {name: "value"},
            image = image,
            tags = ["manual"],
        )
        expected_failure_test(
            name = "invalid_credential_name_%d_test" % index,
            expected_error = "credentials name %r must be" % name,
            target_under_test = ":invalid_credential_name_%d_subject" % index,
        )
    return [":not_testonly_boot_test"] + [":invalid_credential_name_%d_test" % index for index in range(len(names))]

def _secure_boot_firmware_tests():
    """Declares tests of qemu_ovmf_boot_test(secure_boot = True) and returns their labels."""
    qemu_ovmf_boot_test(
        name = "secure_boot_firmware_boot",
        image = ":secure_boot_signed_image_subject",
        secure_boot = True,
        tags = ["manual"],
    )
    _secure_boot_firmware_test(
        name = "secure_boot_firmware_boot_config_test",
        target_under_test = ":secure_boot_firmware_boot_config",
    )
    qemu_ovmf_boot_config(
        name = "secure_boot_code_without_vars_subject",
        boot_timeout_seconds = 15,
        diagnostic_bytes = 4096,
        image = ":secure_boot_signed_image_subject",
        machine_args = ["-machine", "q35"],
        qmp_initialization_timeout_seconds = 15,
        readiness_marker = "READY",
        secure_boot_code = "@mkosi_ovmf_secure_boot//:OVMF_CODE_4M.secboot.fd",
        shutdown_markers = ["SHUTDOWN"],
        shutdown_timeout_seconds = 15,
        tags = ["manual"],
    )
    expected_failure_test(
        name = "secure_boot_code_without_vars_test",
        expected_error = "secure_boot_code and secure_boot_vars must be set together",
        target_under_test = ":secure_boot_code_without_vars_subject",
    )
    return [":secure_boot_code_without_vars_test", ":secure_boot_firmware_boot_config_test"]

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
    for subject in ("uki", "esp_file"):
        secure_boot_import_response(
            name = "secure_boot_%s_import_subject" % subject,
            request = ":secure_boot_%s_request_subject" % subject,
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
        tests = (
            [":secure_boot_fixture_action_test"] + _request_tests(image) + _invalid_esp_path_tests(image) +
            _signed_image_tests(image) + _secure_boot_firmware_tests() + _testonly_image_tests(image) +
            _boot_attribute_failure_tests(image)
        ),
    )
