"""Analysis tests for mkosi_config_tree assembled from srcs and trees."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")
load("//mkosi:defs.bzl", "MkosiConfigTreeInfo", "mkosi_config_tree", "mkosi_image")
load(":analysis_test_helpers.bzl", "expected_failure_test", "single_action")

_SHARED_EXECUTABLES = [
    "mkosi.extra/opt/shared/mkosi.build",
    "mkosi.initrd.conf/mkosi.extra/opt/shared/mkosi.build",
]

def _mappings(argv):
    """Returns the (source, destination, role) triples of a staging command line."""
    return [tuple(argv[index + 1:index + 4]) for index, argument in enumerate(argv) if argument == "--mapping"]

def _assembled_test_impl(ctx):
    env = analysistest.begin(ctx)
    info = analysistest.target_under_test(env)[MkosiConfigTreeInfo]
    asserts.true(env, info.tree.is_directory)
    asserts.equals(env, "assembled_config_tree.config-tree", info.tree.basename)
    asserts.true(env, info.is_generated)
    asserts.equals(env, ["mkosi.include.conf"] + _SHARED_EXECUTABLES, info.executable_paths)

    action = single_action(env, "MkosiConfigTree")
    asserts.equals(env, [info.tree], action.outputs.to_list())
    asserts.true(env, "--merge" in action.argv)
    executables = [action.argv[index + 1] for index, argument in enumerate(action.argv) if argument == "--executable"]
    asserts.equals(env, info.executable_paths, executables)

    mappings = {destination: (source, role) for source, destination, role in _mappings(action.argv)}
    package = ctx.label.package
    asserts.equals(env, (package + "/testdata/config-tree/mkosi.conf", "file"), mappings["mkosi.conf"])
    asserts.equals(
        env,
        (package + "/testdata/config-tree/mkosi.extra/etc/declared-marker", "file"),
        mappings["mkosi.extra/etc/declared-marker"],
    )
    generated = mappings["mkosi.extra/usr/share/generated-source.txt"]
    asserts.true(env, generated[0].endswith("/bin/" + package + "/generated-source.txt"), generated[0])
    asserts.equals(env, "file", generated[1])

    # The same fragment is shared by the image and its default initrd.
    shared = [
        mappings[destination]
        for destination in ("mkosi.extra/opt/shared", "mkosi.initrd.conf/mkosi.extra/opt/shared")
    ]
    asserts.equals(env, shared[0], shared[1])
    asserts.true(env, shared[0][0].endswith("shared_config_fragment.config-tree"), shared[0][0])
    asserts.equals(env, "generated-tree", shared[0][1])
    asserts.equals(env, 7, len(mappings))
    return analysistest.end(env)

_assembled_test = analysistest.make(_assembled_test_impl)

def _image_test_impl(ctx):
    env = analysistest.begin(ctx)
    stage = single_action(env, "MkosiStageInputs")
    config = [mapping for mapping in _mappings(stage.argv) if mapping[1] == "."]
    asserts.equals(env, 1, len(config))
    asserts.true(env, config[0][0].endswith("assembled_config_tree.config-tree"), config[0][0])
    asserts.equals(env, "generated-tree", config[0][2])
    for path in ["mkosi.include.conf"] + _SHARED_EXECUTABLES:
        asserts.true(env, path in stage.argv, path)
    return analysistest.end(env)

_image_test = analysistest.make(_image_test_impl)

def _declared_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    info = target[MkosiConfigTreeInfo]
    asserts.true(env, info.tree.is_source)
    asserts.false(env, info.is_generated)
    asserts.equals(env, [], analysistest.target_actions(env))
    return analysistest.end(env)

_declared_test = analysistest.make(_declared_test_impl)

_INVALID = [
    ("empty", {}, "set src, srcs, or trees"),
    ("traversal", {"trees": {"../outside": ":generated_source_file"}}, "not a normalized relative path"),
    ("absolute", {"trees": {"/mkosi.extra": ":generated_source_file"}}, "must be relative"),
    ("strip_prefix", {"srcs": ["testdata/minimal.conf"], "strip_prefix": "testdata/config-tree"}, "is not below"),
    ("strip_prefix_traversal", {"srcs": ["testdata/minimal.conf"], "strip_prefix": "../testdata"}, "normalized"),
    ("duplicate", {"srcs": ["testdata/minimal.conf", ":invalid_mkosi_config"]}, "duplicate configuration tree"),
    (
        "file_at_tree",
        {"srcs": ["testdata/minimal.conf"], "trees": {"testdata/minimal.conf": ":shared_config_fragment"}},
        "collides with a trees directory",
    ),
    (
        "file_above_file",
        {"srcs": ["testdata/minimal.conf"], "trees": {"testdata/minimal.conf/child": ":generated_source_file"}},
        "collides with",
    ),
    ("directory_src", {"srcs": [":shared_config_fragment"]}, "srcs must contain files"),
    ("outside_package", {"srcs": [":config_tree_outside_package_files"]}, "is outside the package"),
    (
        "unknown_executable",
        {"executable_paths": ["testdata/missing"], "srcs": ["testdata/minimal.conf"]},
        "is not a file of the configuration tree",
    ),
    (
        "executable_traversal",
        {"executable_paths": ["../minimal.conf"], "srcs": ["testdata/minimal.conf"]},
        "not a normalized relative path",
    ),
]

def _consumer_tests():
    mkosi_image(
        name = "assembled_config_image_subject",
        config_tree = ":assembled_config_tree",
        debian_snapshot = "@mkosi_debian_snapshot//:repository",
        tags = ["manual"],
    )
    _image_test(name = "assembled_config_image_test", target_under_test = ":assembled_config_image_subject")

    mkosi_config_tree(name = "declared_config_tree", src = "testdata/config-tree", tags = ["manual"])
    _declared_test(name = "declared_config_tree_test", target_under_test = ":declared_config_tree")
    return [":assembled_config_image_test", ":declared_config_tree_test"]

def _invalid_config_tree_tests():
    native.filegroup(
        name = "config_tree_outside_package_files",
        srcs = ["//mkosi/private:stage_inputs.py"],
        tags = ["manual"],
    )
    tests = []
    for subject, kwargs, expected_error in _INVALID:
        mkosi_config_tree(name = "invalid_%s_config_tree" % subject, tags = ["manual"], **kwargs)
        expected_failure_test(
            name = "invalid_%s_config_tree_test" % subject,
            expected_error = expected_error,
            target_under_test = ":invalid_%s_config_tree" % subject,
        )
        tests.append(":invalid_%s_config_tree_test" % subject)
    return tests

def config_tree_test_suite(name):
    """Declares the mkosi_config_tree assembly analysis tests and a test_suite named name.

    Args:
      name: Name of the test_suite.
    """
    mkosi_config_tree(
        name = "shared_config_fragment",
        srcs = ["testdata/source-tree/hello.txt", "testdata/source-tree/mkosi.build"],
        strip_prefix = "testdata/source-tree",
        executable_paths = ["mkosi.build"],
    )
    mkosi_config_tree(
        name = "assembled_config_tree",
        srcs = native.glob(["testdata/config-tree/**"]),
        strip_prefix = "testdata/config-tree",
        trees = {
            "mkosi.extra/opt/shared": ":shared_config_fragment",
            "mkosi.extra/usr/share": ":generated_source_file",
            "mkosi.initrd.conf/mkosi.extra/opt/shared": ":shared_config_fragment",
        },
        executable_paths = ["mkosi.include.conf"],
    )
    _assembled_test(name = "assembled_config_tree_test", target_under_test = ":assembled_config_tree")
    native.test_suite(
        name = name,
        tests = [":assembled_config_tree_test"] + _consumer_tests() + _invalid_config_tree_tests(),
    )
