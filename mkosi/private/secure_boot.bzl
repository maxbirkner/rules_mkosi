"""Offline Authenticode Secure Boot rules."""

load("//mkosi/private:mkosi_action.bzl", "mkosi_execution_requirements")
load("//mkosi/private:mkosi_image.bzl", "MkosiImageInfo")
load("//mkosi/private:python_action.bzl", "MKOSI_TOOLCHAIN_TYPE", "run_python")

SecureBootSigningRequestInfo = provider(
    doc = "Typed immutable request for an external Secure Boot signer.",
    fields = {
        "certificate": "Expected public signer certificate.",
        "esp_path": "ESP path of the requested binary, or the empty string for the image's UKI.",
        "format_version": "Request schema, mkosi-secure-boot-signing-request-v3.",
        "request": "Canonical JSON request.",
        "request_digest": "Canonical request SHA-256.",
        "signature_algorithm": "Required embedded Authenticode algorithm.",
        "unsigned_binary": "Exact unsigned PE/COFF binary bound by the request.",
    },
)

SecureBootSignedBinaryInfo = provider(
    doc = "Authenticode-verified, firmware-consumable PE/COFF binary: a UKI or a boot binary from an image's ESP.",
    fields = {
        "certificate": "DER certificate that signed the binary.",
        "esp_path": "ESP path of the binary, or the empty string for a UKI.",
        "format_version": "Provider schema, mkosi-secure-boot-signed-binary-v3.",
        "request": "Verified request.",
        "signed_binary": "Verified signed PE/COFF binary.",
        "verification_metadata": "Verification and equivalence metadata.",
    },
)

SecureBootEphemeralTestFixtureInfo = provider(
    doc = "Public outputs from one action-private ephemeral signing operation.",
    fields = {
        "auto_enroll_keys": "PK.auth (self-signed), KEK.auth (signed by PK) and db.auth (signed by KEK) of the keys.",
        "certificate": "Ephemeral public certificate.",
        "execution_requirements": "No-remote, no-cache action policy.",
        "signed_binaries": "Authenticode-signed test binaries, one per requested UKI and ESP file.",
    },
)

# Ephemeral test fixtures run on the local machine, sandboxed where the strategy allows, and their outputs are never
# cached.
EPHEMERAL_EXECUTION_REQUIREMENTS = {
    "no-cache": "1",
    "no-remote": "1",
    "no-remote-cache": "1",
    "no-remote-exec": "1",
}

def _run(ctx, args, inputs, outputs, mnemonic, **kwargs):
    run_python(
        ctx,
        arguments = [args],
        inputs = [
            ctx.file._tool,
            ctx.file._efi_auth,
            ctx.file._esp_files,
            ctx.file._file_hashing,
            ctx.file._gpt_partitions,
            ctx.file._launcher_tool,
            ctx.file._sibling_loader,
        ] + inputs,
        outputs = outputs,
        mnemonic = mnemonic,
        tools = [ctx.attr._debian_tools[DefaultInfo].files_to_run],
        # Without a sandbox, loading the helper modules must not write a __pycache__ into the sources.
        env = {"PYTHONDONTWRITEBYTECODE": "1"},
        **kwargs
    )

def _extract_esp_file(ctx, image, esp_path, output):
    """Registers the action that copies esp_path from the ESP of image to output.

    Args:
      ctx: Rule context with _TOOL_ATTRS.
      image: MkosiImageInfo of a UEFI release image.
      esp_path: Validated relative path of a PE/COFF file on the ESP.
      output: Declared output File.
    """
    if image.partition_metadata == None:
        fail("image must be a release image with partition metadata to read files from its ESP")
    args = ctx.actions.args()
    args.add(ctx.file._tool.path)
    args.add("extract")
    args.add("--mtools", ctx.executable._debian_tools.path)
    args.add("--image", image.raw_image.path)
    args.add("--partition-metadata", image.partition_metadata.path)
    args.add("--esp-path", esp_path)
    args.add("--scratch", output.path + ".scratch")
    args.add("--output", output.path)
    _run(
        ctx,
        args,
        [image.raw_image, image.partition_metadata],
        [output],
        "SecureBootExtractEspFile",
        execution_requirements = mkosi_execution_requirements(True, offline = True),
        progress_message = "Extracting %s from the ESP of %%{label}" % esp_path,
    )

