"""Analysis tests of the package source of tracer images: the network, or a Debian snapshot without network."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts", "unittest")
load("//mkosi:defs.bzl", "mkosi_image")
load("//mkosi/private:mkosi_action.bzl", "mkosi_execution_requirements")
load(":analysis_test_helpers.bzl", "argv_preamble", "option_value", "single_action")

def _package_source_test_impl(ctx):
    env = analysistest.begin(ctx)
    action = single_action(env, "MkosiImage")
    preamble = argv_preamble(action.argv)
    repository = option_value(preamble, "--debian-snapshot-repository")
    if ctx.attr.offline:
        asserts.true(env, repository.endswith("/repository_repository"), repository)
        asserts.true(env, repository in [file.path for file in action.inputs.to_list()])
    else:
        asserts.equals(env, None, repository)
    asserts.equals(env, "main" if ctx.attr.offline else None, option_value(preamble, "--debian-snapshot-components"))
    asserts.equals(env, None, option_value(preamble, "--release-seed"), "a tracer build has no release options")
    asserts.false(env, "SOURCE_DATE_EPOCH" in action.env)
    metadata = [
        json.decode(write.content)
        for write in analysistest.target_actions(env)
        if write.mnemonic == "FileWrite" and write.outputs.to_list()[0].basename.endswith(".mkosi-image-info.json")
    ][0]
    asserts.equals(env, "tracer", metadata["mode"])
    asserts.equals(env, ctx.attr.offline, "debian_snapshot" in metadata)
    asserts.false(env, "reproducibility" in metadata)
    return analysistest.end(env)

_package_source_test = analysistest.make(
    _package_source_test_impl,
    attrs = {"offline": attr.bool(mandatory = True)},
)

def _execution_requirements_test_impl(ctx):
    env = unittest.begin(ctx)
    for release_mode, offline, expected in [
        (False, False, ["no-cache", "no-remote-exec", "requires-network"]),
        (False, True, ["block-network", "no-cache", "no-remote-exec"]),
        (True, True, ["block-network", "no-remote-exec"]),
    ]:
        asserts.equals(env, expected, sorted(mkosi_execution_requirements(release_mode, offline).keys()))
    return unittest.end(env)

_execution_requirements_test = unittest.make(_execution_requirements_test_impl)

def tracer_test_suite(name):
    """Declares the tracer tests, which use the networked tracer :debian_subject, and a test suite of them.

    Args:
      name: Name of the test suite.
    """
    mkosi_image(
        name = "tracer_with_snapshot_subject",
        config = "testdata/minimal.conf",
        debian_snapshot = "@mkosi_debian_snapshot//:repository",
        tags = ["manual"],
    )
    _package_source_test(
        name = "tracer_with_snapshot_test",
        offline = True,
        target_under_test = ":tracer_with_snapshot_subject",
    )
    _package_source_test(
        name = "networked_tracer_test",
        offline = False,
        target_under_test = ":debian_subject",
    )
    _execution_requirements_test(name = "tracer_execution_requirements_test")
    native.test_suite(
        name = name,
        tests = [
            ":networked_tracer_test",
            ":tracer_execution_requirements_test",
            ":tracer_with_snapshot_test",
        ],
    )
