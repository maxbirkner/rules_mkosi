"""Offline Authenticode Secure Boot rules."""

load("//mkosi/private:mkosi_image.bzl", "MkosiImageInfo")

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

def _python(ctx):
    return ctx.toolchains["//mkosi/toolchain:toolchain_type"].mkosi

def _run(ctx, args, inputs, outputs, mnemonic, requirements = {}):
    python = _python(ctx)
    ctx.actions.run(
        executable = python.python,
        arguments = [args],
        inputs = depset(inputs, transitive = [python.python_runtime_files]),
        tools = [python.python_files_to_run],
        outputs = outputs,
        mnemonic = mnemonic,
        env = {"PATH": "", "PYTHONNOUSERSITE": "1"},
        execution_requirements = requirements,
    )

def _certificate(target):
    if SecureBootEphemeralTestFixtureInfo in target:
        return target[SecureBootEphemeralTestFixtureInfo].certificate
    files = target.files.to_list()
    if len(files) != 1:
        fail("certificate must provide one File or SecureBootEphemeralTestFixtureInfo")
    return files[0]

def _signed_uki(target):
    if SecureBootEphemeralTestFixtureInfo in target:
        return target[SecureBootEphemeralTestFixtureInfo].signed_uki
    files = target.files.to_list()
    if len(files) != 1:
        fail("signed_uki must provide one File or SecureBootEphemeralTestFixtureInfo")
    return files[0]

def _request_impl(ctx):
    image = ctx.attr.image[MkosiImageInfo]
    if image.uki == None:
        fail("image must provide an unsigned UKI")
    certificate = _certificate(ctx.attr.certificate)
    request = ctx.actions.declare_file(ctx.label.name + ".secure-boot-request.json")
    request_digest = ctx.actions.declare_file(ctx.label.name + ".secure-boot-request.sha256")
    args = ctx.actions.args()
    args.add(ctx.file._tool.path)
    args.add("request")
    args.add("--openssl", ctx.executable._debian_tools.path)
    args.add("--unsigned-uki", image.uki.path)
    args.add("--certificate", certificate.path)
    args.add("--algorithm", ctx.attr.signature_algorithm)
    args.add("--output", request.path)
    args.add("--digest-output", request_digest.path)
    _run(ctx, args, [ctx.file._tool, ctx.executable._debian_tools, image.uki, certificate], [request, request_digest], "SecureBootSigningRequest")
    return [
        DefaultInfo(files = depset([request, request_digest, image.uki, certificate])),
        SecureBootSigningRequestInfo(
            certificate = certificate,
            format_version = "mkosi-secure-boot-signing-request-v2",
            request = request,
            request_digest = request_digest,
            signature_algorithm = ctx.attr.signature_algorithm,
            unsigned_uki = image.uki,
        ),
    ]

secure_boot_signing_request = rule(
    implementation = _request_impl,
    attrs = {
        "image": attr.label(mandatory = True, providers = [MkosiImageInfo]),
        "certificate": attr.label(mandatory = True, allow_files = True),
        "signature_algorithm": attr.string(default = "authenticode-sha256", values = ["authenticode-sha256"]),
        "_tool": attr.label(default = "//mkosi/private:secure_boot.py", allow_single_file = True, cfg = "exec"),
        "_debian_tools": attr.label(default = "@mkosi_debian_tools//:launcher", executable = True, cfg = "exec"),
    },
    doc = "Creates a cacheable unsigned-UKI and expected-certificate signing request.",
    toolchains = ["//mkosi/toolchain:toolchain_type"],
)

def _import_impl(ctx):
    request = ctx.attr.request[SecureBootSigningRequestInfo]
    signed_input = _signed_uki(ctx.attr.signed_uki)
    output = ctx.actions.declare_file(ctx.label.name + ".signed.efi")
    metadata = ctx.actions.declare_file(ctx.label.name + ".secure-boot-verification.json")
    pkcs7 = ctx.actions.declare_file(ctx.label.name + ".authenticode.der")
    content = ctx.actions.declare_file(ctx.label.name + ".authenticode-content")
    args = ctx.actions.args()
    args.add(ctx.file._tool.path)
    args.add("verify")
    args.add("--openssl", ctx.executable._debian_tools.path)
    args.add("--request", request.request.path)
    args.add("--request-digest", request.request_digest.path)
    args.add("--unsigned-uki", request.unsigned_uki.path)
    args.add("--signed-uki", signed_input.path)
    args.add("--certificate", request.certificate.path)
    args.add("--pkcs7", pkcs7.path)
    args.add("--content", content.path)
    args.add("--output", output.path)
    args.add("--metadata", metadata.path)
    _run(
        ctx,
        args,
        [ctx.file._tool, ctx.executable._debian_tools, request.request, request.request_digest, request.unsigned_uki, request.certificate, signed_input],
        [output, metadata, pkcs7, content],
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
    attrs = {
        "request": attr.label(mandatory = True, providers = [SecureBootSigningRequestInfo]),
        "signed_uki": attr.label(mandatory = True, allow_files = True),
        "_tool": attr.label(default = "//mkosi/private:secure_boot.py", allow_single_file = True, cfg = "exec"),
        "_debian_tools": attr.label(default = "@mkosi_debian_tools//:launcher", executable = True, cfg = "exec"),
    },
    doc = "Imports only an embedded Authenticode-signed UKI equivalent to its request.",
    toolchains = ["//mkosi/toolchain:toolchain_type"],
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
    _run(ctx, args, [ctx.file._tool, ctx.executable._debian_tools, unsigned], [certificate, signed], "SecureBootEphemeralFixture", {
        "local": "1",
        "no-cache": "1",
        "no-remote": "1",
        "no-remote-cache": "1",
        "no-remote-exec": "1",
    })
    return [
        DefaultInfo(files = depset([certificate, signed])),
        SecureBootEphemeralTestFixtureInfo(
            certificate = certificate,
            execution_requirements = {
                "local": "1",
                "no-cache": "1",
                "no-remote": "1",
                "no-remote-cache": "1",
                "no-remote-exec": "1",
            },
            signed_uki = signed,
        ),
    ]

secure_boot_ephemeral_test_fixture = rule(
    implementation = _fixture_impl,
    attrs = {
        "unsigned_uki": attr.label(mandatory = True, allow_single_file = True),
        "_tool": attr.label(default = "//mkosi/private:secure_boot.py", allow_single_file = True, cfg = "exec"),
        "_debian_tools": attr.label(default = "@mkosi_debian_tools//:launcher", executable = True, cfg = "exec"),
    },
    doc = "Creates only public outputs while its ephemeral key remains action-private.",
    toolchains = ["//mkosi/toolchain:toolchain_type"],
)
