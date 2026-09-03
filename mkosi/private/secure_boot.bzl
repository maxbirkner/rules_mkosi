"""Offline Secure Boot signing request, response, and assembly rules."""

load("//mkosi/private:mkosi_image.bzl", "MkosiImageInfo")

SecureBootSigningRequestInfo = provider(
    doc = "Typed immutable request for an external Secure Boot signer.",
    fields = {
        "format_version": "Request schema, currently mkosi-secure-boot-signing-request-v1.",
        "request": "Canonical JSON request File.",
        "unsigned_uki": "Unsigned UKI File bound by the request digest.",
        "certificate": "Public signing certificate File bound by SHA-256.",
        "signature_algorithm": "Requested signature algorithm.",
    },
)

SecureBootSignedUkiInfo = provider(
    doc = "Verified externally signed UKI and audit metadata.",
    fields = {
        "format_version": "Provider schema, currently mkosi-secure-boot-signed-uki-v1.",
        "signed_uki": "Externally assembled signed UKI.",
        "verification_metadata": "Signature and certificate binding metadata.",
        "request": "The verified request artifact.",
    },
)

SecureBootTestKeyInfo = provider(
    doc = "Ephemeral non-production key pair for tests only.",
    fields = {
        "certificate": "Ephemeral public certificate.",
        "private_key": "Ephemeral private key; intentionally absent from DefaultInfo.",
    },
)

SecureBootTestResponseInfo = provider(
    doc = "Test-only detached response artifacts.",
    fields = {
        "response": "Canonical response manifest.",
        "signature": "Detached response signature.",
        "signed_uki": "Synthetic signed UKI input.",
    },
)

def _tool(ctx):
    return ctx.toolchains["//mkosi/toolchain:toolchain_type"].mkosi

def _run(ctx, arguments, inputs, outputs, mnemonic, requirements = {}):
    tool = _tool(ctx)
    ctx.actions.run(
        executable = tool.python,
        arguments = [arguments],
        inputs = depset(inputs, transitive = [tool.python_runtime_files]),
        tools = [tool.python_files_to_run],
        outputs = outputs,
        mnemonic = mnemonic,
        env = {"PATH": "", "PYTHONNOUSERSITE": "1"},
        execution_requirements = requirements,
    )

def _request_impl(ctx):
    image = ctx.attr.image[MkosiImageInfo]
    if image.uki == None:
        fail("image must provide an unsigned UKI")
    output = ctx.actions.declare_file(ctx.label.name + ".secure-boot-request.json")
    args = ctx.actions.args()
    args.add(ctx.file._tool.path)
    args.add("request")
    args.add("--openssl", ctx.executable._openssl.path)
    args.add("--unsigned-uki", image.uki.path)
    args.add("--certificate", ctx.file.certificate.path)
    args.add("--algorithm", ctx.attr.signature_algorithm)
    args.add("--output", output.path)
    _run(ctx, args, [ctx.file._tool, ctx.executable._openssl, image.uki, ctx.file.certificate], [output], "SecureBootSigningRequest")
    return [
        DefaultInfo(files = depset([output, image.uki, ctx.file.certificate])),
        SecureBootSigningRequestInfo(
            certificate = ctx.file.certificate,
            format_version = "mkosi-secure-boot-signing-request-v1",
            request = output,
            signature_algorithm = ctx.attr.signature_algorithm,
            unsigned_uki = image.uki,
        ),
    ]

secure_boot_signing_request = rule(
    implementation = _request_impl,
    attrs = {
        "image": attr.label(mandatory = True, providers = [MkosiImageInfo]),
        "certificate": attr.label(mandatory = True, allow_single_file = True),
        "signature_algorithm": attr.string(default = "rsa-pkcs1-sha256", values = ["rsa-pkcs1-sha256"]),
        "_tool": attr.label(default = "//mkosi/private:secure_boot.py", allow_single_file = True, cfg = "exec"),
        "_openssl": attr.label(default = "@mkosi_debian_tools//:launcher", executable = True, cfg = "exec"),
    },
    doc = "Creates a cacheable request containing the unsigned UKI digest and public signing parameters.",
    toolchains = ["//mkosi/toolchain:toolchain_type"],
)

def _import_impl(ctx):
    request = ctx.attr.request[SecureBootSigningRequestInfo]
    output = ctx.actions.declare_file(ctx.label.name + ".signed.efi")
    metadata = ctx.actions.declare_file(ctx.label.name + ".secure-boot-verification.json")
    public_key = ctx.actions.declare_file(ctx.label.name + ".public.pem")
    args = ctx.actions.args()
    args.add(ctx.file._tool.path)
    args.add("verify")
    args.add("--openssl", ctx.executable._openssl.path)
    args.add("--request", request.request.path)
    args.add("--response", ctx.file.response.path)
    args.add("--signed-uki", ctx.file.signed_uki.path)
    args.add("--signature", ctx.file.signature.path)
    args.add("--certificate", ctx.file.certificate.path)
    args.add("--public-key", public_key.path)
    args.add("--output", output.path)
    args.add("--metadata", metadata.path)
    _run(
        ctx,
        args,
        [ctx.file._tool, ctx.executable._openssl, request.request, ctx.file.response, ctx.file.signed_uki, ctx.file.signature, ctx.file.certificate],
        [output, metadata, public_key],
        "SecureBootImportResponse",
    )
    return [
        DefaultInfo(files = depset([output, metadata])),
        SecureBootSignedUkiInfo(
            format_version = "mkosi-secure-boot-signed-uki-v1",
            request = request.request,
            signed_uki = output,
            verification_metadata = metadata,
        ),
    ]

