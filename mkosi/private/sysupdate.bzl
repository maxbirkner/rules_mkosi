"""systemd-sysupdate A/B transfer definitions and update payloads for mkosi images."""

load("//mkosi/private:image_identity.bzl", "validate_image_id")
load("//mkosi/private:mkosi_image.bzl", "MkosiImageInfo", "MkosiRootfsPayloadInfo")
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

def _python_action(ctx, arguments, inputs, outputs, mnemonic):
    python = ctx.toolchains["//mkosi/toolchain:toolchain_type"].mkosi
    ctx.actions.run(
        executable = python.python,
        arguments = [arguments],
        inputs = depset([ctx.file._tool, ctx.file._gpt_partitions] + inputs, transitive = [python.python_runtime_files]),
        tools = [python.python_files_to_run],
        outputs = outputs,
        env = {"PATH": "", "PYTHONNOUSERSITE": "1"},
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
    _python_action(ctx, arguments, [], [output], "MkosiSysupdateTransfers")
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
        "image_id": attr.string(mandatory = True, doc = "IMAGE_ID shared by every release of the image."),
        "boot_attempts": attr.int(
            default = 3,
            doc = """systemd-boot boot-counting attempts for a newly installed UKI (TriesLeft=).

0 disables boot counting by listing the counter-free '<id>_@v.efi' first in the UKI target MatchPattern=, because
systemd-sysupdate names new files after the first pattern and otherwise defaults to TriesLeft=3.""",
        ),
        "instances": attr.int(default = 2, doc = "Number of A/B slots (InstancesMax=)."),
        "destination": attr.string(
            default = "/usr/lib/sysupdate.d",
            doc = "Image directory receiving the transfer files.",
        ),
        "_gpt_partitions": attr.label(default = "//mkosi/private:gpt_partitions.py", allow_single_file = True),
        "_tool": attr.label(default = "//mkosi/private:sysupdate.py", allow_single_file = True),
    },
    doc = """Generates systemd-sysupdate transfer definitions for A/B root, verity and UKI updates.

Add the target to mkosi_image(rootfs_payloads = [...]). Sources use PathRelativeTo=explicit, so updates
are applied with `systemd-sysupdate --transfer-source=<payload directory> update`. Each transfer protects
the running version, and unless boot_attempts = 0, new UKIs use systemd-boot boot counting so that a release
that never reaches boot-complete.target falls back to the previous one.
""",
    provides = [MkosiRootfsPayloadInfo],
    toolchains = ["//mkosi/toolchain:toolchain_type"],
)

def _sysupdate_payload_impl(ctx):
    image = ctx.attr.image[MkosiImageInfo]

    # MkosiImageInfo values constructed outside mkosi_image may predate image_version_file.
    image_version_file = getattr(image, "image_version_file", None)
    if not image.image_version and not image_version_file:
        fail("image must set image_id and image_version or image_version_file")
    if image.root_image == None or image.root_hash == None or image.root_hash_image == None or image.uki == None:
        fail("image must use unified_kernel_image = 'unsigned' and verity = 'hash'")
    output = ctx.actions.declare_directory(ctx.label.name)
    inputs = [image.root_hash, image.partition_metadata, image.root_image, image.root_hash_image, image.uki]
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
    arguments.add("--uki", image.uki)
    if ctx.attr.signed_uki:
        signed = ctx.attr.signed_uki[SecureBootSignedUkiInfo]
        inputs += [signed.signed_uki, signed.request]
        arguments.add("--signed-uki", signed.signed_uki)
        arguments.add("--signing-request", signed.request)
    arguments.add("--output", output.path)
    _python_action(ctx, arguments, inputs, [output], "MkosiSysupdatePayload")
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
            doc = """Optional externally signed replacement for the image's unsigned UKI.

The payload action fails with SYSUPDATE_INVALID unless the signing request was created for this image's
unsigned UKI.""",
        ),
        "_gpt_partitions": attr.label(default = "//mkosi/private:gpt_partitions.py", allow_single_file = True),
        "_image_version": attr.label(default = "//mkosi/private:image_version.py", allow_single_file = True),
        "_tool": attr.label(default = "//mkosi/private:sysupdate.py", allow_single_file = True),
    },
    doc = """Projects a versioned mkosi_image into an update directory for sysupdate_transfers.

The directory contains '<id>_<version>.root.<uuid>.raw', '<id>_<version>.root-verity.<uuid>.raw',
'<id>_<version>.efi' and a SHA256SUMS manifest. Partition UUIDs are the dm-verity root-hash-derived
UUIDs that the UKI's roothash= locates at boot; they are cross-checked against the image's GPT.
For an image versioned through image_version_file, the action reads and validates the version from that file.
""",
    provides = [SysupdatePayloadInfo],
    toolchains = ["//mkosi/toolchain:toolchain_type"],
)
