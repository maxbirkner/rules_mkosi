"""Offline Authenticode Secure Boot rules."""

load("//mkosi/private:mkosi_image.bzl", "MkosiImageInfo")
load("//mkosi/private:python_action.bzl", "MKOSI_TOOLCHAIN_TYPE", "run_python")

SecureBootSigningRequestInfo = provider(
    doc = "Typed immutable request for an external Secure Boot signer.",
    fields = {
        "certificate": "Expected public signer certificate.",
        "format_version": "Request schema, mkosi-secure-boot-signing-request-v2.",
        "request": "Canonical JSON request.",
        "request_digest": "Canonical request SHA-256.",
        "signature_algorithm": "Required embedded Authenticode algorithm.",
        "unsigned_uki": "Exact unsigned UKI bound by the request.",
    },
)

SecureBootSignedUkiInfo = provider(
    doc = "Authenticode-verified, firmware-consumable UKI.",
    fields = {
        "format_version": "Provider schema, mkosi-secure-boot-signed-uki-v2.",
        "request": "Verified request.",
        "signed_uki": "Verified signed PE/COFF UKI.",
        "verification_metadata": "Verification and equivalence metadata.",
    },
)

SecureBootEphemeralTestFixtureInfo = provider(
    doc = "Public outputs from one action-private ephemeral signing operation.",
    fields = {
        "certificate": "Ephemeral public certificate.",
        "execution_requirements": "Local, no-remote, no-cache action policy.",
        "signed_uki": "Authenticode-signed test UKI.",
    },
)

_EPHEMERAL_EXECUTION_REQUIREMENTS = {
    "local": "1",
    "no-cache": "1",
    "no-remote": "1",
    "no-remote-cache": "1",
    "no-remote-exec": "1",
}

def _run(ctx, args, inputs, outputs, mnemonic, **kwargs):
    run_python(
        ctx,
        arguments = [args],
        inputs = [ctx.file._tool, ctx.file._file_hashing, ctx.file._sibling_loader, ctx.executable._debian_tools] + inputs,
        outputs = outputs,
        mnemonic = mnemonic,
        # The ephemeral fixture runs unsandboxed; loading file_hashing.py must not write a __pycache__ into the sources.
        env = {"PYTHONDONTWRITEBYTECODE": "1"},
        **kwargs
    )

def _single_file(target, attribute):
    """Returns the file of the attribute, or the field of the same name of a test fixture."""
    if SecureBootEphemeralTestFixtureInfo in target:
        return getattr(target[SecureBootEphemeralTestFixtureInfo], attribute)
    files = target.files.to_list()
    if len(files) != 1:
        fail("{} must provide one File or SecureBootEphemeralTestFixtureInfo".format(attribute))
    return files[0]

def _request_impl(ctx):
    image = ctx.attr.image[MkosiImageInfo]
    if image.uki == None:
        fail("image must provide an unsigned UKI")
    certificate = _single_file(ctx.attr.certificate, "certificate")
    normalized_certificate = ctx.actions.declare_file(ctx.label.name + ".certificate.der")
    request = ctx.actions.declare_file(ctx.label.name + ".secure-boot-request.json")
    request_digest = ctx.actions.declare_file(ctx.label.name + ".secure-boot-request.sha256")
    args = ctx.actions.args()
    args.add(ctx.file._tool.path)
    args.add("request")
    args.add("--openssl", ctx.executable._debian_tools.path)
    args.add("--unsigned-uki", image.uki.path)
    args.add("--certificate", certificate.path)
    args.add("--certificate-output", normalized_certificate.path)
    args.add("--algorithm", ctx.attr.signature_algorithm)
    args.add("--output", request.path)
    args.add("--digest-output", request_digest.path)
    _run(ctx, args, [image.uki, certificate], [request, request_digest, normalized_certificate], "SecureBootSigningRequest")
    return [
        DefaultInfo(files = depset([request, request_digest, image.uki, normalized_certificate])),
        SecureBootSigningRequestInfo(
            certificate = normalized_certificate,
            format_version = "mkosi-secure-boot-signing-request-v2",
            request = request,
            request_digest = request_digest,
            signature_algorithm = ctx.attr.signature_algorithm,
            unsigned_uki = image.uki,
        ),
    ]

# Private attributes of every rule that runs secure_boot.py.
_TOOL_ATTRS = {
    "_tool": attr.label(default = "//mkosi/private:secure_boot.py", allow_single_file = True, cfg = "exec"),
    "_file_hashing": attr.label(default = "//mkosi/private:file_hashing.py", allow_single_file = True, cfg = "exec"),
    "_sibling_loader": attr.label(
        default = "//mkosi/private:sibling_loader.py",
        allow_single_file = True,
        cfg = "exec",
    ),
    "_debian_tools": attr.label(default = "@mkosi_debian_tools//:launcher", executable = True, cfg = "exec"),
}

