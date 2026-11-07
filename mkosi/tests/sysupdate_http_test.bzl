"""Analysis tests for HTTP update sources, offline signatures of payload manifests, and HTTP shares of boot tests."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")
load(
    "//mkosi:defs.bzl",
    "SysupdateEphemeralTestFixtureInfo",
    "SysupdatePayloadInfo",
    "SysupdateSigningRequestInfo",
    "sysupdate_ephemeral_test_fixture",
    "sysupdate_import_signature",
    "sysupdate_signing_request",
    "sysupdate_transfers",
)
load(":analysis_test_helpers.bzl", "expected_failure_test", "option_value", "single_action")
load(":sysupdate_test.bzl", "boot_config_subject")

_EPHEMERAL_REQUIREMENTS = ["no-cache", "no-remote", "no-remote-cache", "no-remote-exec"]

def _url_transfers_test_impl(ctx):
    env = analysistest.begin(ctx)
    argv = single_action(env, "MkosiSysupdateTransfers").argv
    asserts.equals(env, ctx.attr.expected_url or None, option_value(argv, "--url"))
    return analysistest.end(env)

_url_transfers_test = analysistest.make(_url_transfers_test_impl, attrs = {"expected_url": attr.string()})

def _fixture_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    fixture = target[SysupdateEphemeralTestFixtureInfo]
    action = single_action(env, "SysupdateEphemeralFixture")
    for requirement in _EPHEMERAL_REQUIREMENTS:
        asserts.equals(env, "1", fixture.execution_requirements[requirement], requirement)
    asserts.false(env, "local" in fixture.execution_requirements, "the fixture must run under the sandbox strategy")
    payloads = [payload[SysupdatePayloadInfo].directory.path for payload in ctx.attr.payloads]
    signed = [action.argv[index + 1] for index, value in enumerate(action.argv) if value == "--sign"]
    asserts.equals(env, payloads, signed)
    asserts.equals(env, len(payloads), len(fixture.signatures))
    asserts.true(env, fixture.keyring.is_directory)
    asserts.equals(env, [fixture.keyring], target[OutputGroupInfo].keyring.to_list())
    asserts.equals(
        env,
        sorted([fixture.public_key, fixture.keyring] + fixture.signatures),
        sorted(target[DefaultInfo].files.to_list()),
    )
    return analysistest.end(env)

_fixture_test = analysistest.make(
    _fixture_test_impl,
    attrs = {"payloads": attr.label_list(providers = [SysupdatePayloadInfo])},
)

def _request_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    request = target[SysupdateSigningRequestInfo]
    payload = ctx.attr.payload[SysupdatePayloadInfo]
    asserts.equals(env, "mkosi-sysupdate-signing-request-v1", request.format_version)
    asserts.equals(env, payload.directory, request.payload.directory)
    asserts.equals(env, ["SHA256SUMS", "signer.pgp", "request.json"], [
        file.basename
        for file in (request.manifest, request.public_key, request.request)
    ])
    argv = single_action(env, "SysupdateSigningRequest").argv
    asserts.equals(env, payload.directory.path, option_value(argv, "--payload"))
    asserts.equals(env, ctx.attr.fixture[SysupdateEphemeralTestFixtureInfo].public_key.path, option_value(argv, "--public-key"))
    return analysistest.end(env)

_request_test = analysistest.make(
    _request_test_impl,
    attrs = {
        "fixture": attr.label(providers = [SysupdateEphemeralTestFixtureInfo]),
        "payload": attr.label(providers = [SysupdatePayloadInfo]),
    },
)

def _import_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    info = target[SysupdatePayloadInfo]
    payload = ctx.attr.payload[SysupdatePayloadInfo]
    asserts.equals(env, payload.directory, info.directory)
    asserts.equals(env, payload.image_id, info.image_id)
    asserts.equals(env, payload.image_version, info.image_version)
    asserts.equals(env, None, payload.signature)
    asserts.equals(env, "SHA256SUMS.gpg", info.signature.basename)
    asserts.equals(env, [info.directory, info.signature], target[DefaultInfo].files.to_list())
    action = single_action(env, "SysupdateImportSignature")
    candidates = [action.argv[index + 1] for index, value in enumerate(action.argv) if value == "--signature"]
    asserts.equals(env, [file.path for file in ctx.attr.fixture[SysupdateEphemeralTestFixtureInfo].signatures], candidates)
    asserts.equals(env, info.signature.path, option_value(action.argv, "--output"))
    return analysistest.end(env)

_import_test = analysistest.make(
    _import_test_impl,
    attrs = {
        "fixture": attr.label(providers = [SysupdateEphemeralTestFixtureInfo]),
        "payload": attr.label(providers = [SysupdatePayloadInfo]),
    },
)

def _http_boot_config_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    config = json.decode(single_action(env, "FileWrite").content)
    asserts.equals(env, ["after-1", "after-2"], [share["path"] for share in config["http_shares"]])
    runfiles = [file.short_path for file in target[DefaultInfo].default_runfiles.files.to_list()]
    for share in config["http_shares"]:
        asserts.true(env, share["files"], "share %s has files" % share["path"])
        for path in share["files"]:
            asserts.true(env, path in runfiles, "%s is a runfile" % path)
    return analysistest.end(env)

_http_boot_config_test = analysistest.make(_http_boot_config_test_impl)

def _signing_tests(payloads):
    """Declares the fixture, request and import tests for payloads and returns their labels."""
    sysupdate_ephemeral_test_fixture(name = "manifest_signer_subject", payloads = payloads, tags = ["manual"])
    _fixture_test(name = "manifest_signer_test", payloads = payloads, target_under_test = ":manifest_signer_subject")
    sysupdate_signing_request(
        name = "manifest_signing_request_subject",
        payload = payloads[0],
        public_key = ":manifest_signer_subject",
        tags = ["manual"],
    )
    _request_test(
        name = "manifest_signing_request_test",
        fixture = ":manifest_signer_subject",
        payload = payloads[0],
        target_under_test = ":manifest_signing_request_subject",
    )
    return [":manifest_signer_test", ":manifest_signing_request_test"] + _import_tests(payloads)

def _import_tests(payloads):
    """Declares tests of importing the fixture's signature for the first payload and returns their labels."""
    sysupdate_import_signature(
        name = "signed_manifest_subject",
        request = ":manifest_signing_request_subject",
        signature = ":manifest_signer_subject",
        tags = ["manual"],
    )
    _import_test(
        name = "signed_manifest_test",
        fixture = ":manifest_signer_subject",
        payload = payloads[0],
        target_under_test = ":signed_manifest_subject",
    )
    sysupdate_signing_request(
        name = "invalid_signed_payload_request_subject",
        payload = ":signed_manifest_subject",
        public_key = ":manifest_signer_subject",
        tags = ["manual"],
    )
    expected_failure_test(
        name = "invalid_signed_payload_request_test",
        expected_error = "payload must be an unsigned sysupdate_payload",
        target_under_test = ":invalid_signed_payload_request_subject",
    )
    return [":invalid_signed_payload_request_test", ":signed_manifest_test"]