_ESP_PATH_CHARACTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._+-"

def _validate_esp_path(esp_path):
    for component in esp_path.split("/"):
        if not component or not component[0].isalnum() or component.strip(_ESP_PATH_CHARACTERS):
            fail(
                ("esp_path %r must be a relative path whose components start with a letter or digit and contain " +
                 "only letters, digits, '.', '_', '+' and '-'") % esp_path,
            )

def _unsigned_binary(ctx, image, esp_path, name):
    """Returns the image's UKI for an empty esp_path, or a new action's copy of the ESP file."""
    if not esp_path:
        if image.uki == None:
            fail("image must provide an unsigned UKI")
        return image.uki
    _validate_esp_path(esp_path)
    output = ctx.actions.declare_file(name)
    _extract_esp_file(ctx, image, esp_path, output)
    return output

def _certificate_file(target):
    """Returns the certificate file of the attribute, or the certificate of a test fixture."""
    if SecureBootEphemeralTestFixtureInfo in target:
        return target[SecureBootEphemeralTestFixtureInfo].certificate
    files = target.files.to_list()
    if len(files) != 1:
        fail("certificate must provide one File or SecureBootEphemeralTestFixtureInfo")
    return files[0]

def _signed_candidates(target):
    """Returns the signed binary of the attribute, or every binary that a test fixture signed."""
    if SecureBootEphemeralTestFixtureInfo in target:
        return target[SecureBootEphemeralTestFixtureInfo].signed_binaries
    files = target.files.to_list()
    if len(files) != 1:
        fail("signed_binary must provide one File or SecureBootEphemeralTestFixtureInfo")
    return files

def _request_impl(ctx):
    image = ctx.attr.image[MkosiImageInfo]
    unsigned = _unsigned_binary(ctx, image, ctx.attr.esp_path, ctx.label.name + ".unsigned.efi")
    certificate = _certificate_file(ctx.attr.certificate)
    normalized_certificate = ctx.actions.declare_file(ctx.label.name + ".certificate.der")
    request = ctx.actions.declare_file(ctx.label.name + ".secure-boot-request.json")
    request_digest = ctx.actions.declare_file(ctx.label.name + ".secure-boot-request.sha256")
    args = ctx.actions.args()
    args.add(ctx.file._tool.path)
    args.add("request")
    args.add("--openssl", ctx.executable._debian_tools.path)
    args.add("--unsigned", unsigned.path)
    args.add("--esp-path", ctx.attr.esp_path)
    args.add("--certificate", certificate.path)
    args.add("--certificate-output", normalized_certificate.path)
    args.add("--algorithm", ctx.attr.signature_algorithm)
    args.add("--output", request.path)
    args.add("--digest-output", request_digest.path)
    _run(ctx, args, [unsigned, certificate], [request, request_digest, normalized_certificate], "SecureBootSigningRequest")
    return [
        DefaultInfo(files = depset([request, request_digest, unsigned, normalized_certificate])),
        SecureBootSigningRequestInfo(
            certificate = normalized_certificate,
            esp_path = ctx.attr.esp_path,
            format_version = "mkosi-secure-boot-signing-request-v3",
            request = request,
            request_digest = request_digest,
            signature_algorithm = ctx.attr.signature_algorithm,
            unsigned_binary = unsigned,
        ),
    ]

# Private attributes of every rule that runs secure_boot.py.
_TOOL_ATTRS = {
    "_debian_tools": attr.label(default = "@mkosi_debian_tools//:launcher", executable = True, cfg = "exec"),
    "_efi_auth": attr.label(default = "//mkosi/private:efi_auth.py", allow_single_file = True, cfg = "exec"),
    "_esp_files": attr.label(default = "//mkosi/private:esp_files.py", allow_single_file = True, cfg = "exec"),
    "_file_hashing": attr.label(default = "//mkosi/private:file_hashing.py", allow_single_file = True, cfg = "exec"),
    "_gpt_partitions": attr.label(
        default = "//mkosi/private:gpt_partitions.py",
        allow_single_file = True,
        cfg = "exec",
    ),
    "_launcher_tool": attr.label(
        default = "//mkosi/private:launcher_tool.py",
        allow_single_file = True,
        cfg = "exec",
    ),
    "_sibling_loader": attr.label(
        default = "//mkosi/private:sibling_loader.py",
        allow_single_file = True,
        cfg = "exec",
    ),
    "_tool": attr.label(default = "//mkosi/private:secure_boot.py", allow_single_file = True, cfg = "exec"),
}

