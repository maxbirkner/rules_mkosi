"""Analysis tests for the devicetree rule."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")
load("//mkosi:defs.bzl", "devicetree")
load(":analysis_test_helpers.bzl", "expected_failure_test", "single_action")

def _values(argv, option):
    return [argv[index + 1] for index, argument in enumerate(argv) if argument == option]

def _action_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    action = single_action(env, "MkosiDevicetree")
    output = target[DefaultInfo].files.to_list()
    asserts.equals(env, ["devicetree_board.dtb"], [file.basename for file in output])
    asserts.equals(env, [output[0]], action.outputs.to_list())
    inputs = [file.short_path for file in action.inputs.to_list()]
    for path in ("board.dts", "soc.dtsi", "include/dt-bindings/rules-mkosi-leds.h", "display.dtso"):
        asserts.true(env, "mkosi/tests/testdata/devicetree/" + path in inputs, path)
    asserts.true(env, [path for path in inputs if path.endswith("/launcher")] != [], "the action runs the launcher")
    include = "mkosi/tests/testdata/devicetree/include"
    directories = _values(action.argv, "--include-directory")
    asserts.equals(env, [include, ctx.bin_dir.path + "/" + include], directories)
    asserts.equals(env, ['BOARD_MODEL="rules-mkosi test board"', "DISPLAY_REVISION=3"], _values(action.argv, "--define"))
    asserts.equals(env, ["mkosi/tests/testdata/devicetree/display.dtso"], _values(action.argv, "--overlay"))
    return analysistest.end(env)

_action_test = analysistest.make(_action_test_impl)

def devicetree_rule_test_suite(name):
    """Declares the devicetree analysis subjects and tests.

    Args:
      name: Name of the test suite.
    """
    _action_test(name = "devicetree_action_test", target_under_test = ":devicetree_board")
    devicetree(
        name = "invalid_devicetree_define_subject",
        src = "testdata/devicetrees/board.dts",
        defines = ["1COMPATIBLE=\"vendor,board\""],
        tags = ["manual"],
    )
    devicetree(
        name = "invalid_devicetree_include_subject",
        src = "testdata/devicetrees/board.dts",
        includes = ["../include"],
        tags = ["manual"],
    )
    failures = {
        "invalid_devicetree_define": "defines must be NAME or NAME=VALUE with a C identifier as NAME",
        "invalid_devicetree_include": "includes must be directories inside the package, not ../include",
    }
    for subject, error in failures.items():
        expected_failure_test(
            name = subject + "_test",
            expected_error = error,
            target_under_test = ":" + subject + "_subject",
        )
    native.test_suite(
        name = name,
        tests = [":devicetree_action_test"] + [":" + subject + "_test" for subject in failures],
    )