def _url_tests():
    """Declares tests of sysupdate_transfers(url) and returns their labels."""
    sysupdate_transfers(
        name = "url_transfers_subject",
        image_id = "rules-mkosi-ab",
        url = "https://updates.example.com/rules-mkosi-ab/after-%A",
        tags = ["manual"],
    )
    _url_transfers_test(
        name = "url_transfers_test",
        expected_url = "https://updates.example.com/rules-mkosi-ab/after-%A",
        target_under_test = ":url_transfers_subject",
    )
    _url_transfers_test(name = "directory_transfers_test", target_under_test = ":default_transfers_subject")
    tests = [":directory_transfers_test", ":url_transfers_test"]
    for subject, url in [("scheme", "ftp://updates.example.com"), ("whitespace", "https://updates.example.com/a b")]:
        sysupdate_transfers(name = "invalid_url_%s_subject" % subject, image_id = "rules", url = url, tags = ["manual"])
        expected_failure_test(
            name = "invalid_url_%s_test" % subject,
            expected_error = "url must be an http:// or https:// URL",
            target_under_test = ":invalid_url_%s_subject" % subject,
        )
        tests.append(":invalid_url_%s_test" % subject)
    return tests

def _http_share_tests(payloads):
    """Declares tests of qemu_ovmf_boot_config(http_shares) and returns their labels."""
    boot_config_subject(
        name = "http_boot_subject",
        http_shares = {payloads[1]: "after-2", ":signed_manifest_subject": "after-1"},
    )
    _http_boot_config_test(name = "http_boot_config_test", target_under_test = ":http_boot_subject")
    tests = [":http_boot_config_test"]
    for subject, shares, expected_error in [
        ("empty_path", {payloads[0]: ""}, "must be letters, digits"),
        ("path_slash", {payloads[0]: "a/b"}, "must be letters, digits"),
        ("dot_path", {payloads[0]: ".."}, "must be letters, digits"),
        ("duplicate_path", {payloads[0]: "p", payloads[1]: "p"}, "is used more than once"),
    ]:
        boot_config_subject(name = "invalid_%s_http_subject" % subject, http_shares = shares)
        expected_failure_test(
            name = "invalid_%s_http_test" % subject,
            expected_error = expected_error,
            target_under_test = ":invalid_%s_http_subject" % subject,
        )
        tests.append(":invalid_%s_http_test" % subject)
    return tests

def sysupdate_http_test_suite(name, payloads):
    """Defines analysis tests for HTTP update sources, manifest signing and HTTP shares.

    The subjects reuse targets declared by sysupdate_test_suite in the same package.

    Args:
      name: Name of the generated test suite.
      payloads: Two sysupdate_payload labels; the first one is signed.
    """
    native.test_suite(
        name = name,
        tests = _signing_tests(payloads) + _url_tests() + _http_share_tests(payloads),
    )