secure_boot_signing_request = rule(
    implementation = _request_impl,
    attrs = dict({
        "certificate": attr.label(
            mandatory = True,
            allow_files = True,
            doc = "Expected signer certificate: a single file or a secure_boot_ephemeral_test_fixture.",
        ),
        "esp_path": attr.string(
            doc = """Path of the PE/COFF binary to sign on the image's ESP, such as EFI/systemd/systemd-bootx64.efi.

Empty, the default, requests the image's unsigned UKI. Any other value requires a release image, whose ESP the request
reads the binary from.""",
        ),
        "image": attr.label(
            mandatory = True,
            providers = [MkosiImageInfo],
            doc = "UEFI release mkosi_image with an unsigned UKI.",
        ),
        "signature_algorithm": attr.string(
            default = "authenticode-sha256",
            values = ["authenticode-sha256"],
            doc = "Required embedded signature algorithm.",
        ),
    }, **_TOOL_ATTRS),
    doc = """Creates a request for an external signer to sign one PE/COFF binary of an image with the expected
certificate: the image's unsigned UKI, or a boot binary on its ESP such as systemd-boot.""",
    toolchains = [MKOSI_TOOLCHAIN_TYPE],
)

def _verify_arguments(ctx, request, candidates, outputs):
    """Returns the arguments of secure_boot.py verify, which writes outputs keyed by their option."""
    args = ctx.actions.args()
    args.add(ctx.file._tool.path)
    args.add("verify")
    args.add("--openssl", ctx.executable._debian_tools.path)
    args.add("--request", request.request.path)
    args.add("--request-digest", request.request_digest.path)
    args.add("--unsigned", request.unsigned_binary.path)
    args.add_all(candidates, before_each = "--signed")
    args.add("--certificate", request.certificate.path)
    for option, file in outputs.items():
        args.add(option, file.path)
    return args

def _import_impl(ctx):
    request = ctx.attr.request[SecureBootSigningRequestInfo]
    candidates = _signed_candidates(ctx.attr.signed_binary)
    outputs = {
        option: ctx.actions.declare_file(ctx.label.name + suffix)
        for option, suffix in (
            ("--output", ".signed.efi"),
            ("--metadata", ".secure-boot-verification.json"),
            ("--pkcs7", ".authenticode.der"),
            ("--content", ".authenticode-content"),
            ("--verified-signer", ".verified-signer.pem"),
            ("--expected-pem", ".expected-certificate.pem"),
        )
    }
    output = outputs["--output"]
    metadata = outputs["--metadata"]
    _run(
        ctx,
        _verify_arguments(ctx, request, candidates, outputs),
        [request.request, request.request_digest, request.unsigned_binary, request.certificate] + candidates,
        outputs.values(),
        "SecureBootImportAuthenticode",
    )
    return [
        DefaultInfo(files = depset([output, metadata])),
        SecureBootSignedBinaryInfo(
            certificate = request.certificate,
            esp_path = request.esp_path,
            format_version = "mkosi-secure-boot-signed-binary-v3",
            request = request.request,
            signed_binary = output,
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
        "signed_binary": attr.label(
            mandatory = True,
            allow_files = True,
            doc = "The signed binary: a single file or a secure_boot_ephemeral_test_fixture.",
        ),
    }, **_TOOL_ATTRS),
    doc = """Imports an externally signed UKI or ESP boot binary.

The import fails unless the binary embeds an Authenticode signature by the requested certificate and is otherwise
equivalent to the requested unsigned binary.""",
    toolchains = [MKOSI_TOOLCHAIN_TYPE],
)

def _fixture_binaries(ctx):
    """Returns the unsigned UKIs and ESP files of the fixture's images, extracting the ESP files."""
    unsigned = []
    for index, target in enumerate(ctx.attr.images):
        image = target[MkosiImageInfo]
        unsigned.append(_unsigned_binary(ctx, image, "", None))
        for path_index, esp_path in enumerate(ctx.attr.esp_paths):
            name = "%s.unsigned/%d/%d.efi" % (ctx.label.name, index, path_index)
            unsigned.append(_unsigned_binary(ctx, image, esp_path, name))
    return unsigned