secure_boot_signing_request = rule(
    implementation = _request_impl,
    attrs = dict({
        "image": attr.label(
            mandatory = True,
            providers = [MkosiImageInfo],
            doc = "mkosi_image with an unsigned UKI.",
        ),
        "certificate": attr.label(
            mandatory = True,
            allow_files = True,
            doc = "Expected signer certificate: a single file or a secure_boot_ephemeral_test_fixture.",
        ),
        "signature_algorithm": attr.string(
            default = "authenticode-sha256",
            values = ["authenticode-sha256"],
            doc = "Required embedded signature algorithm.",
        ),
    }, **_TOOL_ATTRS),
    doc = "Creates a request for an external signer to sign an image's unsigned UKI with the expected certificate.",
    toolchains = [MKOSI_TOOLCHAIN_TYPE],
)

def _import_impl(ctx):
    request = ctx.attr.request[SecureBootSigningRequestInfo]
    signed_input = _single_file(ctx.attr.signed_uki, "signed_uki")
    output = ctx.actions.declare_file(ctx.label.name + ".signed.efi")
    metadata = ctx.actions.declare_file(ctx.label.name + ".secure-boot-verification.json")
    pkcs7 = ctx.actions.declare_file(ctx.label.name + ".authenticode.der")
    content = ctx.actions.declare_file(ctx.label.name + ".authenticode-content")
    verified_signer = ctx.actions.declare_file(ctx.label.name + ".verified-signer.pem")
    expected_pem = ctx.actions.declare_file(ctx.label.name + ".expected-certificate.pem")
    args = ctx.actions.args()
    args.add(ctx.file._tool.path)
    args.add("verify")
    args.add("--openssl", ctx.executable._debian_tools.path)
    args.add("--request", request.request.path)
    args.add("--request-digest", request.request_digest.path)
    args.add("--unsigned-uki", request.unsigned_uki.path)
    args.add("--signed-uki", signed_input.path)
    args.add("--certificate", request.certificate.path)
    args.add("--expected-pem", expected_pem.path)
    args.add("--pkcs7", pkcs7.path)
    args.add("--content", content.path)
    args.add("--verified-signer", verified_signer.path)
    args.add("--output", output.path)
    args.add("--metadata", metadata.path)
    _run(
        ctx,
        args,
        [request.request, request.request_digest, request.unsigned_uki, request.certificate, signed_input],
        [output, metadata, pkcs7, content, verified_signer, expected_pem],
        "SecureBootImportAuthenticode",
    )
    return [
        DefaultInfo(files = depset([output, metadata])),
        SecureBootSignedUkiInfo(
            format_version = "mkosi-secure-boot-signed-uki-v2",
            request = request.request,
            signed_uki = output,
            verification_metadata = metadata,
        ),
    ]

secure_boot_import_response = rule(
    implementation = _import_impl,
    attrs = dict({
        "request": attr.label(
            mandatory = True,
            providers = [SecureBootSigningRequestInfo],
            doc = "The secure_boot_signing_request that the signer answered.",
        ),
        "signed_uki": attr.label(
            mandatory = True,
            allow_files = True,
            doc = "The signed UKI: a single file or a secure_boot_ephemeral_test_fixture.",
        ),
    }, **_TOOL_ATTRS),
    doc = """Imports an externally signed UKI.

The import fails unless the UKI embeds an Authenticode signature by the requested certificate and is otherwise
equivalent to the requested unsigned UKI.""",
    toolchains = [MKOSI_TOOLCHAIN_TYPE],
)

def _fixture_impl(ctx):
    unsigned = ctx.file.unsigned_uki
    certificate = ctx.actions.declare_file(ctx.label.name + ".certificate.pem")
    signed = ctx.actions.declare_file(ctx.label.name + ".signed.efi")
    scratch = signed.dirname + "/." + ctx.label.name + "-private"
    args = ctx.actions.args()
    args.add(ctx.file._tool.path)
    args.add("ephemeral-fixture")
    args.add("--openssl", ctx.executable._debian_tools.path)
    args.add("--sbsign", ctx.executable._debian_tools.path)
    args.add("--unsigned-uki", unsigned.path)
    args.add("--certificate", certificate.path)
    args.add("--signed-uki", signed.path)
    args.add("--scratch", scratch)
    _run(
        ctx,
        args,
        [unsigned],
        [certificate, signed],
        "SecureBootEphemeralFixture",
        execution_requirements = _EPHEMERAL_EXECUTION_REQUIREMENTS,
    )
    return [
        DefaultInfo(files = depset([certificate, signed])),
        SecureBootEphemeralTestFixtureInfo(
            certificate = certificate,
            execution_requirements = _EPHEMERAL_EXECUTION_REQUIREMENTS,
            signed_uki = signed,
        ),
    ]

secure_boot_ephemeral_test_fixture = rule(
    implementation = _fixture_impl,
    attrs = dict({
        "unsigned_uki": attr.label(mandatory = True, allow_single_file = True, doc = "The UKI to sign."),
    }, **_TOOL_ATTRS),
    doc = "For tests: signs a UKI with a throwaway key that never leaves the action, and outputs its certificate.",
    toolchains = [MKOSI_TOOLCHAIN_TYPE],
)
