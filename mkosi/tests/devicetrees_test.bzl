"""Analysis tests for the devicetrees of mkosi_image."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")
load("//mkosi:defs.bzl", "mkosi_image")
load(":analysis_test_helpers.bzl", "argv_preamble", "expected_failure_test", "option_value", "single_action")

_SNAPSHOT = "@mkosi_debian_snapshot//:repository"
_SEED = "00000000-0000-4000-8000-000000000207"

def _staged_test_impl(ctx):
    env = analysistest.begin(ctx)
    staging = single_action(env, "MkosiDevicetrees")
    for file in ctx.files.devicetrees:
        asserts.true(env, file in staging.inputs.to_list(), file.path)
    directory = staging.outputs.to_list()[0]
    asserts.true(env, directory.is_directory)
    asserts.equals(env, directory.path, option_value(staging.argv, "--output-directory"))
    build = single_action(env, "MkosiImage")
    asserts.equals(env, directory.path, option_value(argv_preamble(build.argv), "--devicetrees-directory"))
    asserts.true(env, directory in build.inputs.to_list())

    # A derived version hashes every input of the build, so a changed device tree gets a new version.
    asserts.true(env, directory in single_action(env, "MkosiInputVersion").inputs.to_list())
    return analysistest.end(env)

_staged_test = analysistest.make(
    _staged_test_impl,
    attrs = {"devicetrees": attr.label_list(allow_files = True, mandatory = True)},
)

def _release_image(name, devicetrees, unified_kernel_image = "unsigned"):
    mkosi_image(
        name = name,
        config_tree = ":immutable_release_config_tree",
        debian_snapshot = _SNAPSHOT,
        devicetrees = devicetrees,
        image_id = "rules-mkosi-devicetrees",
        image_version_from_inputs = True,
        mode = "release",
        release_seed = _SEED,
        release_source_date_epoch = 0,
        tags = ["manual"],
        unified_kernel_image = unified_kernel_image,
    )

def _device_tree(name, output, compatible):
    native.genrule(
        name = name,
        outs = [output],
        cmd = "$(execpath :encode_device_tree) --compatible {} $@".format(compatible),
        tools = [":encode_device_tree"],
    )

def _declare_failures():
    """Declares subjects that analysis must reject and returns their tests."""
    mkosi_image(
        name = "invalid_devicetrees_tracer_subject",
        config = "testdata/minimal.conf",
        devicetrees = [":devicetree_board_a"],
        tags = ["manual"],
    )
    _release_image("invalid_devicetrees_without_uki_subject", [":devicetree_board_a"], "none")
    _release_image("invalid_devicetrees_same_name_subject", [":devicetree_board_a", ":devicetree_other_board_a"])
    _release_image("invalid_devicetrees_file_name_subject", [":devicetree_bracketed"])
    failures = {
        "invalid_devicetrees_file_name": "must end with .dtb and consist of letters, digits, and . _ + -",
        "invalid_devicetrees_same_name": "have the same file name",
        "invalid_devicetrees_tracer": "devicetrees requires release mode",
        "invalid_devicetrees_without_uki": "devicetrees requires unified_kernel_image",
    }
    for subject, error in failures.items():
        expected_failure_test(
            name = subject + "_test",
            expected_error = error,
            target_under_test = ":" + subject + "_subject",
        )
    return [":" + subject + "_test" for subject in failures]

def devicetrees_test_suite(name):
    """Declares the devicetrees analysis subjects and tests.

    Args:
      name: Name of the test suite.
    """
    _device_tree("devicetree_board_a", "devicetrees/board-a.dtb", "vendor,board-a")
    _device_tree("devicetree_board_b", "devicetrees/board-b.dtb", "vendor,board-b")
    _device_tree("devicetree_other_board_a", "devicetrees/other/board-a.dtb", "other,board-a")

    # fnmatch() would read the brackets of this file name as a pattern.
    _device_tree("devicetree_bracketed", "devicetrees/board[a].dtb", "vendor,board-a")
    _release_image("devicetrees_subject", [":devicetree_board_a", ":devicetree_board_b"])
    _staged_test(
        name = "devicetrees_staged_test",
        devicetrees = [":devicetree_board_a", ":devicetree_board_b"],
        target_under_test = ":devicetrees_subject",
    )
    native.test_suite(
        name = name,
        tests = [":devicetrees_staged_test"] + _declare_failures(),
    )
