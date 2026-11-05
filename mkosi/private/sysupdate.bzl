"""systemd-sysupdate A/B transfer definitions and update payloads for mkosi images."""

load("//mkosi/private:image_identity.bzl", "validate_image_id")
load("//mkosi/private:mkosi_image.bzl", "MkosiImageInfo", "MkosiRootfsPayloadInfo")
load("//mkosi/private:python_action.bzl", "MKOSI_TOOLCHAIN_TYPE", "run_python")
load("//mkosi/private:secure_boot.bzl", "SecureBootSignedUkiInfo")

SysupdatePayloadInfo = provider(
    doc = "A directory of versioned update artifacts accepted by sysupdate_transfers definitions.",
    fields = {
        "directory": "TreeArtifact with the root, verity and UKI artifacts plus SHA256SUMS.",
        "image_id": "os-release IMAGE_ID of the payload.",
        "image_version": "os-release IMAGE_VERSION string of the payload when known during analysis, or None.",
        "image_version_file": """File holding the payload's os-release IMAGE_VERSION when the image selected it through
mkosi_image.image_version_file, or None. Exactly one of image_version and image_version_file is set.""",
    },
)

def _script(name):
    return attr.label(default = "//mkosi/private:" + name, allow_single_file = True, cfg = "exec")

_SCRIPT_ATTRS = {
    "_file_hashing": _script("file_hashing.py"),
    "_gpt_partitions": _script("gpt_partitions.py"),
    "_sibling_loader": _script("sibling_loader.py"),
    "_tool": _script("sysupdate.py"),
}

def _run_sysupdate(ctx, arguments, inputs, output, mnemonic):
    run_python(
        ctx,
        arguments = [arguments],
        inputs = [ctx.file._tool, ctx.file._file_hashing, ctx.file._gpt_partitions, ctx.file._sibling_loader] + inputs,
        outputs = [output],
        mnemonic = mnemonic,
    )

def _sysupdate_transfers_impl(ctx):
    validate_image_id(ctx.attr.image_id)
    if ctx.attr.boot_attempts < 0:
        fail("boot_attempts must be non-negative")
    if ctx.attr.instances < 2:
        fail("instances must be at least 2 for A/B updates")
    output = ctx.actions.declare_directory(ctx.label.name)
    arguments = ctx.actions.args()
    arguments.add(ctx.file._tool)
    arguments.add("transfers")
    arguments.add("--image-id", ctx.attr.image_id)
    arguments.add("--boot-attempts", str(ctx.attr.boot_attempts))
    arguments.add("--instances", str(ctx.attr.instances))
    arguments.add("--output", output.path)
    _run_sysupdate(ctx, arguments, [], output, "MkosiSysupdateTransfers")
    return [
        DefaultInfo(files = depset([output])),
        MkosiRootfsPayloadInfo(
            artifact = output,
            destination = ctx.attr.destination,
            executable_paths = [],
            is_tree = True,
            is_generated = True,
        ),
    ]

sysupdate_transfers = rule(
    implementation = _sysupdate_transfers_impl,
    attrs = {
        "boot_attempts": attr.int(
            default = 3,
            doc = "systemd-boot boot-counting attempts (TriesLeft=) of a newly installed UKI; 0 disables boot counting.",
        ),
        "destination": attr.string(
            default = "/usr/lib/sysupdate.d",
            doc = "Image directory receiving the transfer files.",
        ),
        "image_id": attr.string(mandatory = True, doc = "IMAGE_ID shared by every release of the image."),
        "instances": attr.int(default = 2, doc = "Number of A/B slots (InstancesMax=)."),
    } | _SCRIPT_ATTRS,
    doc = """Generates systemd-sysupdate transfer definitions for A/B root, verity and UKI updates.

Add the target to mkosi_image(rootfs_payloads = [...]) and apply updates with
`systemd-sysupdate --transfer-source=<payload directory> update`. The running version is protected, and unless
boot_attempts = 0, a release that never reaches boot-complete.target falls back to the previous one.
""",
    provides = [MkosiRootfsPayloadInfo],
    toolchains = [MKOSI_TOOLCHAIN_TYPE],
)

