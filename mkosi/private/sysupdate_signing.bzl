"""Offline OpenPGP signatures of sysupdate payload manifests (SHA256SUMS.gpg)."""

load("//mkosi/private:python_action.bzl", "MKOSI_TOOLCHAIN_TYPE", "run_python")
load("//mkosi/private:secure_boot.bzl", "EPHEMERAL_EXECUTION_REQUIREMENTS")
load("//mkosi/private:sysupdate.bzl", "SysupdatePayloadInfo")

SysupdateSigningRequestInfo = provider(
    doc = "Request for an external signer to sign the SHA256SUMS manifest of a sysupdate payload.",
    fields = {
        "format_version": "Request schema, mkosi-sysupdate-signing-request-v1.",
        "manifest": "Exact SHA256SUMS to sign.",
        "payload": "SysupdatePayloadInfo of the unsigned payload.",
        "public_key": "Expected signer certificate as a binary OpenPGP transferable public key.",
        "request": "JSON request binding the manifest digest to the signer fingerprint.",
    },
)

SysupdateEphemeralTestFixtureInfo = provider(
    doc = "Public outputs from one action-private ephemeral OpenPGP signing operation.",
    fields = {
        "execution_requirements": "No-remote, no-cache action policy.",
        "keyring": "Directory holding the certificate as import-pubring.gpg, for a guest's systemd keyring.",
        "public_key": "Binary OpenPGP certificate of the ephemeral key.",
        "signatures": "Detached signatures of the payloads' SHA256SUMS.",
    },
)

_TOOL_ATTRS = {
    "_debian_tools": attr.label(default = "@mkosi_debian_tools//:launcher", executable = True, cfg = "exec"),
    "_launcher_tool": attr.label(
        default = "//mkosi/private:launcher_tool.py",
        allow_single_file = True,
        cfg = "exec",
    ),
    "_openpgp": attr.label(default = "//mkosi/private:openpgp.py", allow_single_file = True, cfg = "exec"),
    "_sibling_loader": attr.label(
        default = "//mkosi/private:sibling_loader.py",
        allow_single_file = True,
        cfg = "exec",
    ),
    "_tool": attr.label(default = "//mkosi/private:sysupdate_signing.py", allow_single_file = True, cfg = "exec"),
}

def _run(ctx, args, inputs, outputs, mnemonic, **kwargs):
    run_python(
        ctx,
        arguments = [args],
        inputs = [ctx.file._tool, ctx.file._launcher_tool, ctx.file._openpgp, ctx.file._sibling_loader] + inputs,
        outputs = outputs,
        mnemonic = mnemonic,
        tools = [ctx.attr._debian_tools[DefaultInfo].files_to_run],
        # Without a sandbox, loading the helper modules must not write a __pycache__ into the sources.
        env = {"PYTHONDONTWRITEBYTECODE": "1"},
        **kwargs
    )

def _single_file(target, attribute, fixture_field):
    """Returns the files of a fixture's field, or the single file of the attribute."""
    if SysupdateEphemeralTestFixtureInfo in target:
        value = getattr(target[SysupdateEphemeralTestFixtureInfo], fixture_field)
        return value if type(value) == "list" else [value]
    files = target.files.to_list()
    if len(files) != 1:
        fail("%s must provide one File or SysupdateEphemeralTestFixtureInfo" % attribute)
    return files

def _request_impl(ctx):
    payload = ctx.attr.payload[SysupdatePayloadInfo]
    if getattr(payload, "signature", None):
        fail("payload must be an unsigned sysupdate_payload")
    public_key = _single_file(ctx.attr.public_key, "public_key", "public_key")[0]
    outputs = {
        option: ctx.actions.declare_file("%s/%s" % (ctx.label.name, basename))
        for option, basename in (
            ("--manifest-output", "SHA256SUMS"),
            ("--public-key-output", "signer.pgp"),
            ("--output", "request.json"),
        )
    }
    args = ctx.actions.args()
    args.add(ctx.file._tool)
    args.add("request")
    args.add("--payload", payload.directory.path)
    args.add("--public-key", public_key)
    for option, file in outputs.items():
        args.add(option, file)
    _run(ctx, args, [payload.directory, public_key], outputs.values(), "SysupdateSigningRequest")
    return [
        DefaultInfo(files = depset(outputs.values())),
        SysupdateSigningRequestInfo(
            format_version = "mkosi-sysupdate-signing-request-v1",
            manifest = outputs["--manifest-output"],
            payload = payload,
            public_key = outputs["--public-key-output"],
            request = outputs["--output"],
        ),
    ]

