"""Analysis tests for mkosi_image."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")
load(
    "//mkosi:defs.bzl",
    "ManagedPythonTestInfo",
    "MkosiImageInfo",
    "MkosiQemuToolchainInfo",
    "QemuOvmfBootConfigInfo",
    "mkosi_config_tree",
    "mkosi_image",
    "mkosi_reproducibility_manifest",
    "mkosi_rootfs_payload",
    "mkosi_source_tree",
    "qemu_ovmf_boot_config",
    "qemu_ovmf_boot_test",
)
load("//mkosi/debian:toolchain.bzl", "DebianToolsInfo")

_qemu_ovmf_boot_config = qemu_ovmf_boot_config

def _reproducibility_manifest_test_impl(ctx):
    env = analysistest.begin(ctx)
    actions = analysistest.target_actions(env)
    asserts.equals(env, 1, len(actions))
    action = actions[0]
    asserts.equals(env, "MkosiReproducibilityManifest", action.mnemonic)
    asserts.equals(
        env,
        ["release_reproducibility.reproducibility.json"],
        [output.basename for output in action.outputs.to_list()],
    )
    inputs = [file.basename for file in action.inputs.to_list()]
    asserts.true(env, "release_subject.raw" in inputs)
    asserts.true(env, "release_subject.mkosi-image-info.json" in inputs)
    asserts.true(env, "release_subject.partitions.json" in inputs)
    asserts.true(env, "reproducibility_manifest.py" in inputs)
    return analysistest.end(env)

_reproducibility_manifest_test = analysistest.make(
    _reproducibility_manifest_test_impl,
)

def _provider_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)

    asserts.true(env, MkosiImageInfo in target)
    info = target[MkosiImageInfo]
    asserts.equals(env, "mkosi-image-v1", info.format_version)
    asserts.equals(env, ctx.attr.expected_output, info.raw_image.basename)
    asserts.equals(env, info.raw_image, info.image)
    asserts.equals(env, None, info.manifest)
    asserts.equals(env, None, info.partition_metadata)
    asserts.equals(env, None, info.uki)
    asserts.equals(env, "uefi", info.firmware)
    asserts.equals(env, ctx.attr.expected_metadata, info.build_metadata.basename)
    asserts.equals(
        env,
        sorted([info.raw_image.path, info.build_metadata.path]),
        sorted([file.path for file in target[DefaultInfo].files.to_list()]),
    )

    actions = analysistest.target_actions(env)
    image_actions = [action for action in actions if action.mnemonic == "MkosiImage"]
    asserts.equals(env, 1, len(image_actions))
    image_action = image_actions[0]
    action_inputs = [file.basename for file in image_action.inputs.to_list()]
    asserts.true(env, ctx.attr.expected_config in action_inputs)
    asserts.true(env, "flat.tar" in action_inputs)
    asserts.true(env, "extract_tree.py" in action_inputs)
    asserts.true(env, "kernel_preflight" in action_inputs)
    asserts.true(env, "diagnostics.py" in action_inputs)
    asserts.false(env, "tree_root_root" in action_inputs)
    asserts.true(env, "python3" in action_inputs, "managed Python is an action input")
    asserts.true(env, "libpython3.14.so.1.0" in action_inputs, "Python library is an action input")
    asserts.true(env, "os.py" in action_inputs, "Python standard library is an action input")
    asserts.true(env, "__main__.py" in action_inputs, "mkosi script is an action input")
    asserts.true(env, "pefile.py" in action_inputs, "pefile is an action input")
    asserts.false(env, "mkosi_cli" in action_inputs)
    asserts.false(env, "mkosi_launcher.sh" in action_inputs)
    asserts.false(env, "launcher" in action_inputs)
    asserts.equals(env, 1, len(image_action.outputs.to_list()))
    asserts.equals(env, ctx.attr.expected_output, image_action.outputs.to_list()[0].basename)
    argv = image_action.argv
    asserts.true(env, argv[0].endswith("python3"))
    asserts.true(env, argv[1].endswith("/run_mkosi.py"))
    asserts.true(env, argv[2].endswith("/mkosi/__main__.py"))
    asserts.equals(env, "--debian-tools-archive", argv[3])
    asserts.true(env, argv[4].endswith("/flat.tar"))
    asserts.equals(env, "--debian-tools-extractor", argv[5])
    asserts.true(env, argv[6].endswith("/extract_tree.py"))
    asserts.equals(env, "--debian-tools-sha256", argv[7])
    asserts.equals(
        env,
        "604d93f0a2a7eeb688742e4380b5a246a679ea679215fc9e469a683bcfc4212d",
        argv[8],
    )
    kernel_preflight = argv.index("--kernel-preflight")
    asserts.true(env, argv[kernel_preflight + 1].endswith("/kernel_preflight"))
    asserts.equals(env, "--", argv[kernel_preflight + 2])
    include = argv.index("-I")
    asserts.true(env, argv[include + 1].endswith(ctx.attr.expected_config))
    tools = argv.index("--tools-tree")
    asserts.true(env, argv[tools + 1].endswith("/debian-tools"))
    search = argv.index("--extra-search-path")
    asserts.true(env, argv[search + 1].endswith("site-packages"))
    asserts.true(env, "--format=disk" in argv)
    asserts.true(env, "--output-extension=raw" in argv)
    asserts.true(env, "--compress-output=none" in argv)
    asserts.true(env, "--split-artifacts=" in argv)
    output_directory = argv.index("--output-directory")
    asserts.true(env, argv[output_directory + 1].endswith("/mkosi/tests"))
    output = argv.index("--output")
    asserts.equals(env, ctx.attr.expected_name, argv[output + 1])
    workspace = argv.index("--workspace-directory")
    asserts.true(env, argv[workspace + 1].endswith("/.{}-mkosi".format(ctx.attr.expected_name)))
    expected_suffixes = {
        "--cache-directory": "/cache",
        "--package-cache-directory": "/package-cache",
        "--build-directory": "/build",
    }
    for option in expected_suffixes:
        asserts.true(env, option in argv)
        asserts.true(env, argv[argv.index(option) + 1].endswith(expected_suffixes[option]))
    asserts.true(env, "--build-sources=" in argv)
    asserts.true(env, "--no-pager" in argv)
    asserts.equals(env, "build", argv[-1])
    asserts.equals(env, "", image_action.env["PATH"])
    asserts.equals(env, "1", image_action.env["PYTHONNOUSERSITE"])

    return analysistest.end(env)

def _toolchain_provider_test_impl(ctx):
    env = analysistest.begin(ctx)
    info = analysistest.target_under_test(env)[platform_common.ToolchainInfo].mkosi

    asserts.equals(env, "27", info.version)
    asserts.equals(
        env,
        "fa34b3ba66cc71d202b267a0f55e6c77f41d8db273ea5404f7fad99e464835f8",
        info.source_sha256,
    )
    asserts.equals(env, "sha256-+jSzumbMcdICsmeg9V5sd/QdjbJz6lQE9/rZnkZINfg=", info.integrity)
    asserts.equals(env, "3.14", info.python_version)
    asserts.equals(env, "3.14.0", info.resolved_python_version)
    asserts.true(env, "python_3_14" in info.resolved_python_interpreter.path)
    asserts.equals(env, "mkosi-v1", info.format_version)
    asserts.equals(env, "python3", info.executable.basename)
    asserts.equals(env, "python3", info.python.basename)
    asserts.true(env, info.python_files_to_run != None, "managed Python FilesToRunProvider is present")
    asserts.true(env, info.files_to_run != None, "compatibility FilesToRunProvider is present")
    runtime_paths = [file.path for file in info.python_runtime_files.to_list()]
    asserts.true(env, len(runtime_paths) > 1000, "managed Python runtime is complete")
    asserts.true(env, any([path.endswith("/lib/libpython3.14.so.1.0") for path in runtime_paths]))
    asserts.true(env, any([path.endswith("/lib/python3.14/os.py") for path in runtime_paths]))
    asserts.true(env, len(info.runfiles.files.to_list()) > 1000)
    asserts.equals(env, "__main__.py", info.script.basename)
    asserts.equals(env, "pefile.py", info.pefile.basename)
    asserts.true(env, len(info.runfiles_files.to_list()) > 0)

    return analysistest.end(env)

_toolchain_provider_test = analysistest.make(_toolchain_provider_test_impl)

def _qemu_toolchain_provider_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    info = target[platform_common.ToolchainInfo].qemu

    asserts.true(env, MkosiQemuToolchainInfo in target)
    asserts.equals(env, "linux", info.execution_os)
    asserts.equals(env, "x86_64", info.execution_cpu)
    asserts.equals(env, "11.0.0.1", info.qemu_version)
    asserts.equals(env, "edk2-stable202605-r1", info.ovmf_version)
    asserts.equals(
        env,
        "b84d359893a0a1d565f368adb8290933ef9c99431acd98cff0fc4c9b35de3d22",
        info.qemu_sha256,
    )
    asserts.equals(
        env,
        "8ae4d2d73161cc2335f5675d3b8b6edfa0642301679764a246940488ea3ce20d",
        info.ovmf_sha256,
    )
    asserts.true(env, info.qemu_system.basename == "qemu-system-x86_64")
    asserts.true(env, info.qemu_files_to_run.executable != None)
    asserts.true(env, info.ovmf_code.basename == "code.fd")
    asserts.true(env, info.ovmf_vars.basename == "vars.fd")
    return analysistest.end(env)

def _debian_tools_provider_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    info = target[platform_common.ToolchainInfo].debian_tools

    asserts.true(env, DebianToolsInfo in target)
    asserts.equals(env, "debian-tools-v1", info.format_version)
    asserts.equals(env, "debian", info.distribution)
    asserts.equals(env, "13", info.release)
    asserts.equals(
        env,
        "604d93f0a2a7eeb688742e4380b5a246a679ea679215fc9e469a683bcfc4212d",
        info.archive_sha256,
    )
    asserts.equals(env, "trixie", info.codename)
    asserts.equals(env, "amd64", info.architecture)
    asserts.equals(env, "20250814T000000Z", info.snapshot)
    asserts.equals(
        env,
        "69ade031417000aff9027996e4c3fc99336aca1b1ca8563fa69d76817003fd34",
        info.lock_sha256,
    )
    asserts.equals(
        env,
        "https://snapshot.debian.org/archive/debian/20250814T000000Z",
        info.snapshot_url,
    )
    asserts.equals(env, "flat.tar", info.tree.basename)
    asserts.equals(env, "tree_root_root", info.tree_root.basename)
    asserts.equals(env, "launcher", info.launcher.executable.basename)
    asserts.equals(env, "3.14.7", info.python_version)
    asserts.equals(env, "python", info.python.basename)
    asserts.true(env, info.launcher.executable != None)
    asserts.true(env, info.tree_files_to_run.executable == None)
    asserts.equals(env, 12, len(info.required_components))
    asserts.true(env, info.provenance.basename == "provenance.bzl")
    return analysistest.end(env)

_debian_tools_provider_test = analysistest.make(_debian_tools_provider_test_impl)

_qemu_toolchain_provider_test = analysistest.make(_qemu_toolchain_provider_test_impl)

def _boot_config_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    output = target[DefaultInfo].files.to_list()[0]
    asserts.equals(env, "analysis_boot_test_config.json", output.basename)
    runfile_names = [
        file.basename
        for file in target[DefaultInfo].default_runfiles.files.to_list()
    ]
    asserts.true(env, "code.fd" in runfile_names)
    asserts.true(env, "kernel_preflight" in runfile_names)
    return analysistest.end(env)

boot_config_test = analysistest.make(_boot_config_test_impl)

_provider_test = analysistest.make(
    _provider_test_impl,
    attrs = {
        "expected_config": attr.string(mandatory = True),
        "expected_metadata": attr.string(mandatory = True),
        "expected_name": attr.string(mandatory = True),
        "expected_output": attr.string(mandatory = True),
    },
)

def _rootfs_payload_test_impl(ctx):
    env = analysistest.begin(ctx)
    actions = analysistest.target_actions(env)
    stage = [action for action in actions if action.mnemonic == "MkosiStageInputs"][0]
    argv = stage.argv
    destination = argv.index("mkosi.extra/usr/local/bin/payload")
    asserts.true(env, argv[destination - 1].endswith("/minimal.conf"))
    asserts.equals(env, "--mapping", argv[destination - 2])
    asserts.equals(env, "file", argv[destination + 1])
    asserts.equals(env, "mkosi.extra/usr/local/bin/payload", argv[-1])
    asserts.true(env, "minimal.conf" in [file.basename for file in stage.inputs.to_list()])
    image = [action for action in actions if action.mnemonic == "MkosiImage"][0]
    asserts.true(env, "rootfs_payload_subject.mkosi" in [file.basename for file in image.inputs.to_list()])
    return analysistest.end(env)

_rootfs_payload_test = analysistest.make(_rootfs_payload_test_impl)

def _image_info_fixture_impl(ctx):
    """Creates analysis-only MkosiImageInfo output combinations."""
    raw_image = ctx.actions.declare_file(ctx.label.name + ".raw") if ctx.attr.raw_image else None
    manifest = ctx.actions.declare_file(ctx.label.name + ".manifest.json") if ctx.attr.manifest else None
    partition_metadata = ctx.actions.declare_file(ctx.label.name + ".partitions.json") if ctx.attr.partition_metadata else None
    uki = ctx.actions.declare_file(ctx.label.name + ".efi") if ctx.attr.uki else None
    build_metadata = ctx.actions.declare_file(ctx.label.name + ".mkosi-image-info.json") if ctx.attr.build_metadata else None
    artifacts = [raw_image, manifest, partition_metadata, uki, build_metadata]
    for artifact in artifacts:
        if artifact != None:
            ctx.actions.write(output = artifact, content = artifact.basename + "\n")
    return [
        DefaultInfo(files = depset([artifact for artifact in artifacts if artifact != None])),
        MkosiImageInfo(
            format_version = "mkosi-image-v1",
            raw_image = raw_image,
            manifest = manifest,
            partition_metadata = partition_metadata,
            uki = uki,
            build_metadata = build_metadata,
            firmware = "uefi",
            image = raw_image,
        ),
    ]

_image_info_fixture = rule(
    implementation = _image_info_fixture_impl,
    attrs = {
        "raw_image": attr.bool(mandatory = True),
        "manifest": attr.bool(mandatory = True),
        "partition_metadata": attr.bool(mandatory = True),
        "uki": attr.bool(mandatory = True),
        "build_metadata": attr.bool(mandatory = True),
    },
)

def _image_info_contract_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    info = target[MkosiImageInfo]
    asserts.equals(env, "mkosi-image-v1", info.format_version)
    artifacts = [
        info.raw_image,
        info.manifest,
        info.partition_metadata,
        info.uki,
        info.build_metadata,
    ]
    expected = [
        ctx.attr.expect_raw_image,
        ctx.attr.expect_manifest,
        ctx.attr.expect_partition_metadata,
        ctx.attr.expect_uki,
        ctx.attr.expect_build_metadata,
    ]
    for index in range(len(artifacts)):
        asserts.equals(env, expected[index], artifacts[index] != None)
    asserts.equals(env, info.raw_image, info.image)
    asserts.equals(
        env,
        sorted([artifact.path for artifact in artifacts if artifact != None]),
        sorted([artifact.path for artifact in target[DefaultInfo].files.to_list()]),
    )
    return analysistest.end(env)

_image_info_contract_test = analysistest.make(
    _image_info_contract_test_impl,
    attrs = {
        "expect_raw_image": attr.bool(mandatory = True),
        "expect_manifest": attr.bool(mandatory = True),
        "expect_partition_metadata": attr.bool(mandatory = True),
        "expect_uki": attr.bool(mandatory = True),
        "expect_build_metadata": attr.bool(mandatory = True),
    },
)

def _build_metadata_file_impl(ctx):
    """Selects build metadata through the public provider, not a filename."""
    metadata = ctx.attr.image[MkosiImageInfo].build_metadata
    if metadata == None:
        fail("image must provide MkosiImageInfo.build_metadata")
    return [DefaultInfo(files = depset([metadata]))]

build_metadata_file = rule(
    implementation = _build_metadata_file_impl,
    attrs = {
        "image": attr.label(
            mandatory = True,
            providers = [MkosiImageInfo],
        ),
    },
)

def _raw_image_file_impl(ctx):
    """Selects a raw disk artifact through the public provider."""
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

def _release_provider_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    actions = analysistest.target_actions(env)

    asserts.true(env, MkosiImageInfo in target)
    image_actions = [action for action in actions if action.mnemonic == "MkosiImage"]
    asserts.equals(env, 1, len(image_actions))
    image_action = image_actions[0]
    inputs = [file.basename for file in image_action.inputs.to_list()]
    asserts.true(env, "repository_repository" in inputs)
    argv = image_action.argv
    repository = argv.index("--debian-snapshot-repository")
    asserts.true(env, argv[repository + 1].endswith("/repository_repository"))
    seed = argv.index("--release-seed")
    asserts.equals(env, "00000000-0000-4000-8000-000000000007", argv[seed + 1])
    epoch = argv.index("--release-source-date-epoch")
    asserts.equals(env, "0", argv[epoch + 1])
    asserts.equals(env, "0", image_action.env["SOURCE_DATE_EPOCH"])
    info = target[MkosiImageInfo]
    asserts.equals(env, "mkosi-image-v1", info.format_version)
    asserts.equals(env, "release_subject.raw", info.raw_image.basename)
    asserts.equals(env, info.raw_image, info.image)
    asserts.equals(env, "release_subject.mkosi-image-info.json", info.build_metadata.basename)
    asserts.equals(env, "release_subject.partitions.json", info.partition_metadata.basename)
    partition_actions = [action for action in actions if action.mnemonic == "MkosiPartitionMetadata"]
    asserts.equals(env, 1, len(partition_actions))
    asserts.true(env, info.partition_metadata in partition_actions[0].outputs.to_list())
    asserts.true(env, info.raw_image in partition_actions[0].inputs.to_list())
    asserts.true(env, any([file.basename == "partition_metadata.py" for file in partition_actions[0].inputs.to_list()]))
    asserts.false(env, any([file.basename == "launcher" for file in partition_actions[0].inputs.to_list()]))
    asserts.equals(
        env,
        sorted([
            info.raw_image.path,
            info.partition_metadata.path,
            info.build_metadata.path,
        ]),
        sorted([file.path for file in target[DefaultInfo].files.to_list()]),
    )

    return analysistest.end(env)

_release_provider_test = analysistest.make(_release_provider_test_impl)

def _bios_provider_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    info = target[MkosiImageInfo]
    asserts.equals(env, "bios", info.firmware)
    image_action = [a for a in analysistest.target_actions(env) if a.mnemonic == "MkosiImage"][0]
    asserts.true(env, "--architecture=x86-64" in image_action.argv)
    asserts.true(env, "--bootable=yes" in image_action.argv)
    asserts.true(env, "--bios-bootloader=grub" in image_action.argv)
    repart = image_action.argv.index("--repart-directory")
    asserts.true(env, image_action.argv[repart + 1].endswith(".bios-repart"))
    asserts.true(env, any([f.basename.endswith(".bios-repart") for f in image_action.inputs.to_list()]))
    repart_action = [a for a in analysistest.target_actions(env) if a.mnemonic == "MkosiBiosRepart"][0]
    asserts.true(env, any([f.basename.endswith(".bios-repart") for f in repart_action.outputs.to_list()]))
    firmware = image_action.argv.index("--release-firmware")
    asserts.equals(env, "bios", image_action.argv[firmware + 1])
    partition_action = [a for a in analysistest.target_actions(env) if a.mnemonic == "MkosiPartitionMetadata"][0]
    firmware = partition_action.argv.index("--firmware")
    asserts.equals(env, "bios", partition_action.argv[firmware + 1])
    return analysistest.end(env)

_bios_provider_test = analysistest.make(_bios_provider_test_impl)

def _tree_provider_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    asserts.true(env, MkosiImageInfo in target)

    actions = analysistest.target_actions(env)
    stage = [action for action in actions if action.mnemonic == "MkosiStageInputs"][0]
    image = [action for action in actions if action.mnemonic == "MkosiImage"][0]
    asserts.equals(env, 2, len(stage.outputs.to_list()))
    asserts.true(env, any([file.basename == "tree_subject.mkosi" for file in stage.outputs.to_list()]))
    asserts.true(env, any([file.basename == "tree_subject.mkosi.manifest" for file in stage.outputs.to_list()]))
    asserts.true(env, any([file.basename == "config-tree" for file in stage.inputs.to_list()]))
    asserts.true(env, any([file.basename == "source-tree" for file in stage.inputs.to_list()]))
    asserts.true(env, any([arg.endswith("stage_inputs.py") for arg in stage.argv]))
    asserts.true(env, any([arg.endswith("config-tree") for arg in stage.argv]))
    asserts.true(env, any([arg.endswith("source-tree") for arg in stage.argv]))
    asserts.true(env, any([arg == "src" for arg in stage.argv]))
    asserts.true(env, "-C" in image.argv)
    asserts.true(env, any([
        image.argv[index + 1].endswith("tree_subject.mkosi")
        for index, arg in enumerate(image.argv)
        if arg == "-C"
    ]))
    asserts.false(env, "--build-sources=" in image.argv)
    asserts.false(env, "-I" in image.argv)
    asserts.true(env, any([file.basename == "tree_subject.mkosi" for file in image.inputs.to_list()]))
    asserts.true(env, any([file.basename == "tree_subject.mkosi.manifest" for file in image.inputs.to_list()]))
    asserts.false(env, any([file.basename == "hello.txt" for file in image.inputs.to_list()]))
    return analysistest.end(env)

_tree_provider_test = analysistest.make(_tree_provider_test_impl)

def _legacy_staged_config_test_impl(ctx):
    env = analysistest.begin(ctx)
    actions = analysistest.target_actions(env)
    image = [action for action in actions if action.mnemonic == "MkosiImage"][0]
    directory = image.argv.index("-C")
    asserts.true(env, image.argv[directory + 1].endswith(".mkosi"))
    if ctx.attr.expect_include:
        include = image.argv.index("-I")
        asserts.true(env, image.argv[include + 1].endswith("/" + ctx.attr.expected_basename))
    else:
        asserts.false(env, "-I" in image.argv)
    return analysistest.end(env)

_legacy_staged_config_test = analysistest.make(
    _legacy_staged_config_test_impl,
    attrs = {
        "expect_include": attr.bool(mandatory = True),
        "expected_basename": attr.string(mandatory = True),
    },
)

def _invalid_tree_mapping_test_impl(ctx):
    env = analysistest.begin(ctx)
    asserts.expect_failure(env, ctx.attr.expected_error)
    return analysistest.end(env)

_invalid_tree_mapping_test = analysistest.make(
    _invalid_tree_mapping_test_impl,
    attrs = {"expected_error": attr.string(mandatory = True)},
    expect_failure = True,
)

def _invalid_config_test_impl(ctx):
    env = analysistest.begin(ctx)
    asserts.expect_failure(env, "single file")
    return analysistest.end(env)

_invalid_config_test = analysistest.make(
    _invalid_config_test_impl,
    expect_failure = True,
)

def _invalid_qemu_config_test_impl(ctx):
    env = analysistest.begin(ctx)
    asserts.expect_failure(env, ctx.attr.expected_failure)
    return analysistest.end(env)

_invalid_qemu_config_test = analysistest.make(
    _invalid_qemu_config_test_impl,
    expect_failure = True,
    attrs = {
        "expected_failure": attr.string(mandatory = True),
    },
)

def _boot_deadline_provider_test_impl(ctx):
    env = analysistest.begin(ctx)
    info = analysistest.target_under_test(env)[QemuOvmfBootConfigInfo]
    asserts.equals(env, ctx.attr.expected_timeout, info.test_timeout)
    asserts.equals(env, ctx.attr.expected_qmp, info.qmp_initialization_timeout_seconds)
    asserts.equals(env, ctx.attr.expected_boot, info.boot_timeout_seconds)
    asserts.equals(env, ctx.attr.expected_shutdown, info.shutdown_timeout_seconds)
    asserts.equals(env, 30, info.cleanup_margin_seconds)
    return analysistest.end(env)

_boot_deadline_provider_test = analysistest.make(
    _boot_deadline_provider_test_impl,
    attrs = {
        "expected_timeout": attr.string(mandatory = True),
        "expected_qmp": attr.int(mandatory = True),
        "expected_boot": attr.int(mandatory = True),
        "expected_shutdown": attr.int(mandatory = True),
    },
)

def _public_boot_timeout_test_impl(ctx):
    env = analysistest.begin(ctx)
    info = analysistest.target_under_test(env)[ManagedPythonTestInfo]
    asserts.equals(env, ctx.attr.expected_timeout, info.timeout)
    asserts.equals(env, "boot_test.py", info.source.basename)
    return analysistest.end(env)

_public_boot_timeout_test = analysistest.make(
    _public_boot_timeout_test_impl,
    attrs = {"expected_timeout": attr.string(mandatory = True)},
)

def mkosi_image_test_suite(name):
    """Defines analysis tests for the config-driven image action.

    Args:
      name: Name of the generated test suite.
    """
    mkosi_image(
        name = "debian_subject",
        config = "testdata/minimal.conf",
        tags = ["requires-network"],
    )

    _provider_test(
        name = "debian_provider_test",
        expected_config = "minimal.conf",
        expected_metadata = "debian_subject.mkosi-image-info.json",
        expected_name = "debian_subject",
        expected_output = "debian_subject.raw",
        target_under_test = ":debian_subject",
    )
    build_metadata_file(
        name = "debian_subject_build_metadata",
        image = ":debian_subject",
    )

    mkosi_image(
        name = "override_subject",
        config = "testdata/redirect.conf",
        tags = ["requires-network"],
    )

    mkosi_image(
        name = "tree_subject",
        config_tree = ":config_tree",
        source_trees = {
            "src": ":source_tree",
        },
        tags = ["requires-network"],
    )

    mkosi_config_tree(
        name = "config_tree",
        src = "testdata/config-tree",
    )
    mkosi_source_tree(
        name = "source_tree",
        executable_paths = ["mkosi.build"],
        src = "testdata/source-tree",
    )
    mkosi_rootfs_payload(
        name = "rootfs_payload",
        src = "testdata/minimal.conf",
        destination = "/usr/local/bin/payload",
        executable_paths = [""],
    )
    mkosi_image(
        name = "rootfs_payload_subject",
        config_tree = ":config_tree",
        rootfs_payloads = [":rootfs_payload"],
        source_trees = {"src": ":source_tree"},
        tags = ["requires-network"],
    )
    _rootfs_payload_test(
        name = "rootfs_payload_test",
        target_under_test = ":rootfs_payload_subject",
    )

    for invalid_name, invalid_destination, expected_error in [
        ("relative", "usr/bin/tool", "must be an absolute path"),
        ("root", "/", "must be an absolute path below /"),
        ("traversal", "/usr/../bin/tool", "not a normalized relative path"),
        ("alias", "/usr//bin/tool", "not a normalized relative path"),
    ]:
        mkosi_rootfs_payload(
            name = "invalid_rootfs_payload_" + invalid_name,
            src = "testdata/minimal.conf",
            destination = invalid_destination,
            tags = ["manual"],
        )
        _invalid_tree_mapping_test(
            name = "invalid_rootfs_payload_{}_test".format(invalid_name),
            expected_error = expected_error,
            target_under_test = ":invalid_rootfs_payload_" + invalid_name,
        )
    mkosi_source_tree(
        name = "source_tree_two",
        src = "testdata/source-tree-two",
    )

    _tree_provider_test(
        name = "config_tree_provider_test",
        target_under_test = ":tree_subject",
    )

    mkosi_image(
        name = "traversal_tree_subject",
        config_tree = ":config_tree",
        source_trees = {"../src": ":source_tree"},
        tags = ["manual"],
    )
    _invalid_tree_mapping_test(
        name = "traversal_tree_mapping_test",
        expected_error = "not a normalized relative path",
        target_under_test = ":traversal_tree_subject",
    )

    mkosi_image(
        name = "collision_tree_subject",
        config_tree = ":config_tree",
        source_trees = {
            "src": ":source_tree",
            "src/nested": ":source_tree_two",
        },
        tags = ["manual"],
    )
    _invalid_tree_mapping_test(
        name = "collision_tree_mapping_test",
        expected_error = "colliding staged destinations",
        target_under_test = ":collision_tree_subject",
    )

    mkosi_image(
        name = "duplicate_tree_subject",
        config_tree = ":config_tree",
        source_trees = {
            "one": ":source_tree",
            "two": ":source_tree",
        },
        tags = ["manual"],
    )
    _invalid_tree_mapping_test(
        name = "duplicate_tree_mapping_test",
        expected_error = "duplicate staged source",
        target_under_test = ":duplicate_tree_subject",
    )

    mkosi_image(
        name = "invalid_source_tree_subject",
        config_tree = ":config_tree",
        source_trees = {"src": "testdata/minimal.conf"},
        tags = ["manual"],
    )
    _invalid_tree_mapping_test(
        name = "invalid_source_tree_test",
        expected_error = "MkosiSourceTreeInfo",
        target_under_test = ":invalid_source_tree_subject",
    )

    _qemu_ovmf_boot_config(
        name = "missing_raw_image_boot_subject",
        image = ":image_info_fixture_00",
        readiness_marker = "READY",
        shutdown_markers = ["SHUTDOWN"],
        machine_args = ["-machine", "q35"],
        boot_timeout_seconds = 15,
        qmp_initialization_timeout_seconds = 15,
        shutdown_timeout_seconds = 15,
        diagnostic_bytes = 4096,
        tags = ["manual"],
    )
    _invalid_qemu_config_test(
        name = "missing_raw_image_boot_test",
        expected_failure = "MkosiImageInfo.raw_image",
        target_under_test = ":missing_raw_image_boot_subject",
    )

    _provider_test(
        name = "output_override_provider_test",
        expected_config = "redirect.conf",
        expected_metadata = "override_subject.mkosi-image-info.json",
        expected_name = "override_subject",
        expected_output = "override_subject.raw",
        target_under_test = ":override_subject",
    )

    for output_mask in range(32):
        output_suffix = "0{}".format(output_mask) if output_mask < 10 else str(output_mask)
        fixture_name = "image_info_fixture_" + output_suffix
        test_name = "image_info_contract_" + output_suffix + "_test"
        raw_image = output_mask % 2 == 1
        manifest = output_mask % 4 >= 2
        partition_metadata = output_mask % 8 >= 4
        uki = output_mask % 16 >= 8
        build_metadata = output_mask >= 16
        _image_info_fixture(
            name = fixture_name,
            raw_image = raw_image,
            manifest = manifest,
            partition_metadata = partition_metadata,
            uki = uki,
            build_metadata = build_metadata,
            tags = ["manual"],
        )
        _image_info_contract_test(
            name = test_name,
            expect_raw_image = raw_image,
            expect_manifest = manifest,
            expect_partition_metadata = partition_metadata,
            expect_uki = uki,
            expect_build_metadata = build_metadata,
            target_under_test = ":" + fixture_name,
        )

    mkosi_image(
        name = "release_subject",
        config_tree = ":release_config_tree",
        debian_snapshot = "@mkosi_debian_snapshot//:repository",
        mode = "release",
        release_seed = "00000000-0000-4000-8000-000000000007",
        release_source_date_epoch = 0,
    )
    mkosi_image(
        name = "bios_release_subject",
        config_tree = ":release_config_tree",
        debian_snapshot = "@mkosi_debian_snapshot//:repository",
        firmware = "bios",
        mode = "release",
        release_seed = "00000000-0000-4000-8000-000000000007",
        release_source_date_epoch = 0,
    )
    _bios_provider_test(
        name = "bios_release_provider_test",
        target_under_test = ":bios_release_subject",
    )
    mkosi_image(
        name = "bios_tracer_subject",
        config = "testdata/minimal.conf",
        firmware = "bios",
        tags = ["manual"],
    )
    _invalid_tree_mapping_test(
        name = "bios_tracer_test",
        expected_error = "bios firmware requires release mode",
        target_under_test = ":bios_tracer_subject",
    )
    mkosi_reproducibility_manifest(
        name = "release_reproducibility",
        image = ":release_subject",
    )
    _reproducibility_manifest_test(
        name = "release_reproducibility_analysis_test",
        target_under_test = ":release_reproducibility",
    )
    _release_provider_test(
        name = "release_provider_test",
        target_under_test = ":release_subject",
    )
    raw_image_file(
        name = "release_raw_image",
        image = ":release_subject",
    )
    raw_image_file(
        name = "bios_release_raw_image",
        image = ":bios_release_subject",
    )
    build_metadata_file(
        name = "release_subject_build_metadata",
        image = ":release_subject",
    )
    mkosi_config_tree(
        name = "release_config_tree",
        src = "testdata/release-config",
    )

    mkosi_image(
        name = "release_without_snapshot_subject",
        config = "testdata/minimal.conf",
        mode = "release",
        release_seed = "00000000-0000-4000-8000-000000000007",
        release_source_date_epoch = 0,
        tags = ["manual"],
    )
    _invalid_tree_mapping_test(
        name = "release_without_snapshot_test",
        expected_error = "release mode requires debian_snapshot",
        target_under_test = ":release_without_snapshot_subject",
    )

    mkosi_image(
        name = "tracer_with_snapshot_subject",
        config = "testdata/minimal.conf",
        debian_snapshot = "@mkosi_debian_snapshot//:repository",
        tags = ["manual"],
    )
    _invalid_tree_mapping_test(
        name = "tracer_with_snapshot_test",
        expected_error = "only supported in release mode",
        target_under_test = ":tracer_with_snapshot_subject",
    )

    mkosi_image(
        name = "invalid_mode_subject",
        config = "testdata/minimal.conf",
        mode = "unknown",
        tags = ["manual"],
    )
    _invalid_tree_mapping_test(
        name = "invalid_mode_test",
        expected_error = "must be either 'tracer' or 'release'",
        target_under_test = ":invalid_mode_subject",
    )

    mkosi_image(
        name = "release_without_seed_subject",
        config = "testdata/minimal.conf",
        debian_snapshot = "@mkosi_debian_snapshot//:repository",
        mode = "release",
        release_source_date_epoch = 0,
        tags = ["manual"],
    )
    _invalid_tree_mapping_test(
        name = "release_without_seed_test",
        expected_error = "release mode requires release_seed",
        target_under_test = ":release_without_seed_subject",
    )

    mkosi_image(
        name = "release_without_epoch_subject",
        config = "testdata/minimal.conf",
        debian_snapshot = "@mkosi_debian_snapshot//:repository",
        mode = "release",
        release_seed = "00000000-0000-4000-8000-000000000007",
        tags = ["manual"],
    )
    _invalid_tree_mapping_test(
        name = "release_without_epoch_test",
        expected_error = "release mode requires a non-negative release_source_date_epoch",
        target_under_test = ":release_without_epoch_subject",
    )

    mkosi_image(
        name = "release_single_config_subject",
        config = "testdata/minimal.conf",
        debian_snapshot = "@mkosi_debian_snapshot//:repository",
        mode = "release",
        release_seed = "00000000-0000-4000-8000-000000000007",
        release_source_date_epoch = 0,
        tags = ["manual"],
    )
    _invalid_tree_mapping_test(
        name = "release_single_config_test",
        expected_error = "release mode requires config_tree",
        target_under_test = ":release_single_config_subject",
    )

    mkosi_image(
        name = "legacy_default_name_subject",
        config = "testdata/config-tree/mkosi.conf",
        source_trees = {"src": ":source_tree"},
        tags = ["manual"],
    )
    _legacy_staged_config_test(
        name = "legacy_default_name_test",
        expect_include = False,
        expected_basename = "mkosi.conf",
        target_under_test = ":legacy_default_name_subject",
    )

    mkosi_image(
        name = "legacy_alternate_name_subject",
        config = "testdata/minimal.conf",
        source_trees = {"src": ":source_tree"},
        tags = ["manual"],
    )
    _legacy_staged_config_test(
        name = "legacy_alternate_name_test",
        expect_include = True,
        expected_basename = "minimal.conf",
        target_under_test = ":legacy_alternate_name_subject",
    )

    mkosi_image(
        name = "invalid_config_subject",
        config = ":invalid_mkosi_config",
        # This deliberately invalid analysis subject cannot be part of a
        # wildcard build; the companion analysistest expects its failure.
        tags = ["manual"],
    )

    _invalid_config_test(
        name = "invalid_config_test",
        target_under_test = ":invalid_config_subject",
    )

    _qemu_ovmf_boot_config(
        name = "invalid_boot_deadline_subject",
        image = ":debian_subject",
        readiness_marker = "READY",
        shutdown_markers = ["SHUTDOWN"],
        machine_args = ["-machine", "q35"],
        boot_timeout_seconds = 600,
        qmp_initialization_timeout_seconds = 15,
        shutdown_timeout_seconds = 30,
        diagnostic_bytes = 4096,
        tags = ["manual"],
    )
    _invalid_qemu_config_test(
        name = "invalid_boot_deadline_test",
        expected_failure = "exceed",
        target_under_test = ":invalid_boot_deadline_subject",
    )

    qemu_ovmf_boot_test(
        name = "invalid_public_boot_deadline_subject",
        image = ":debian_subject",
        readiness_marker = "READY",
        shutdown_markers = ["SHUTDOWN"],
        machine_args = ["-machine", "q35"],
        boot_timeout_seconds = 600,
        qmp_initialization_timeout_seconds = 15,
        shutdown_timeout_seconds = 30,
        diagnostic_bytes = 4096,
        tags = ["manual"],
    )
    _invalid_qemu_config_test(
        name = "invalid_public_boot_deadline_test",
        expected_failure = "exceed",
        target_under_test = ":invalid_public_boot_deadline_subject",
    )

    qemu_ovmf_boot_test(
        name = "long_public_boot_deadline_subject",
        image = ":debian_subject",
        readiness_marker = "READY",
        shutdown_markers = ["SHUTDOWN"],
        machine_args = ["-machine", "q35"],
        boot_timeout_seconds = 600,
        qmp_initialization_timeout_seconds = 15,
        shutdown_timeout_seconds = 30,
        diagnostic_bytes = 4096,
        timeout = "long",
        # Analysis-only macro subject; the provider test below validates the
        # generated configuration without booting this deliberately synthetic
        # guest.
        tags = ["manual"],
    )
    _boot_deadline_provider_test(
        name = "long_public_boot_deadline_test",
        expected_timeout = "long",
        expected_qmp = 15,
        expected_boot = 600,
        expected_shutdown = 30,
        target_under_test = ":long_public_boot_deadline_subject_config",
    )

    _qemu_ovmf_boot_config(
        name = "invalid_boot_marker_subject",
        image = ":debian_subject",
        readiness_marker = "",
        shutdown_markers = ["SHUTDOWN"],
        machine_args = ["-machine", "q35"],
        boot_timeout_seconds = 180,
        qmp_initialization_timeout_seconds = 15,
        shutdown_timeout_seconds = 30,
        diagnostic_bytes = 4096,
        tags = ["manual"],
    )
    _invalid_qemu_config_test(
        name = "invalid_boot_marker_test",
        expected_failure = "readiness_marker",
        target_under_test = ":invalid_boot_marker_subject",
    )

    _qemu_ovmf_boot_config(
        name = "invalid_boot_positive_subject",
        image = ":debian_subject",
        readiness_marker = "READY",
        shutdown_markers = ["SHUTDOWN"],
        machine_args = ["-machine", "q35"],
        boot_timeout_seconds = 0,
        qmp_initialization_timeout_seconds = 15,
        shutdown_timeout_seconds = 30,
        diagnostic_bytes = 4096,
        tags = ["manual"],
    )
    _invalid_qemu_config_test(
        name = "invalid_boot_positive_test",
        expected_failure = "must be positive",
        target_under_test = ":invalid_boot_positive_subject",
    )

    _qemu_ovmf_boot_config(
        name = "boundary_boot_deadline_subject",
        image = ":debian_subject",
        readiness_marker = "READY",
        shutdown_markers = ["SHUTDOWN"],
        machine_args = ["-machine", "q35"],
        boot_timeout_seconds = 220,
        qmp_initialization_timeout_seconds = 20,
        shutdown_timeout_seconds = 30,
        diagnostic_bytes = 4096,
        test_timeout = "moderate",
    )
    _boot_deadline_provider_test(
        name = "boundary_boot_deadline_test",
        expected_timeout = "moderate",
        expected_qmp = 20,
        expected_boot = 220,
        expected_shutdown = 30,
        target_under_test = ":boundary_boot_deadline_subject",
    )

    _boot_deadline_provider_test(
        name = "default_boot_deadline_test",
        expected_timeout = "moderate",
        expected_qmp = 15,
        expected_boot = 180,
        expected_shutdown = 30,
        target_under_test = ":analysis_boot_test_config",
    )

    qemu_ovmf_boot_test(
        name = "public_long_timeout_boot_test",
        image = ":debian_subject",
        boot_timeout_seconds = 600,
        timeout = "long",
        # Analysis-only timeout propagation subject.
        tags = ["manual"],
    )
    _public_boot_timeout_test(
        name = "public_boot_timeout_test",
        expected_timeout = "long",
        target_under_test = ":public_long_timeout_boot_test",
    )
    _public_boot_timeout_test(
        name = "public_moderate_timeout_test",
        expected_timeout = "moderate",
        target_under_test = ":analysis_boot_test",
    )

    qemu_ovmf_boot_test(
        name = "public_short_timeout_boot_test",
        image = ":debian_subject",
        boot_timeout_seconds = 10,
        qmp_initialization_timeout_seconds = 5,
        shutdown_timeout_seconds = 5,
        timeout = "short",
        # Analysis-only timeout propagation subject.
        tags = ["manual"],
    )
    _public_boot_timeout_test(
        name = "public_short_timeout_test",
        expected_timeout = "short",
        target_under_test = ":public_short_timeout_boot_test",
    )

    _qemu_ovmf_boot_config(
        name = "invalid_qmp_deadline_subject",
        image = ":debian_subject",
        readiness_marker = "READY",
        shutdown_markers = ["SHUTDOWN"],
        machine_args = ["-machine", "q35"],
        boot_timeout_seconds = 180,
        qmp_initialization_timeout_seconds = 0,
        shutdown_timeout_seconds = 30,
        diagnostic_bytes = 4096,
        tags = ["manual"],
    )
    _invalid_qemu_config_test(
        name = "invalid_qmp_deadline_test",
        expected_failure = "qmp_initialization_timeout_seconds",
        target_under_test = ":invalid_qmp_deadline_subject",
    )

    _qemu_ovmf_boot_config(
        name = "invalid_shutdown_deadline_subject",
        image = ":debian_subject",
        readiness_marker = "READY",
        shutdown_markers = ["SHUTDOWN"],
        machine_args = ["-machine", "q35"],
        boot_timeout_seconds = 180,
        qmp_initialization_timeout_seconds = 15,
        shutdown_timeout_seconds = 0,
        diagnostic_bytes = 4096,
        tags = ["manual"],
    )
    _invalid_qemu_config_test(
        name = "invalid_shutdown_deadline_test",
        expected_failure = "shutdown_timeout_seconds",
        target_under_test = ":invalid_shutdown_deadline_subject",
    )

    _qemu_ovmf_boot_config(
        name = "invalid_sum_deadline_subject",
        image = ":debian_subject",
        readiness_marker = "READY",
        shutdown_markers = ["SHUTDOWN"],
        machine_args = ["-machine", "q35"],
        boot_timeout_seconds = 260,
        qmp_initialization_timeout_seconds = 15,
        shutdown_timeout_seconds = 30,
        diagnostic_bytes = 4096,
        tags = ["manual"],
    )
    _invalid_qemu_config_test(
        name = "invalid_sum_deadline_test",
        expected_failure = "exceed",
        target_under_test = ":invalid_sum_deadline_subject",
    )

    _qemu_ovmf_boot_config(
        name = "invalid_boot_eternal_subject",
        image = ":debian_subject",
        readiness_marker = "READY",
        shutdown_markers = ["SHUTDOWN"],
        machine_args = ["-machine", "q35"],
        boot_timeout_seconds = 180,
        qmp_initialization_timeout_seconds = 15,
        shutdown_timeout_seconds = 30,
        diagnostic_bytes = 4096,
        test_timeout = "eternal",
        tags = ["manual"],
    )
    _invalid_qemu_config_test(
        name = "invalid_boot_eternal_test",
        expected_failure = "eternal",
        target_under_test = ":invalid_boot_eternal_subject",
    )

    qemu_ovmf_boot_test(
        name = "invalid_boot_diagnostic_subject",
        image = ":debian_subject",
        readiness_marker = "READY",
        shutdown_markers = ["SHUTDOWN"],
        machine_args = ["-machine", "q35"],
        boot_timeout_seconds = 180,
        qmp_initialization_timeout_seconds = 15,
        shutdown_timeout_seconds = 30,
        diagnostic_bytes = 0,
        tags = ["manual"],
    )
    _invalid_qemu_config_test(
        name = "invalid_boot_diagnostic_test",
        expected_failure = "diagnostic_bytes",
        target_under_test = ":invalid_boot_diagnostic_subject_config",
    )

    qemu_ovmf_boot_test(
        name = "invalid_boot_shutdown_marker_subject",
        image = ":debian_subject",
        readiness_marker = "READY",
        shutdown_markers = [],
        machine_args = ["-machine", "q35"],
        boot_timeout_seconds = 180,
        qmp_initialization_timeout_seconds = 15,
        shutdown_timeout_seconds = 30,
        diagnostic_bytes = 4096,
        tags = ["manual"],
    )
    _invalid_qemu_config_test(
        name = "invalid_boot_shutdown_marker_test",
        expected_failure = "shutdown_markers",
        target_under_test = ":invalid_boot_shutdown_marker_subject_config",
    )

    _toolchain_provider_test(
        name = "mkosi_toolchain_provider_test",
        target_under_test = "@mkosi_toolchains//:mkosi_toolchain",
    )

    _qemu_toolchain_provider_test(
        name = "qemu_toolchain_provider_test",
        target_under_test = "@mkosi_toolchains//:qemu_ovmf_toolchain",
    )

    _debian_tools_provider_test(
        name = "debian_tools_provider_test",
        target_under_test = "@mkosi_debian_tools//:toolchain",
    )

    native.test_suite(
        name = name,
        tests = [
            ":debian_provider_test",
            ":output_override_provider_test",
            ":image_info_contract_00_test",
            ":image_info_contract_01_test",
            ":image_info_contract_02_test",
            ":image_info_contract_03_test",
            ":image_info_contract_04_test",
            ":image_info_contract_05_test",
            ":image_info_contract_06_test",
            ":image_info_contract_07_test",
            ":image_info_contract_08_test",
            ":image_info_contract_09_test",
            ":image_info_contract_10_test",
            ":image_info_contract_11_test",
            ":image_info_contract_12_test",
            ":image_info_contract_13_test",
            ":image_info_contract_14_test",
            ":image_info_contract_15_test",
            ":image_info_contract_16_test",
            ":image_info_contract_17_test",
            ":image_info_contract_18_test",
            ":image_info_contract_19_test",
            ":image_info_contract_20_test",
            ":image_info_contract_21_test",
            ":image_info_contract_22_test",
            ":image_info_contract_23_test",
            ":image_info_contract_24_test",
            ":image_info_contract_25_test",
            ":image_info_contract_26_test",
            ":image_info_contract_27_test",
            ":image_info_contract_28_test",
            ":image_info_contract_29_test",
            ":image_info_contract_30_test",
            ":image_info_contract_31_test",
            ":release_provider_test",
            ":bios_release_provider_test",
            ":bios_tracer_test",
            ":release_without_snapshot_test",
            ":tracer_with_snapshot_test",
            ":invalid_mode_test",
            ":release_without_seed_test",
            ":release_without_epoch_test",
            ":release_single_config_test",
            ":config_tree_provider_test",
            ":rootfs_payload_test",
            ":invalid_rootfs_payload_relative_test",
            ":invalid_rootfs_payload_root_test",
            ":invalid_rootfs_payload_traversal_test",
            ":invalid_rootfs_payload_alias_test",
            ":legacy_default_name_test",
            ":legacy_alternate_name_test",
            ":traversal_tree_mapping_test",
            ":collision_tree_mapping_test",
            ":duplicate_tree_mapping_test",
            ":invalid_source_tree_test",
            ":missing_raw_image_boot_test",
            ":invalid_config_test",
            ":invalid_boot_deadline_test",
            ":invalid_public_boot_deadline_test",
            ":long_public_boot_deadline_test",
            ":invalid_boot_marker_test",
            ":invalid_boot_positive_test",
            ":invalid_boot_eternal_test",
            ":invalid_boot_diagnostic_test",
            ":invalid_boot_shutdown_marker_test",
            ":boundary_boot_deadline_test",
            ":default_boot_deadline_test",
            ":public_boot_timeout_test",
            ":public_moderate_timeout_test",
            ":public_short_timeout_test",
            ":invalid_qmp_deadline_test",
            ":invalid_shutdown_deadline_test",
            ":invalid_sum_deadline_test",
            ":mkosi_toolchain_provider_test",
            ":qemu_toolchain_provider_test",
            ":debian_tools_provider_test",
            ":boot_config_test",
        ],
    )