secure_boot_import_response = rule(
    implementation = _import_impl,
    attrs = {
        "request": attr.label(mandatory = True, providers = [SecureBootSigningRequestInfo]),
        "response": attr.label(mandatory = True, allow_single_file = True),
        "signed_uki": attr.label(mandatory = True, allow_single_file = True),
        "signature": attr.label(mandatory = True, allow_single_file = True),
        "certificate": attr.label(mandatory = True, allow_single_file = True),
        "_tool": attr.label(default = "//mkosi/private:secure_boot.py", allow_single_file = True, cfg = "exec"),
        "_openssl": attr.label(default = "@mkosi_debian_tools//:launcher", executable = True, cfg = "exec"),
    },
    doc = "Verifies an offline response's request, UKI, signature, and certificate binding before import.",
    toolchains = ["//mkosi/toolchain:toolchain_type"],
)

def _test_key_impl(ctx):
    key = ctx.actions.declare_file(ctx.label.name + ".private.pem")
    certificate = ctx.actions.declare_file(ctx.label.name + ".certificate.pem")
    args = ctx.actions.args()
    args.add(ctx.file._tool.path)
    args.add("test-key")
    args.add("--openssl", ctx.executable._openssl.path)
    args.add("--private-key", key.path)
    args.add("--certificate", certificate.path)
    _run(ctx, args, [ctx.file._tool, ctx.executable._openssl], [key, certificate], "SecureBootEphemeralTestKey", {
        "local": "1",
        "no-cache": "1",
        "no-remote": "1",
        "no-remote-cache": "1",
        "no-remote-exec": "1",
    })
    return [
        DefaultInfo(files = depset([certificate])),
        SecureBootTestKeyInfo(certificate = certificate, private_key = key),
    ]

secure_boot_ephemeral_test_key = rule(
    implementation = _test_key_impl,
    attrs = {
        "_tool": attr.label(default = "//mkosi/private:secure_boot.py", allow_single_file = True, cfg = "exec"),
        "_openssl": attr.label(default = "@mkosi_debian_tools//:launcher", executable = True, cfg = "exec"),
    },
    doc = "Generates a local, non-cacheable, non-production key whose secret is excluded from DefaultInfo.",
    toolchains = ["//mkosi/toolchain:toolchain_type"],
)

def _test_response_impl(ctx):
    request = ctx.attr.request[SecureBootSigningRequestInfo]
    key = ctx.attr.key[SecureBootTestKeyInfo]
    response = ctx.actions.declare_file(ctx.label.name + ".response.json")
    signature = ctx.actions.declare_file(ctx.label.name + ".response.sig")
    args = ctx.actions.args()
    args.add(ctx.file._tool.path)
    args.add("test-response")
    args.add("--openssl", ctx.executable._openssl.path)
    args.add("--request", request.request.path)
    args.add("--signed-uki", ctx.file.signed_uki.path)
    args.add("--private-key", key.private_key.path)
    args.add("--output", response.path)
    args.add("--signature", signature.path)
    _run(ctx, args, [ctx.file._tool, ctx.executable._openssl, request.request, ctx.file.signed_uki, key.private_key], [response, signature], "SecureBootEphemeralTestResponse", {
        "local": "1",
        "no-cache": "1",
        "no-remote": "1",
        "no-remote-cache": "1",
        "no-remote-exec": "1",
    })
    return [
        DefaultInfo(files = depset([response, signature])),
        SecureBootTestResponseInfo(response = response, signature = signature, signed_uki = ctx.file.signed_uki),
    ]

secure_boot_ephemeral_test_response = rule(
    implementation = _test_response_impl,
    attrs = {
        "request": attr.label(mandatory = True, providers = [SecureBootSigningRequestInfo]),
        "key": attr.label(mandatory = True, providers = [SecureBootTestKeyInfo]),
        "signed_uki": attr.label(mandatory = True, allow_single_file = True),
        "_tool": attr.label(default = "//mkosi/private:secure_boot.py", allow_single_file = True, cfg = "exec"),
        "_openssl": attr.label(default = "@mkosi_debian_tools//:launcher", executable = True, cfg = "exec"),
    },
    doc = "Signs a response with an ephemeral test key under local/no-cache execution.",
    toolchains = ["//mkosi/toolchain:toolchain_type"],
)
