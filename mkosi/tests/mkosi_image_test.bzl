"""Analysis tests for mkosi_image."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")
load("//mkosi:defs.bzl", "MkosiImageInfo", "MkosiQemuToolchainInfo", "mkosi_image")
load("//mkosi/debian:toolchain.bzl", "DebianToolsInfo")

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
    asserts.true(env, "tree_root_root" in action_inputs)
    asserts.true(env, "python3" in action_inputs, "managed Python is an action input")
    asserts.true(env, "libpython3.11.so.1.0" in action_inputs, "Python library is an action input")
    asserts.true(env, "os.py" in action_inputs, "Python standard library is an action input")
    asserts.true(env, "__main__.py" in action_inputs, "mkosi script is an action input")
    asserts.true(env, "pefile.py" in action_inputs, "pefile is an action input")
    asserts.false(env, "mkosi_cli" in action_inputs)
    asserts.false(env, "mkosi_launcher.sh" in action_inputs)
    asserts.false(env, "flat.tar" in action_inputs)
    asserts.false(env, "launcher" in action_inputs)
    asserts.equals(env, 1, len(actions[0].outputs.to_list()))
    asserts.equals(env, ctx.attr.expected_output, actions[0].outputs.to_list()[0].basename)
    asserts.true(env, actions[0].argv[0].endswith("python3"))
    asserts.true(env, actions[0].argv[1].endswith("/mkosi/__main__.py"))
    asserts.equals(env, "-I", actions[0].argv[2])
    asserts.true(env, actions[0].argv[3].endswith(ctx.attr.expected_config))
    asserts.equals(env, "--tools-tree", actions[0].argv[4])
    asserts.true(env, actions[0].argv[5].endswith("tree_root_root"))
    asserts.equals(env, "--extra-search-path", actions[0].argv[6])
    asserts.true(env, actions[0].argv[7].endswith("site-packages"))
    asserts.equals(env, "--format=disk", actions[0].argv[8])
    asserts.equals(env, "--output-extension=raw", actions[0].argv[9])
    asserts.equals(env, "--compress-output=none", actions[0].argv[10])
    asserts.equals(env, "--split-artifacts=", actions[0].argv[11])
    asserts.equals(env, "--output-directory", actions[0].argv[12])
    asserts.true(env, actions[0].argv[13].endswith("/mkosi/tests"))
    asserts.equals(env, "--output", actions[0].argv[14])
    asserts.equals(env, ctx.attr.expected_name, actions[0].argv[15])
    asserts.equals(env, "--workspace-directory", actions[0].argv[16])
    asserts.true(env, actions[0].argv[17].endswith("/.{}-mkosi".format(ctx.attr.expected_name)))
    asserts.equals(env, "--cache-directory", actions[0].argv[18])
    asserts.true(env, actions[0].argv[19].endswith("/cache"))
    asserts.equals(env, "--package-cache-directory", actions[0].argv[20])
    asserts.true(env, actions[0].argv[21].endswith("/package-cache"))
    asserts.equals(env, "--build-directory", actions[0].argv[22])
    asserts.true(env, actions[0].argv[23].endswith("/build"))
    asserts.equals(env, "--build-sources=", actions[0].argv[24])
    asserts.equals(env, "--no-pager", actions[0].argv[25])
    asserts.equals(env, "build", actions[0].argv[26])
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
        "6bcfc391a7e418b6e618706400e26301e48e4909f24f48772be14538c6b85315",
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

_provider_test = analysistest.make(
    _provider_test_impl,
    attrs = {
        "expected_config": attr.string(mandatory = True),
        "expected_name": attr.string(mandatory = True),
        "expected_output": attr.string(mandatory = True),
    },
)

def _invalid_config_test_impl(ctx):
    env = analysistest.begin(ctx)
    asserts.expect_failure(env, "single file")
    return analysistest.end(env)

_invalid_config_test = analysistest.make(
    _invalid_config_test_impl,
    expect_failure = True,
)

def mkosi_image_test_suite(name):
    """Defines analysis tests for the config-driven image action.

    Args:
      name: Name of the generated test suite.
    """
    mkosi_image(
        name = "debian_subject",
        config = "testdata/minimal.conf",
        tags = ["manual"],
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
        tags = ["manual"],
    )

    _provider_test(
        name = "output_override_provider_test",
        expected_config = "redirect.conf",
        expected_name = "override_subject",
        expected_output = "override_subject.raw",
        target_under_test = ":override_subject",
    )

    mkosi_image(
        name = "invalid_config_subject",
        config = ":invalid_mkosi_config",
        tags = ["manual"],
    )

    _invalid_config_test(
        name = "invalid_config_test",
        target_under_test = ":invalid_config_subject",
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
            ":invalid_config_test",
            ":mkosi_toolchain_provider_test",
            ":qemu_toolchain_provider_test",
            ":debian_tools_provider_test",
        ],
    )
