"""Normalized metadata projected from the outputs of an mkosi_image build."""

load(":mkosi_action.bzl", "mkosi_execution_requirements", "pefile_root")
load(":python_action.bzl", "mkosi_toolchain_info", "run_python")

IMAGE_METADATA_ATTRS = {
    "_file_hashing": attr.label(
        cfg = "exec",
        default = "//mkosi/private:file_hashing.py",
        allow_single_file = True,
    ),
    "_gpt_partitions": attr.label(
        cfg = "exec",
        default = "//mkosi/private:gpt_partitions.py",
        allow_single_file = True,
    ),
    "_image_version": attr.label(
        cfg = "exec",
        default = "//mkosi/private:image_version.py",
        allow_single_file = True,
    ),
    "_partition_metadata": attr.label(
        cfg = "exec",
        default = "//mkosi/private:partition_metadata.py",
        allow_single_file = True,
    ),
    "_sibling_loader": attr.label(
        cfg = "exec",
        default = "//mkosi/private:sibling_loader.py",
        allow_single_file = True,
    ),
    "_uki_metadata": attr.label(
        cfg = "exec",
        default = "//mkosi/private:uki_metadata.py",
        allow_single_file = True,
    ),
    "_verity_metadata": attr.label(
        cfg = "exec",
        default = "//mkosi/private:verity_metadata.py",
        allow_single_file = True,
    ),
}

def _slot_label_arguments(ctx, settings, arguments):
    """Adds the expected A/B slot label and returns the inputs needed to read it."""
    if not settings.verity:
        return []
    if settings.image_version:
        arguments.add("--slot-label")
        arguments.add(settings.image_id + "_" + settings.image_version)
    if settings.image_version_file:
        arguments.add("--slot-label-image-id")
        arguments.add(settings.image_id)
        arguments.add("--image-version-file")
        arguments.add(settings.image_version_file.path)
        return [settings.image_version_file, ctx.file._image_version]
    return []

def project_partition_metadata(ctx, settings, outputs):
    """Registers the action that validates and projects the GPT partition table of a release image.

    Args:
      ctx: mkosi_image rule context.
      settings: Validated mkosi_image settings.
      outputs: Declared mkosi_image outputs.
    """
    arguments = ctx.actions.args()
    arguments.add(ctx.file._partition_metadata.path)
    arguments.add("--image")
    arguments.add(outputs.raw_image.path)
    arguments.add("--output")
    arguments.add(outputs.partition_metadata.path)
    arguments.add("--firmware")
    arguments.add(settings.firmware)
    slot_version_inputs = _slot_label_arguments(ctx, settings, arguments)
    run_python(
        ctx,
        arguments = [arguments],
        inputs = [ctx.file._partition_metadata, ctx.file._gpt_partitions, ctx.file._sibling_loader, outputs.raw_image] + slot_version_inputs,
        outputs = [outputs.partition_metadata],
        execution_requirements = mkosi_execution_requirements(True, offline = True),
        mnemonic = "MkosiPartitionMetadata",
        progress_message = "Projecting GPT metadata for %{label}",
    )

def project_uki_metadata(ctx, outputs):
    """Registers the action that projects the sections of the unsigned UKI.

    Args:
      ctx: mkosi_image rule context.
      outputs: Declared mkosi_image outputs.
    """
    mkosi = mkosi_toolchain_info(ctx)
    root_hash = outputs.root_hash
    arguments = ctx.actions.args()
    arguments.add(ctx.file._uki_metadata.path)
    arguments.add("--uki")
    arguments.add(outputs.uki.path)
    if root_hash:
        arguments.add("--root-hash")
        arguments.add(root_hash.path)
    arguments.add("--output")
    arguments.add(outputs.uki_metadata.path)
    run_python(
        ctx,
        arguments = [arguments],
        inputs = [ctx.file._uki_metadata, mkosi.pefile, outputs.uki] + ([root_hash] if root_hash else []),
        transitive_inputs = [mkosi.python_runtime_files, mkosi.runfiles_files],
        outputs = [outputs.uki_metadata],
        env = {"PYTHONPATH": pefile_root(mkosi)},
        mnemonic = "MkosiUkiMetadata",
    )

