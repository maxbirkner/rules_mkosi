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
    "mkosi_source_tree",
    "qemu_ovmf_boot_config",
    "qemu_ovmf_boot_test",
)
load("//mkosi/debian:toolchain.bzl", "DebianToolsInfo")

_qemu_ovmf_boot_config = qemu_ovmf_boot_config

def _provider_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)

    asserts.true(env, MkosiImageInfo in target)
    asserts.equals(env, ctx.attr.expected_output, target[MkosiImageInfo].image.basename)

    actions = analysistest.target_actions(env)
    asserts.equals(env, 1, len(actions))
    asserts.equals(env, "MkosiImage", actions[0].mnemonic)
    action_inputs = [file.basename for file in actions[0].inputs.to_list()]
    asserts.true(env, ctx.attr.expected_config in action_inputs)
    asserts.true(env, "flat.tar" in action_inputs)
    asserts.true(env, "extract_tree.py" in action_inputs)
    asserts.false(env, "tree_root_root" in action_inputs)
    asserts.true(env, "python3" in action_inputs, "managed Python is an action input")
    asserts.true(env, "libpython3.11.so.1.0" in action_inputs, "Python library is an action input")
    asserts.true(env, "os.py" in action_inputs, "Python standard library is an action input")
    asserts.true(env, "__main__.py" in action_inputs, "mkosi script is an action input")
    asserts.true(env, "pefile.py" in action_inputs, "pefile is an action input")
    asserts.false(env, "mkosi_cli" in action_inputs)
    asserts.false(env, "mkosi_launcher.sh" in action_inputs)
    asserts.false(env, "launcher" in action_inputs)
    asserts.equals(env, 1, len(actions[0].outputs.to_list()))
    asserts.equals(env, ctx.attr.expected_output, actions[0].outputs.to_list()[0].basename)
    argv = actions[0].argv
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
        "ebc174414d5291b2f06597dd72b8c210e99442dc316aad6a9e020590040c3fbb",
        argv[8],
    )
    asserts.equals(env, "--", argv[9])
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
    asserts.equals(env, "", actions[0].env["PATH"])
    asserts.equals(env, "1", actions[0].env["PYTHONNOUSERSITE"])

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
    asserts.equals(env, "3.11", info.python_version)
    asserts.equals(env, "mkosi-v1", info.format_version)
    asserts.equals(env, "python3", info.executable.basename)
    asserts.equals(env, "python3", info.python.basename)
    asserts.true(env, info.python_files_to_run != None, "managed Python FilesToRunProvider is present")
    asserts.true(env, info.files_to_run != None, "compatibility FilesToRunProvider is present")
    runtime_paths = [file.path for file in info.python_runtime_files.to_list()]
    asserts.true(env, len(runtime_paths) > 1000, "managed Python runtime is complete")
    asserts.true(env, any([path.endswith("/lib/libpython3.11.so.1.0") for path in runtime_paths]))
    asserts.true(env, any([path.endswith("/lib/python3.11/os.py") for path in runtime_paths]))
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
        "ebc174414d5291b2f06597dd72b8c210e99442dc316aad6a9e020590040c3fbb",
        info.archive_sha256,
    )
    asserts.equals(env, "trixie", info.codename)
    asserts.equals(env, "amd64", info.architecture)
    asserts.equals(env, "20250814T000000Z", info.snapshot)
    asserts.equals(
        env,
        "d92b93836d652799006045aec102c5487dec01b5b478f4e7e1e4e1018811d409",
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
    asserts.true(env, info.launcher.executable != None)
    asserts.true(env, info.tree_files_to_run.executable == None)
    asserts.equals(env, 11, len(info.required_components))
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
    return analysistest.end(env)

boot_config_test = analysistest.make(_boot_config_test_impl)

_provider_test = analysistest.make(
    _provider_test_impl,
    attrs = {
        "expected_config": attr.string(mandatory = True),
        "expected_name": attr.string(mandatory = True),
        "expected_output": attr.string(mandatory = True),
    },
)

def _tree_provider_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    asserts.true(env, MkosiImageInfo in target)

    actions = analysistest.target_actions(env)
    asserts.equals(env, 2, len(actions))
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
        expected_name = "debian_subject",
        expected_output = "debian_subject.raw",
        target_under_test = ":debian_subject",
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

    _provider_test(
        name = "output_override_provider_test",
        expected_config = "redirect.conf",
        expected_name = "override_subject",
        expected_output = "override_subject.raw",
        target_under_test = ":override_subject",
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
            ":config_tree_provider_test",
            ":legacy_default_name_test",
            ":legacy_alternate_name_test",
            ":traversal_tree_mapping_test",
            ":collision_tree_mapping_test",
            ":duplicate_tree_mapping_test",
            ":invalid_source_tree_test",
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