sysupdate_signing_request = rule(
    implementation = _request_impl,
    attrs = {
        "payload": attr.label(
            mandatory = True,
            providers = [SysupdatePayloadInfo],
            doc = "The sysupdate_payload whose SHA256SUMS the signer signs.",
        ),
        "public_key": attr.label(
            mandatory = True,
            allow_files = True,
            doc = """Expected signer: one OpenPGP certificate (transferable public key, binary or ASCII-armored), or a
sysupdate_ephemeral_test_fixture. Secret keys are rejected.""",
        ),
    } | _TOOL_ATTRS,
    doc = """Creates a request for an external signer to sign the SHA256SUMS of a payload with the expected key.

The outputs are SHA256SUMS, the normalized binary certificate signer.pgp, and request.json, which binds the SHA-256 of
SHA256SUMS, the payload files it lists, and the signer's fingerprint.""",
    toolchains = [MKOSI_TOOLCHAIN_TYPE],
)

def _import_impl(ctx):
    request = ctx.attr.request[SysupdateSigningRequestInfo]
    candidates = _single_file(ctx.attr.signature, "signature", "signatures")
    output = ctx.actions.declare_file(ctx.label.name + "/SHA256SUMS.gpg")
    args = ctx.actions.args()
    args.add(ctx.file._tool)
    args.add("verify")
    args.add("--sqv", ctx.executable._debian_tools)
    args.add("--request", request.request)
    args.add("--manifest", request.manifest)
    args.add("--public-key", request.public_key)
    args.add_all(candidates, before_each = "--signature")
    args.add("--output", output)
    _run(
        ctx,
        args,
        [request.request, request.manifest, request.public_key] + candidates,
        [output],
        "SysupdateImportSignature",
    )
    payload = request.payload
    return [
        DefaultInfo(files = depset([payload.directory, output])),
        SysupdatePayloadInfo(
            directory = payload.directory,
            image_id = payload.image_id,
            image_version = payload.image_version,
            image_version_file = payload.image_version_file,
            signature = output,
        ),
    ]

sysupdate_import_signature = rule(
    implementation = _import_impl,
    attrs = {
        "request": attr.label(
            mandatory = True,
            providers = [SysupdateSigningRequestInfo],
            doc = "The sysupdate_signing_request that the signer answered.",
        ),
        "signature": attr.label(
            mandatory = True,
            allow_files = True,
            doc = """The detached signature returned by the signer (binary or ASCII-armored), or a
sysupdate_ephemeral_test_fixture.""",
        ),
    } | _TOOL_ATTRS,
    doc = """Imports an externally created SHA256SUMS.gpg for a payload.

The import fails unless sqv verifies the signature over the requested SHA256SUMS with the requested certificate. It
returns the payload's SysupdatePayloadInfo with signature set; publish the payload directory and SHA256SUMS.gpg side
by side.""",
    toolchains = [MKOSI_TOOLCHAIN_TYPE],
)

def _fixture_impl(ctx):
    if not ctx.attr.payloads:
        fail("payloads must name at least one sysupdate_payload")
    public_key = ctx.actions.declare_file(ctx.label.name + ".pgp")
    keyring = ctx.actions.declare_directory(ctx.label.name + ".keyring")
    signatures = []
    args = ctx.actions.args()
    args.add(ctx.file._tool)
    args.add("ephemeral-fixture")
    args.add("--openssl", ctx.executable._debian_tools)
    args.add("--public-key", public_key)
    args.add("--keyring-dir", keyring.path)
    args.add("--scratch", public_key.dirname + "/." + ctx.label.name + "-private")
    for index, target in enumerate(ctx.attr.payloads):
        signature = ctx.actions.declare_file("%s.signatures/%d.gpg" % (ctx.label.name, index))
        signatures.append(signature)
        args.add_all("--sign", [target[SysupdatePayloadInfo].directory.path, signature])
    _run(
        ctx,
        args,
        [target[SysupdatePayloadInfo].directory for target in ctx.attr.payloads],
        [public_key, keyring] + signatures,
        "SysupdateEphemeralFixture",
        execution_requirements = EPHEMERAL_EXECUTION_REQUIREMENTS,
    )
    return [
        DefaultInfo(files = depset([public_key, keyring] + signatures)),
        OutputGroupInfo(keyring = depset([keyring])),
        SysupdateEphemeralTestFixtureInfo(
            execution_requirements = EPHEMERAL_EXECUTION_REQUIREMENTS,
            keyring = keyring,
            public_key = public_key,
            signatures = signatures,
        ),
    ]

sysupdate_ephemeral_test_fixture = rule(
    implementation = _fixture_impl,
    attrs = {
        "payloads": attr.label_list(
            mandatory = True,
            providers = [SysupdatePayloadInfo],
            doc = "Payloads whose SHA256SUMS the fixture signs.",
        ),
    } | _TOOL_ATTRS,
    doc = """For tests: signs the SHA256SUMS of payloads with a throwaway OpenPGP key. No key leaves the action.

Use the fixture as both the public_key of sysupdate_signing_request and the signature of sysupdate_import_signature;
the import selects the fixture's signature that verifies. The output group 'keyring' holds a directory with the
certificate as import-pubring.gpg, which a test can share with a guest.""",
    toolchains = [MKOSI_TOOLCHAIN_TYPE],
)
