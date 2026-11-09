"""Independent consumer check for the public Debian toolchain API."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")
load(
    "@rules_mkosi//mkosi:defs.bzl",
    "DebianSnapshotInfo",
    "DebianToolsInfo",
    "MkosiBaseInfo",
    "MkosiConfigTreeInfo",
    "MkosiImageInfo",
    "MkosiRootfsPayloadInfo",
    "QemuBootConfigInfo",
    "QemuOvmfBootConfigInfo",
    "SysupdatePayloadInfo",
)
load("@rules_mkosi//mkosi/debian:provenance.bzl", "DEBIAN_TOOLS_PYTHON_VERSION", "DEBIAN_TOOLS_SNAPSHOT")

def _public_api_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    asserts.true(env, DebianToolsInfo in target)
    asserts.equals(env, "debian", target[DebianToolsInfo].distribution)
    asserts.equals(env, "13", target[DebianToolsInfo].release)
    asserts.equals(env, DEBIAN_TOOLS_PYTHON_VERSION, target[DebianToolsInfo].python_version)
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
    asserts.equals(env, ctx.attr.expected_snapshot, info.snapshot)
    asserts.equals(env, ctx.attr.expected_components, info.components)
    asserts.equals(env, "repository_repository", info.repository.basename)
    asserts.equals(env, 2 * len(ctx.attr.expected_components), len(info.packages_metadata.to_list()))
    asserts.equals(env, 64, len(info.lock_sha256))
    return analysistest.end(env)

snapshot_public_api_test = analysistest.make(
    _snapshot_public_api_test_impl,
    attrs = {
        "expected_components": attr.string_list(default = ["main"]),
        "expected_snapshot": attr.string(default = DEBIAN_TOOLS_SNAPSHOT),
    },
)

def _image_public_api_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    asserts.true(env, MkosiImageInfo in target)
    info = target[MkosiImageInfo]
    asserts.equals(env, "mkosi-image-v3", info.format_version)
    asserts.equals(env, "demo.raw", info.raw_image.basename)
    asserts.equals(env, info.raw_image, info.image)
    asserts.equals(env, [info.raw_image], target[OutputGroupInfo].raw_image.to_list())
    asserts.equals(env, None, info.manifest)
    asserts.false(env, hasattr(info, "root_hash_signature"), "root_hash_signature is not part of the API")
    asserts.equals(env, None, info.partition_metadata)
    asserts.equals(env, None, info.uki)
    asserts.equals(env, "uefi", info.firmware)
    asserts.equals(env, None, info.root_image)
    asserts.equals(env, None, info.root_hash)
    asserts.equals(env, None, info.root_hash_image)
    asserts.equals(env, None, info.uki_metadata)
    asserts.equals(env, None, info.verity_metadata)
    asserts.equals(env, "demo.mkosi-image-info.json", info.build_metadata.basename)
    asserts.equals(env, None, info.image_id)
    asserts.equals(env, None, info.image_version)
    asserts.equals(env, None, info.image_version_file)
    asserts.equals(env, None, info.input_digest)
    asserts.equals(env, None, info.version_inputs)
    return analysistest.end(env)

image_public_api_test = analysistest.make(_image_public_api_test_impl)

def _rootfs_payload_public_api_test_impl(ctx):
    env = analysistest.begin(ctx)
    info = analysistest.target_under_test(env)[MkosiRootfsPayloadInfo]
    asserts.equals(env, "/usr/local/bin/consumer-tool", info.destination)
    asserts.equals(env, [""], info.executable_paths)
    asserts.false(env, info.is_tree)
    return analysistest.end(env)

rootfs_payload_public_api_test = analysistest.make(_rootfs_payload_public_api_test_impl)

def _config_tree_public_api_test_impl(ctx):
    env = analysistest.begin(ctx)
    info = analysistest.target_under_test(env)[MkosiConfigTreeInfo]
    generator = "mkosi.extra/usr/lib/systemd/system-generators/rules-mkosi-shared-tree"
    asserts.equals(env, [generator, "mkosi.initrd.conf/" + generator], info.executable_paths)
    asserts.true(env, info.is_generated)
    asserts.true(env, info.tree.is_directory)
    return analysistest.end(env)

config_tree_public_api_test = analysistest.make(_config_tree_public_api_test_impl)

def _boot_config_public_api_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    info = target[QemuBootConfigInfo]
    asserts.equals(env, ctx.attr.expected_timeout, info.test_timeout)
    asserts.equals(env, 30, info.cleanup_margin_seconds)
    asserts.equals(env, info, target[QemuOvmfBootConfigInfo], "deprecated alias selects the same provider")
    return analysistest.end(env)

boot_config_public_api_test = analysistest.make(
    _boot_config_public_api_test_impl,
    attrs = {"expected_timeout": attr.string(mandatory = True)},
)

def _sysupdate_public_api_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    if ctx.attr.image:
        info = target[SysupdatePayloadInfo]
        image = ctx.attr.image[MkosiImageInfo]
        asserts.equals(env, "rules-mkosi-ab", info.image_id)
        asserts.equals(env, "rules-mkosi-ab", image.image_id)
        asserts.true(env, info.directory.is_directory)
        expected_version = ctx.attr.expected_version or None
        expected_version_file = ctx.file.expected_version_file
        asserts.equals(env, expected_version, info.image_version)
        asserts.equals(env, expected_version, image.image_version)
        asserts.equals(env, expected_version_file, info.image_version_file)
        asserts.equals(env, expected_version_file, image.image_version_file)
        asserts.equals(env, ctx.attr.expect_signature, info.signature != None)
    else:
        info = target[MkosiRootfsPayloadInfo]
        asserts.equals(env, "/usr/lib/sysupdate.d", info.destination)
        asserts.true(env, info.is_tree)
    return analysistest.end(env)

sysupdate_public_api_test = analysistest.make(
    _sysupdate_public_api_test_impl,
    attrs = {
        "expect_signature": attr.bool(),
        "expected_version": attr.string(),
        "expected_version_file": attr.label(allow_single_file = True),
        "image": attr.label(providers = [MkosiImageInfo]),
    },
)

def _input_version_public_api_test_impl(ctx):
    env = analysistest.begin(ctx)
    payload = analysistest.target_under_test(env)[SysupdatePayloadInfo]
    image_target = ctx.attr.image
    image = image_target[MkosiImageInfo]
    asserts.equals(env, None, image.image_version)
    asserts.true(env, image.image_version_file != None)
    asserts.true(env, image.input_digest != None)
    asserts.equals(env, [], image.version_inputs)
    asserts.equals(env, [image.image_version_file, image.input_digest], image_target[OutputGroupInfo].image_version.to_list())
    asserts.equals(env, image.image_id, payload.image_id)
    asserts.equals(env, None, payload.image_version)
    asserts.equals(env, image.image_version_file, payload.image_version_file)
    return analysistest.end(env)

input_version_public_api_test = analysistest.make(
    _input_version_public_api_test_impl,
    attrs = {"image": attr.label(providers = [MkosiImageInfo], mandatory = True)},
)

def _base_public_api_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    info = target[MkosiBaseInfo]
    asserts.equals(env, "mkosi-base-v1", info.format_version)
    asserts.equals(env, "root.tar", info.root_tree.basename)
    asserts.equals(env, [info.root_tree, info.initrd], target[DefaultInfo].files.to_list())
    asserts.equals(env, "00000000-0000-4000-8000-000000000017", info.release_seed)
    asserts.equals(env, 1755129600, info.release_source_date_epoch)
    snapshot = ctx.attr.debian_snapshot[DebianSnapshotInfo]
    asserts.equals(env, snapshot.lock_sha256, info.debian_snapshot.lock_sha256)
    return analysistest.end(env)

base_public_api_test = analysistest.make(
    _base_public_api_test_impl,
    attrs = {"debian_snapshot": attr.label(providers = [DebianSnapshotInfo], mandatory = True)},
)

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
            format_version = "mkosi-image-v3",
            raw_image = output,
            manifest = None,
            partition_metadata = info.partition_metadata,
            uki = info.uki,
            root_image = None,
            root_hash = info.root_hash,
            root_hash_image = info.root_hash_image,
            uki_metadata = info.uki_metadata,
            verity_metadata = info.verity_metadata,
            build_metadata = info.build_metadata,
            firmware = info.firmware,
            image_id = info.image_id,
            image_version = info.image_version,
            image_version_file = info.image_version_file,
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

def _image_artifact_file_impl(ctx):
    """Selects an artifact through MkosiImageInfo rather than output names."""
    artifact = getattr(ctx.attr.image[MkosiImageInfo], ctx.attr._field)
    if artifact == None:
        fail("image must provide MkosiImageInfo." + ctx.attr._field)
    return [DefaultInfo(files = depset([artifact]))]

def _image_artifact_file(field):
    return rule(
        implementation = _image_artifact_file_impl,
        attrs = {
            "image": attr.label(mandatory = True, providers = [MkosiImageInfo]),
            "_field": attr.string(default = field),
        },
        doc = "Selects MkosiImageInfo.%s through the public image provider." % field,
    )

image_build_metadata_file = _image_artifact_file("build_metadata")
image_manifest_file = _image_artifact_file("manifest")
image_partition_metadata_file = _image_artifact_file("partition_metadata")
raw_image_file = _image_artifact_file("raw_image")
