"""Analysis tests of image actions that build arm64 images on a Linux x86-64 execution platform."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")
load("//mkosi:defs.bzl", "MkosiImageInfo")
load("//mkosi/tests:analysis_test_helpers.bzl", "argv_preamble", "option_value", "single_action")

def _foreign_architecture_test_impl(ctx):
    env = analysistest.begin(ctx)
    action = single_action(env, ctx.attr.mnemonic)
    preamble = argv_preamble(action.argv)
    inputs = [file.path for file in action.inputs.to_list()]
    asserts.equals(env, "arm64", option_value(preamble, "--debian-snapshot-architecture"))
    asserts.equals(env, "arm64", option_value(preamble, "--foreign-architecture"))
    emulator = option_value(preamble, "--foreign-emulator")
    asserts.true(env, emulator.endswith("/qemu-user-linux-amd64-aarch64"), emulator)
    asserts.true(env, emulator in inputs, "the action reads the emulator")
    runner = option_value(preamble, "--binfmt-runner")
    asserts.true(env, runner.endswith("/binfmt_runner"), runner)
    asserts.true(env, runner in inputs, "the action reads the runner")
    return analysistest.end(env)

foreign_architecture_test = analysistest.make(
    _foreign_architecture_test_impl,
    attrs = {"mnemonic": attr.string(mandatory = True)},
)

def _arm64_image_test_impl(ctx):
    env = analysistest.begin(ctx)
    asserts.equals(env, "arm64", analysistest.target_under_test(env)[MkosiImageInfo].architecture)
    projection = single_action(env, "MkosiPartitionMetadata")
    asserts.equals(env, "arm64", option_value(projection.argv, "--architecture"))
    return analysistest.end(env)

arm64_image_test = analysistest.make(_arm64_image_test_impl)

def _arm64_boot_config_test_impl(ctx):
    env = analysistest.begin(ctx)
    writes = [action for action in analysistest.target_actions(env) if action.mnemonic == "FileWrite"]
    asserts.equals(env, 1, len(writes))
    config = json.decode(writes[0].content)
    asserts.true(env, config["qemu"].endswith("/aarch64_qemu_system_executable"), config["qemu"])
    asserts.true(env, config["firmware_code"].endswith("/aarch64/code.fd"), config["firmware_code"])
    asserts.true(env, config["firmware_vars"].endswith("/aarch64/vars.fd"), config["firmware_vars"])
    asserts.equals(env, ["-machine", "virt", "-m", "1G", "-cpu", "max,pauth-impdef=on"], config["qemu_args"][:6])
    asserts.equals(env, ["-serial", "chardev:serial0"], config["serial_args"])

    # KVM cannot run an arm64 guest on the Linux x86-64 execution platform.
    asserts.equals(env, ["-accel", "tcg"], config["accelerator_args"])
    return analysistest.end(env)

arm64_boot_config_test = analysistest.make(_arm64_boot_config_test_impl)

def _virt_device_tree_impl(ctx):
    guest = ctx.toolchains["//mkosi/toolchain:qemu_toolchain_type"].qemu.guests["arm64"]
    dumped = ctx.actions.declare_file(ctx.label.name + ".qemu.dtb")

    # Without dtb-randomness=off, QEMU writes random rng-seed and kaslr-seed properties.
    ctx.actions.run(
        executable = guest.qemu_files_to_run,
        arguments = [
            "-machine",
            "{},acpi=off,dtb-randomness=off,dumpdtb={}".format(guest.machine, dumped.path),
            "-m",
            guest.memory,
            "-nodefaults",
            "-display",
            "none",
        ] + guest.cpu_args,
        outputs = [dumped],
        mnemonic = "QemuDumpDeviceTree",
        progress_message = "Dumping the device tree of QEMU's virt machine for %{label}",
    )
    output = ctx.actions.declare_file(ctx.label.name + ".dtb")
    arguments = ctx.actions.args()
    arguments.add("--input", dumped)
    arguments.add_all(ctx.attr.compatible, format_each = "--compatible=%s")
    arguments.add("--string-property=model=" + ctx.attr.model)
    arguments.add(output)
    ctx.actions.run(
        executable = ctx.executable._encoder,
        arguments = [arguments],
        inputs = [dumped],
        outputs = [output],
        mnemonic = "EditDeviceTree",
    )
    return [DefaultInfo(files = depset([output]))]

virt_device_tree = rule(
    implementation = _virt_device_tree_impl,
    doc = """The device tree that QEMU's arm64 `virt` machine without ACPI passes to the firmware, with another root model
and compatible strings, so that a booted kernel shows whether it used this device tree or the firmware's.""",
    attrs = {
        "compatible": attr.string_list(mandatory = True, doc = "Root compatible strings, most specific first."),
        "model": attr.string(mandatory = True, doc = "Root model, which Linux prints as `Machine model: <model>`."),
        "_encoder": attr.label(default = "//mkosi/tests:encode_device_tree", executable = True, cfg = "exec"),
    },
    toolchains = ["//mkosi/toolchain:qemu_toolchain_type"],
)