def _payload_arguments(ctx, image, image_version_file, output):
    """Returns the arguments and inputs of the payload action."""
    inputs = [
        image.root_hash,
        image.partition_metadata,
        image.root_image,
        image.root_hash_image,
        image.verity_metadata,
        image.uki,
    ]
    arguments = ctx.actions.args()
    arguments.add(ctx.file._tool)
    arguments.add("payload")
    arguments.add("--image-id", image.image_id)
    if image_version_file:
        inputs += [image_version_file, ctx.file._image_version]
        arguments.add("--image-version-file", image_version_file)
    else:
        arguments.add("--image-version", image.image_version)
    arguments.add("--root-hash", image.root_hash)
    arguments.add("--partition-metadata", image.partition_metadata)
    arguments.add("--root-image", image.root_image)
    arguments.add("--verity-image", image.root_hash_image)
    arguments.add("--verity-metadata", image.verity_metadata)
    arguments.add("--uki", image.uki)
    if ctx.attr.signed_uki:
        signed = ctx.attr.signed_uki[SecureBootSignedUkiInfo]
        inputs += [signed.signed_uki, signed.request]
        arguments.add("--signed-uki", signed.signed_uki)
        arguments.add("--signing-request", signed.request)
    arguments.add("--output", output.path)
    return arguments, inputs

def _sysupdate_payload_impl(ctx):
    image = ctx.attr.image[MkosiImageInfo]

    # MkosiImageInfo values constructed outside mkosi_image may lack image_version_file.
    image_version_file = getattr(image, "image_version_file", None)
    if not image.image_version and not image_version_file:
        fail("image must set image_id and image_version or image_version_file")
    if None in (image.root_image, image.root_hash, image.root_hash_image, image.verity_metadata, image.uki):
        fail("image must use unified_kernel_image = 'unsigned' and verity = 'hash'")
    output = ctx.actions.declare_directory(ctx.label.name)
    arguments, inputs = _payload_arguments(ctx, image, image_version_file, output)
    _run_sysupdate(ctx, arguments, inputs, output, "MkosiSysupdatePayload")
    return [
        DefaultInfo(files = depset([output])),
        SysupdatePayloadInfo(
            directory = output,
            image_id = image.image_id,
            image_version = image.image_version if not image_version_file else None,
            image_version_file = image_version_file,
        ),
    ]

sysupdate_payload = rule(
    implementation = _sysupdate_payload_impl,
    attrs = {
        "image": attr.label(
            mandatory = True,
            providers = [MkosiImageInfo],
            doc = "Versioned UEFI release image with an unsigned UKI and dm-verity.",
        ),
        "signed_uki": attr.label(
            providers = [SecureBootSignedUkiInfo],
            doc = """Externally signed replacement for the image's unsigned UKI.

The build fails with SYSUPDATE_INVALID unless its signing request was created for this image's unsigned UKI.""",
        ),
        "_image_version": _script("image_version.py"),
    } | _SCRIPT_ATTRS,
    doc = """Projects a versioned mkosi_image into an update directory for sysupdate_transfers.

The directory contains '<id>_<version>.root.<uuid>.raw', '<id>_<version>.root-verity.<uuid>.raw',
'<id>_<version>.efi' and a SHA256SUMS manifest. The partition UUIDs are those derived from the dm-verity root
hash, which the UKI's roothash= locates at boot, and must match the image's GPT. The root and verity files hold only
the bytes that dm-verity covers, so a minimized read-only root (repart Minimize=best on both partitions) is not
padded to its slot size.
""",
    provides = [SysupdatePayloadInfo],
    toolchains = [MKOSI_TOOLCHAIN_TYPE],
)
