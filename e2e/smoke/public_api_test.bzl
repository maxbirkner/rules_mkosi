"""Independent consumer check for the public Debian toolchain API."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")
load(
    "@rules_mkosi//mkosi:defs.bzl",
    "DebianSnapshotInfo",
    "DebianToolsInfo",
    "MkosiImageInfo",
    "MkosiRootfsPayloadInfo",
    "SecureBootSignedUkiInfo",
    "SysupdateAbInfo",
)

def _behavior_targets_impl(ctx):
    output = ctx.actions.declare_file(ctx.label.name + ".txt")
    ctx.actions.write(
        output,
        "\n".join(sorted([str(target.label) for target in ctx.attr.targets])) + "\n",
    )
    return [DefaultInfo(files = depset([output]))]

behavior_targets = rule(
    implementation = _behavior_targets_impl,
    attrs = {"targets": attr.label_list(allow_files = True)},
)

def _public_api_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    asserts.true(env, DebianToolsInfo in target)
    asserts.equals(env, "debian", target[DebianToolsInfo].distribution)
    asserts.equals(env, "13", target[DebianToolsInfo].release)
    asserts.equals(env, "3.14.7", target[DebianToolsInfo].python_version)
    asserts.true(env, target[DebianToolsInfo].launcher.executable != None)
    return analysistest.end(env)

public_api_test = analysistest.make(_public_api_test_impl)

def _mkosi_python_override_test_impl(ctx):
    env = analysistest.begin(ctx)
    info = analysistest.target_under_test(env)[platform_common.ToolchainInfo].mkosi
    asserts.equals(env, "3.14", info.python_version)
    asserts.equals(env, "3.14.0", info.resolved_python_version)
    asserts.true(
        env,
        "consumer_python" in info.resolved_python_interpreter.path,
        "mkosi toolchain selected the consumer-registered Python runtime",
    )
    return analysistest.end(env)

mkosi_python_override_test = analysistest.make(_mkosi_python_override_test_impl)

def _snapshot_public_api_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    asserts.true(env, DebianSnapshotInfo in target)
    info = target[DebianSnapshotInfo]
    asserts.equals(env, "debian", info.distribution)
    asserts.equals(env, "13", info.release)
    asserts.equals(env, "trixie", info.codename)
    asserts.equals(env, "amd64", info.architecture)
    asserts.equals(env, "20250814T000000Z", info.snapshot)
    asserts.equals(env, "repository_repository", info.repository.basename)
    return analysistest.end(env)

snapshot_public_api_test = analysistest.make(_snapshot_public_api_test_impl)

def _image_public_api_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    asserts.true(env, MkosiImageInfo in target)
    info = target[MkosiImageInfo]
    asserts.equals(env, "mkosi-image-v2", info.format_version)
    asserts.equals(env, "demo.raw", info.raw_image.basename)
    asserts.equals(env, info.raw_image, info.image)
    asserts.equals(env, None, info.manifest)
    asserts.equals(env, None, info.partition_metadata)
    asserts.equals(env, None, info.uki)
    asserts.equals(env, "uefi", info.firmware)
    asserts.equals(env, None, info.root_image)
    asserts.equals(env, None, info.root_hash)
    asserts.equals(env, None, info.root_hash_image)
    asserts.equals(env, None, info.root_hash_signature)
    asserts.equals(env, None, info.uki_metadata)
    asserts.equals(env, None, info.verity_metadata)
    asserts.equals(env, "demo.mkosi-image-info.json", info.build_metadata.basename)
    return analysistest.end(env)

image_public_api_test = analysistest.make(_image_public_api_test_impl)

def _signed_uki_fixture_impl(ctx):
    output = ctx.actions.declare_file(ctx.label.name + ".efi")
    ctx.actions.write(output, "consumer signed UKI")
    return [
        DefaultInfo(files = depset([output])),
        SecureBootSignedUkiInfo(
            format_version = "mkosi-secure-boot-signed-uki-v2",
            request = None,
            signed_uki = output,
            verification_metadata = None,
        ),
    ]

signed_uki_fixture = rule(implementation = _signed_uki_fixture_impl)

def _sysupdate_public_api_test_impl(ctx):
    env = analysistest.begin(ctx)
    info = analysistest.target_under_test(env)[SysupdateAbInfo]
    asserts.equals(env, "rules-mkosi-sysupdate-ab-v1", info.format_version)
    asserts.equals(env, "uefi", info.firmware)
    asserts.equals(env, "old", info.slot_a.version)
    asserts.equals(env, "new", info.slot_b.version)
    asserts.true(env, info.layout != None)
    return analysistest.end(env)

sysupdate_public_api_test = analysistest.make(_sysupdate_public_api_test_impl)

def _rootfs_payload_public_api_test_impl(ctx):
    env = analysistest.begin(ctx)
    info = analysistest.target_under_test(env)[MkosiRootfsPayloadInfo]
    asserts.equals(env, "/usr/local/bin/consumer-tool", info.destination)
    asserts.equals(env, [""], info.executable_paths)
    asserts.false(env, info.is_tree)
    return analysistest.end(env)

rootfs_payload_public_api_test = analysistest.make(_rootfs_payload_public_api_test_impl)

def _generated_payload_tree_impl(ctx):
    output = ctx.actions.declare_directory(ctx.label.name)
    ctx.actions.run(
        executable = ctx.executable.generator,
        arguments = [output.path],
        inputs = ctx.attr.generator[DefaultInfo].default_runfiles.files,
        tools = [ctx.attr.generator[DefaultInfo].files_to_run],
        outputs = [output],
        mnemonic = "GenerateConsumerPayloadTree",
    )
    return [DefaultInfo(files = depset([output]))]

generated_payload_tree = rule(
    implementation = _generated_payload_tree_impl,
    attrs = {
        "generator": attr.label(
            mandatory = True,
            cfg = "exec",
            executable = True,
        ),
    },
)

def _verity_corrupted_image_impl(ctx):
    info = ctx.attr.image[MkosiImageInfo]
    if info.raw_image == None or info.partition_metadata == None:
        fail("image must expose raw_image and partition_metadata")
    output = ctx.actions.declare_file(ctx.label.name + ".raw")
    args = ctx.actions.args()
    args.add(ctx.file._corruptor)
    args.add("--image", info.raw_image)
    args.add("--partitions", info.partition_metadata)
    args.add("--output", output)
    ctx.actions.run(
        executable = ctx.file._python,
        arguments = [args],
        inputs = [ctx.file._corruptor, info.raw_image, info.partition_metadata],
        outputs = [output],
        mnemonic = "CorruptVerityRoot",
    )
    return [
        DefaultInfo(files = depset([output])),
        MkosiImageInfo(
            format_version = "mkosi-image-v2",
            raw_image = output,
            manifest = None,
            partition_metadata = info.partition_metadata,
            uki = info.uki,
            root_image = None,
            root_hash = info.root_hash,
            root_hash_image = info.root_hash_image,
            root_hash_signature = None,
            uki_metadata = info.uki_metadata,
            verity_metadata = info.verity_metadata,
            build_metadata = info.build_metadata,
            firmware = info.firmware,
            image = output,
        ),
    ]

verity_corrupted_image = rule(
    implementation = _verity_corrupted_image_impl,
    attrs = {
        "image": attr.label(mandatory = True, providers = [MkosiImageInfo]),
        "_corruptor": attr.label(
            default = "//:corrupt_verity_root.py",
            allow_single_file = True,
        ),
        "_python": attr.label(
            default = "@mkosi_debian_python//:python",
            cfg = "exec",
            allow_single_file = True,
        ),
    },
)

def _image_build_metadata_file_impl(ctx):
    """Selects metadata through MkosiImageInfo rather than output names."""
    metadata = ctx.attr.image[MkosiImageInfo].build_metadata
    if metadata == None:
        fail("image must provide MkosiImageInfo.build_metadata")
    return [DefaultInfo(files = depset([metadata]))]

image_build_metadata_file = rule(
    implementation = _image_build_metadata_file_impl,
    attrs = {
        "image": attr.label(
            mandatory = True,
            providers = [MkosiImageInfo],
        ),
    },
)

def _image_partition_metadata_file_impl(ctx):
    metadata = ctx.attr.image[MkosiImageInfo].partition_metadata
    if metadata == None:
        fail("image must provide MkosiImageInfo.partition_metadata")
    return [DefaultInfo(files = depset([metadata]))]

image_partition_metadata_file = rule(
    implementation = _image_partition_metadata_file_impl,
    attrs = {
        "image": attr.label(mandatory = True, providers = [MkosiImageInfo]),
    },
    doc = "Selects partition metadata through the public image provider.",
)

def _raw_image_file_impl(ctx):
    """Selects a raw disk artifact through MkosiImageInfo."""
    raw_image = ctx.attr.image[MkosiImageInfo].raw_image
    if raw_image == None:
        fail("image must provide MkosiImageInfo.raw_image")
    return [DefaultInfo(files = depset([raw_image]))]

raw_image_file = rule(
    implementation = _raw_image_file_impl,
    attrs = {
        "image": attr.label(
            mandatory = True,
            providers = [MkosiImageInfo],
        ),
    },
)