def _fixture_arguments(ctx, certificate, auto_enroll_dir, pairs):
    """Returns the ephemeral-fixture arguments that sign each (unsigned, signed) pair."""
    args = ctx.actions.args()
    args.add(ctx.file._tool.path)
    args.add("ephemeral-fixture")
    args.add("--openssl", ctx.executable._debian_tools.path)
    args.add("--sbsign", ctx.executable._debian_tools.path)
    args.add("--certificate", certificate.path)
    args.add("--auto-enroll-dir", auto_enroll_dir)
    args.add("--scratch", certificate.dirname + "/." + ctx.label.name + "-private")
    for source, destination in pairs:
        args.add("--sign", source.path)
        args.add(destination.path)
    return args

def _fixture_impl(ctx):
    if not ctx.attr.images:
        fail("images must name at least one image")
    unsigned = _fixture_binaries(ctx)
    certificate = ctx.actions.declare_file(ctx.label.name + ".certificate.pem")
    signed = [
        ctx.actions.declare_file("%s.signed/%d.efi" % (ctx.label.name, index))
        for index in range(len(unsigned))
    ]
    auto_enroll_keys = [
        ctx.actions.declare_file("%s.auto-enroll/%s.auth" % (ctx.label.name, name))
        for name in ("PK", "KEK", "db")
    ]
    _run(
        ctx,
        _fixture_arguments(ctx, certificate, auto_enroll_keys[0].dirname, zip(unsigned, signed)),
        unsigned,
        [certificate] + signed + auto_enroll_keys,
        "SecureBootEphemeralFixture",
        execution_requirements = EPHEMERAL_EXECUTION_REQUIREMENTS,
    )
    return [
        DefaultInfo(files = depset([certificate] + signed + auto_enroll_keys)),
        SecureBootEphemeralTestFixtureInfo(
            auto_enroll_keys = auto_enroll_keys,
            certificate = certificate,
            execution_requirements = EPHEMERAL_EXECUTION_REQUIREMENTS,
            signed_binaries = signed,
        ),
    ]

secure_boot_ephemeral_test_fixture = rule(
    implementation = _fixture_impl,
    attrs = dict({
        "esp_paths": attr.string_list(
            doc = "ESP binaries of every image to sign as well, such as EFI/systemd/systemd-bootx64.efi.",
        ),
        "images": attr.label_list(
            mandatory = True,
            providers = [MkosiImageInfo],
            doc = "UEFI release images whose unsigned UKIs, and esp_paths, the fixture signs.",
        ),
    }, **_TOOL_ATTRS),
    doc = """For tests: signs the UKIs and ESP binaries of images with a throwaway db key and outputs its certificate
and auto-enrollment files for throwaway PK and KEK keys. No key leaves the action.

Use the fixture as both the certificate of secure_boot_signing_request and the signed_binary of
secure_boot_import_response; the import selects the fixture's binary that matches its request.""",
    toolchains = [MKOSI_TOOLCHAIN_TYPE],
)

_MKOSI_IMAGE_FIELDS = [
    "build_metadata",
    "firmware",
    "format_version",
    "image_id",
    "image_version",
    "image_version_file",
    "manifest",
    "partition_metadata",
    "root_hash",
    "root_hash_image",
    "root_image",
    "uki",
    "uki_metadata",
    "verity_metadata",
]

_AUTO_ENROLL_NAMES = ["PK.auth", "KEK.auth", "db.auth", "dbx.auth"]

def _auto_enroll_files(targets):
    """Returns the .auth files of the targets or of test fixtures after checking their names."""
    files = []
    for target in targets:
        if SecureBootEphemeralTestFixtureInfo in target:
            files.extend(target[SecureBootEphemeralTestFixtureInfo].auto_enroll_keys)
        else:
            files.extend(target.files.to_list())
    names = {}
    for file in files:
        if file.basename not in _AUTO_ENROLL_NAMES or file.basename in names:
            fail("auto_enroll_keys must be distinct files named %s, got %s" % (
                ", ".join(_AUTO_ENROLL_NAMES),
                file.basename,
            ))
        names[file.basename] = True
    if files and len([name for name in names if name != "dbx.auth"]) != 3:
        fail("auto_enroll_keys needs PK.auth, KEK.auth and db.auth")
    return files

