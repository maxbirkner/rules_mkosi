"""Fixtures and analysis tests for the extra_packages of mkosi_base and mkosi_image."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")
load(
    "//mkosi:defs.bzl",
    "MkosiBaseInfo",
    "MkosiImageInfo",
    "mkosi_base",
    "mkosi_config_tree",
    "mkosi_image",
    "mkosi_reproducibility_manifest",
)
load(":analysis_test_helpers.bzl", "argv_preamble", "expected_failure_test", "option_value", "single_action")
load(":deb_fixture.bzl", "test_deb_package")

_SNAPSHOT = "@mkosi_debian_snapshot//:repository"
_SEED = "00000000-0000-4000-8000-000000000019"
_PACKAGES = [":extra_packages_hello_deb", ":extra_packages_netbase_deb"]

def _assert_indexed(env, packages, architecture):
    """Asserts the one MkosiExtraPackages action of the target under test and returns its repository and metadata."""
    action = single_action(env, "MkosiExtraPackages")
    inputs = action.inputs.to_list()
    for package in packages:
        asserts.true(env, package in inputs, package.path)
    asserts.equals(env, architecture, option_value(action.argv, "--architecture"))
    repository, metadata = action.outputs.to_list()
    asserts.true(env, repository.is_directory)
    asserts.equals(env, metadata.path, option_value(action.argv, "--manifest"))
    asserts.equals(env, repository.path, option_value(action.argv, "--repository"))
    return repository, metadata

def _assert_served(env, action, repository):
    """Asserts that an mkosi build action serves the extra packages' repository next to the snapshot mirror."""
    preamble = argv_preamble(action.argv)
    asserts.equals(env, repository.path, option_value(preamble, "--extra-packages-repository"))
    asserts.true(env, option_value(preamble, "--debian-snapshot-repository") != None)
    asserts.true(env, repository in action.inputs.to_list())

def _image_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    info = target[MkosiImageInfo]
    repository, metadata = _assert_indexed(env, ctx.files.packages, "amd64")
    _assert_served(env, single_action(env, "MkosiImage"), repository)
    asserts.equals(env, metadata, info.extra_packages_metadata)
    asserts.true(env, metadata in target[DefaultInfo].files.to_list())
    if ctx.attr.derived_version:
        # A derived version hashes every input of the build, so a changed extra package gets a new version.
        asserts.true(env, repository in single_action(env, "MkosiInputVersion").inputs.to_list())
    return analysistest.end(env)

_image_test = analysistest.make(
    _image_test_impl,
    attrs = {
        "derived_version": attr.bool(),
        "packages": attr.label_list(allow_files = True, mandatory = True),
    },
)

def _base_test_impl(ctx):
    env = analysistest.begin(ctx)
    info = analysistest.target_under_test(env)[MkosiBaseInfo]
    repository, metadata = _assert_indexed(env, ctx.files.packages, "amd64")
    _assert_served(env, single_action(env, "MkosiBase"), repository)
    asserts.equals(env, metadata, info.extra_packages_metadata)
    return analysistest.end(env)

_base_test = analysistest.make(
    _base_test_impl,
    attrs = {"packages": attr.label_list(allow_files = True, mandatory = True)},
)

def _finalize_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    base = ctx.attr.base[MkosiBaseInfo]
    asserts.equals(env, base.extra_packages_metadata, target[MkosiImageInfo].extra_packages_metadata)
    asserts.true(env, base.extra_packages_metadata in target[DefaultInfo].files.to_list())

    # Finalization installs no packages, so it neither indexes nor serves the extra packages again.
    asserts.false(env, "--extra-packages-repository" in single_action(env, "MkosiImage").argv)
    for action in analysistest.target_actions(env):
        asserts.false(env, action.mnemonic == "MkosiExtraPackages")
    return analysistest.end(env)

_finalize_test = analysistest.make(
    _finalize_test_impl,
    attrs = {"base": attr.label(providers = [MkosiBaseInfo], mandatory = True)},
)

def _reproducibility_test_impl(ctx):
    env = analysistest.begin(ctx)
    action = single_action(env, "MkosiReproducibilityManifest")
    metadata = ctx.attr.image[MkosiImageInfo].extra_packages_metadata
    roles = [(action.argv[index + 1], action.argv[index + 2]) for index, argument in enumerate(action.argv) if argument == "--artifact"]
    asserts.true(env, ("extra_packages_metadata", metadata.path) in roles, str(roles))
    asserts.true(env, metadata in action.inputs.to_list())
    return analysistest.end(env)

_reproducibility_test = analysistest.make(
    _reproducibility_test_impl,
    attrs = {"image": attr.label(providers = [MkosiImageInfo], mandatory = True)},
)

def _declare_fixture_packages():
    # rules-mkosi-hello depends on netbase and records that dpkg ran its postinst script.
    test_deb_package(
        name = "extra_packages_hello_deb",
        package = "rules-mkosi-hello",
        version = "1.0",
        control_fields = {"Depends": "netbase"},
        files = {"/usr/share/rules-mkosi-hello/hello.txt": "hello from an extra package\n"},
        scripts = {
            "postinst": "#!/bin/sh\nset -e\nmkdir -p /var/lib/rules-mkosi-hello\n" +
                        "echo configured >/var/lib/rules-mkosi-hello/configured\n",
        },
    )

    # Replaces the snapshot's netbase 6.5 although its version is lower.
    test_deb_package(
        name = "extra_packages_netbase_deb",
        package = "netbase",
        version = "0~rules.mkosi1",
        files = {"/usr/share/rules-mkosi-netbase/replaced": "netbase replaced by an extra package\n"},
    )