def project_verity_metadata(ctx, outputs):
    """Registers the action that links the dm-verity root hash to the split partitions.

    Args:
      ctx: mkosi_image rule context.
      outputs: Declared mkosi_image outputs.
    """
    arguments = ctx.actions.args()
    arguments.add(ctx.file._verity_metadata.path)
    arguments.add("--root-hash")
    arguments.add(outputs.root_hash.path)
    arguments.add("--partition-metadata")
    arguments.add(outputs.partition_metadata.path)
    arguments.add("--root-image")
    arguments.add(outputs.root_image.path)
    arguments.add("--hash-image")
    arguments.add(outputs.root_hash_image.path)
    arguments.add("--output")
    arguments.add(outputs.verity_metadata.path)
    run_python(
        ctx,
        arguments = [arguments],
        inputs = [
            ctx.file._verity_metadata,
            ctx.file._file_hashing,
            ctx.file._gpt_partitions,
            ctx.file._sibling_loader,
            outputs.root_hash,
            outputs.partition_metadata,
            outputs.root_image,
            outputs.root_hash_image,
        ],
        outputs = [outputs.verity_metadata],
        mnemonic = "MkosiVerityMetadata",
    )

def _artifact_roles(settings):
    return {
        "build_metadata": True,
        "manifest": settings.manifest,
        "partition_metadata": settings.release_mode,
        "raw_image": True,
        "root_hash": settings.verity,
        "root_hash_image": settings.verity,
        "root_image": settings.verity,
        "uki": settings.uki,
        "uki_metadata": settings.uki,
        "verity_metadata": settings.verity,
    }

def _snapshot_metadata(snapshot):
    return {
        "architecture": snapshot.architecture,
        "codename": snapshot.codename,
        "components": snapshot.components,
        "format_version": snapshot.format_version,
        "lock_sha256": snapshot.lock_sha256,
        "snapshot": snapshot.snapshot,
        "snapshot_url": snapshot.snapshot_url,
    }

def _build_metadata(ctx, settings):
    # The metadata records output roles and normalized mkosi settings rather than deriving meaning from output
    # filenames or binaries.
    metadata = {
        "artifacts": _artifact_roles(settings),
        "firmware": settings.firmware,
        "format_version": "mkosi-image-build-metadata-v3",
        "mkosi": {
            "compression": "none",
            "format": "disk",
            "split_artifacts": settings.verity or settings.uki,
            "version": mkosi_toolchain_info(ctx).version,
        },
        "mode": settings.mode,
    }
    if settings.image_id:
        metadata["image"] = {"id": settings.image_id, "version": settings.image_version}
    if settings.snapshot:
        metadata["debian_snapshot"] = _snapshot_metadata(settings.snapshot)
    if settings.release:
        metadata["reproducibility"] = {
            "seed": settings.release.seed,
            "source_date_epoch": settings.release.source_date_epoch,
        }
    return metadata

def write_build_metadata(ctx, settings, output):
    """Writes the normalized build metadata, completed by an action when the image version is a file.

    Args:
      ctx: mkosi_image rule context.
      settings: Validated mkosi_image settings.
      output: Build metadata file.
    """
    metadata = _build_metadata(ctx, settings)
    if not settings.image_version_file:
        ctx.actions.write(output = output, content = json.encode(metadata) + "\n")
        return
    arguments = ctx.actions.args()
    arguments.add(ctx.file._image_version.path)
    arguments.add("build-metadata")
    arguments.add("--metadata-json")
    arguments.add(json.encode(metadata))
    arguments.add("--image-version-file")
    arguments.add(settings.image_version_file.path)
    arguments.add("--output")
    arguments.add(output.path)
    run_python(
        ctx,
        arguments = [arguments],
        inputs = [ctx.file._image_version, settings.image_version_file],
        outputs = [output],
        mnemonic = "MkosiBuildMetadata",
        progress_message = "Recording build metadata for %{label}",
    )