def _signed_image_arguments(ctx, image, signed, keys, outputs):
    args = ctx.actions.args()
    args.add(ctx.file._image_tool.path)
    args.add("--tools", ctx.executable._debian_tools.path)
    args.add("--image", image.raw_image.path)
    args.add("--partition-metadata", image.partition_metadata.path)
    for binary in signed:
        args.add_all("--signed", [binary.signed_binary, binary.request, binary.certificate])
    args.add_all(keys, before_each = "--auto-enroll-key")
    args.add("--secure-boot-enroll", ctx.attr.secure_boot_enroll)
    args.add("--scratch", outputs[0].path + ".scratch")
    args.add("--output", outputs[0].path)
    args.add("--metadata", outputs[1].path)
    return args

def _signed_image_impl(ctx):
    image = ctx.attr.image[MkosiImageInfo]
    if image.partition_metadata == None or image.firmware != "uefi":
        fail("image must be a UEFI release image")
    keys = _auto_enroll_files(ctx.attr.auto_enroll_keys)
    if not keys and ctx.attr.secure_boot_enroll != "if-safe":
        fail("secure_boot_enroll requires auto_enroll_keys")
    signed = [target[SecureBootSignedBinaryInfo] for target in ctx.attr.signed_binaries]
    outputs = [
        ctx.actions.declare_file(ctx.label.name + ".raw"),
        ctx.actions.declare_file(ctx.label.name + ".secure-boot-image.json"),
    ]
    inputs = [ctx.file._image_tool, image.raw_image, image.partition_metadata] + keys
    for binary in signed:
        inputs += [binary.signed_binary, binary.request, binary.certificate]
    _run(
        ctx,
        _signed_image_arguments(ctx, image, signed, keys, outputs),
        inputs,
        outputs,
        "SecureBootSignedImage",
        execution_requirements = mkosi_execution_requirements(True, offline = True),
        progress_message = "Writing the Secure Boot signed disk image %{label}",
    )
    fields = {field: getattr(image, field, None) for field in _MKOSI_IMAGE_FIELDS}
    return [
        DefaultInfo(files = depset(outputs)),
        MkosiImageInfo(image = outputs[0], raw_image = outputs[0], **fields),
    ]

secure_boot_signed_image = rule(
    implementation = _signed_image_impl,
    attrs = dict({
        "auto_enroll_keys": attr.label_list(
            allow_files = [".auth"],
            doc = """PK.auth, KEK.auth, db.auth and optionally dbx.auth, or a secure_boot_ephemeral_test_fixture.

The public, pre-signed authenticated variables that systemd-boot enrolls from /loader/keys/auto/ when the firmware is in
Setup Mode. The build fails unless db trusts the signer of every signed *.efi file and boot loader entry binary on the
ESP, including binaries that were already signed in the image.""",
        ),
        "image": attr.label(
            mandatory = True,
            providers = [MkosiImageInfo],
            doc = "UEFI release mkosi_image whose signing requests the signed_binaries answer.",
        ),
        "secure_boot_enroll": attr.string(
            default = "if-safe",
            values = ["manual", "if-safe", "force"],
            doc = """systemd-boot's loader.conf secure-boot-enroll mode when auto_enroll_keys are set.

if-safe enrolls automatically only in a virtual machine; force also enrolls on hardware after a 15 second countdown;
manual only adds a boot menu entry.""",
        ),
        "signed_binaries": attr.label_list(
            mandatory = True,
            allow_empty = False,
            providers = [SecureBootSignedBinaryInfo],
            doc = """secure_boot_import_response targets for the image's UKI and ESP binaries.

Each replaces every ESP file with the bytes of its unsigned binary. The build fails if a PE/COFF binary on the ESP stays
unsigned.""",
        ),
        "_image_tool": attr.label(
            default = "//mkosi/private:secure_boot_image.py",
            allow_single_file = True,
            cfg = "exec",
        ),
    }, **_TOOL_ATTRS),
    doc = """Writes a copy of a UEFI release disk image whose ESP holds signed boot binaries and Secure Boot
auto-enrollment keys.

Only the files of the EFI system partition change. Returns DefaultInfo with the disk image and its JSON metadata, and
the image's MkosiImageInfo with raw_image replaced by the signed disk image.""",
    provides = [MkosiImageInfo],
    toolchains = [MKOSI_TOOLCHAIN_TYPE],
)