def _declare_failures():
    """Declares subjects that analysis must reject and returns their tests."""
    mkosi_image(
        name = "invalid_extra_packages_base_subject",
        base = ":extra_packages_base",
        config_tree = ":two_stage_config_tree",
        extra_packages = _PACKAGES,
        mode = "release",
        tags = ["manual"],
    )
    mkosi_image(
        name = "invalid_extra_packages_tracer_subject",
        config = "testdata/minimal.conf",
        extra_packages = _PACKAGES,
        tags = ["manual"],
    )
    mkosi_base(
        name = "invalid_extra_packages_directory_subject",
        config_tree = ":two_stage_base_config_tree",
        debian_snapshot = _SNAPSHOT,
        extra_packages = [_SNAPSHOT],
        release_seed = _SEED,
        release_source_date_epoch = 0,
        tags = ["manual"],
    )
    tests = []
    for subject, expected_error in [
        ("base", "extra_packages cannot be combined with base"),
        ("tracer", "extra_packages require debian_snapshot"),
        ("directory", "extra_packages must be .deb files, but "),
    ]:
        expected_failure_test(
            name = "invalid_extra_packages_%s_test" % subject,
            expected_error = expected_error,
            target_under_test = ":invalid_extra_packages_%s_subject" % subject,
        )
        tests.append(":invalid_extra_packages_%s_test" % subject)
    return tests

def _declare_two_stage():
    """Declares a base with extra packages and its finalization, and returns their tests."""
    mkosi_base(
        name = "extra_packages_base",
        config_tree = ":two_stage_base_config_tree",
        debian_snapshot = _SNAPSHOT,
        extra_packages = _PACKAGES,
        release_seed = "00000000-0000-4000-8000-000000000007",
        release_source_date_epoch = 0,
        tags = ["manual"],
    )
    mkosi_image(
        name = "extra_packages_finalized",
        base = ":extra_packages_base",
        config_tree = ":two_stage_config_tree",
        image_id = "rules-mkosi-ab",
        image_version = "1",
        mode = "release",
        unified_kernel_image = "unsigned",
        tags = ["manual"],
    )
    _base_test(name = "extra_packages_base_test", packages = _PACKAGES, target_under_test = ":extra_packages_base")
    _finalize_test(
        name = "extra_packages_finalize_test",
        base = ":extra_packages_base",
        target_under_test = ":extra_packages_finalized",
    )
    return [":extra_packages_base_test", ":extra_packages_finalize_test"]

def _declare_one_stage():
    """Declares a one-stage release and a tracer with extra packages, and returns their tests."""
    mkosi_config_tree(name = "extra_packages_config_tree", src = "testdata/extra-packages-config")
    mkosi_image(
        name = "extra_packages_release",
        config_tree = ":extra_packages_config_tree",
        debian_snapshot = _SNAPSHOT,
        extra_packages = _PACKAGES,
        image_id = "rules-mkosi-extra",
        image_version_from_inputs = True,
        mode = "release",
        release_seed = _SEED,
        release_source_date_epoch = 0,
        tags = ["manual"],
    )
    mkosi_reproducibility_manifest(
        name = "extra_packages_reproducibility",
        image = ":extra_packages_release",
        tags = ["manual"],
    )
    native.filegroup(
        name = "extra_packages_release_inputs_manifest",
        srcs = [":extra_packages_release"],
        output_group = "image_version_inputs",
        tags = ["manual"],
    )
    _image_test(
        name = "extra_packages_release_test",
        derived_version = True,
        packages = _PACKAGES,
        target_under_test = ":extra_packages_release",
    )
    _reproducibility_test(
        name = "extra_packages_reproducibility_test",
        image = ":extra_packages_release",
        target_under_test = ":extra_packages_reproducibility",
    )
    return [":extra_packages_release_test", ":extra_packages_reproducibility_test"]

def _declare_tracer():
    """Declares a tracer that installs extra packages from the Debian snapshot mirror, and returns its test."""
    mkosi_image(
        name = "extra_packages_tracer",
        config = "testdata/minimal.conf",
        debian_snapshot = _SNAPSHOT,
        extra_packages = _PACKAGES,
        tags = ["manual"],
    )
    _image_test(name = "extra_packages_tracer_test", packages = _PACKAGES, target_under_test = ":extra_packages_tracer")
    return [":extra_packages_tracer_test"]

def extra_packages_test_suite(name):
    """Declares the extra_packages fixtures and their analysis tests.

    ci/verify-release-reproducibility.sh builds extra_packages_reproducibility twice.

    Args:
      name: Name of the test suite.
    """
    _declare_fixture_packages()
    native.test_suite(
        name = name,
        tests = _declare_one_stage() + _declare_tracer() + _declare_two_stage() + _declare_failures(),
    )
