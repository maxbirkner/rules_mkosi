"""Analysis tests for two-stage release images: a cached mkosi_base and its versioned finalization."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")
load(
    "//mkosi:defs.bzl",
    "DebianSnapshotInfo",
    "MkosiBaseInfo",
    "MkosiImageInfo",
    "mkosi_base",
    "mkosi_config_tree",
    "mkosi_image",
    "mkosi_reproducibility_manifest",
    "mkosi_source_tree",
)

_SEED = "00000000-0000-4000-8000-000000000007"

def _action(env, mnemonic):
    actions = [action for action in analysistest.target_actions(env) if action.mnemonic == mnemonic]
    asserts.equals(env, 1, len(actions), "expected one %s action" % mnemonic)
    return actions[0]

def _option_value(argv, option):
    if option not in argv:
        return None
    return argv[argv.index(option) + 1]

def _preamble(argv):
    return argv[:argv.index("--")]

def _mkosi_arguments(argv):
    return argv[argv.index("--") + 1:]

def _base_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    info = target[MkosiBaseInfo]
    snapshot = ctx.attr.debian_snapshot[DebianSnapshotInfo]
    asserts.equals(env, "mkosi-base-v1", info.format_version)
    asserts.equals(env, "root.tar", info.root_tree.basename)
    asserts.equals(env, "two_stage_base.initrd", info.initrd.basename)
    asserts.equals(env, snapshot.lock_sha256, info.debian_snapshot.lock_sha256)
    asserts.equals(env, _SEED, info.release_seed)
    asserts.equals(env, 0, info.release_source_date_epoch)
    asserts.equals(env, [info.root_tree, info.initrd], target[DefaultInfo].files.to_list())

    action = _action(env, "MkosiBase")
    asserts.equals(env, [info.root_tree, info.initrd], action.outputs.to_list())
    preamble = _preamble(action.argv)
    asserts.equals(env, snapshot.repository.path, _option_value(preamble, "--debian-snapshot-repository"))
    asserts.equals(env, info.initrd.path, _option_value(preamble, "--release-base-initrd-output"))
    asserts.equals(env, _SEED, _option_value(preamble, "--release-seed"))
    asserts.equals(env, "uefi", _option_value(preamble, "--release-firmware"))
    arguments = _mkosi_arguments(action.argv)
    for argument in ("--format=tar", "--bootable=no", "--initrd=default", "--environment=INITRD=No"):
        asserts.true(env, argument in arguments, argument)
    asserts.equals(env, "root", _option_value(arguments, "--output"))
    asserts.equals(env, info.root_tree.dirname, _option_value(arguments, "--output-directory"))

    # The base action must not depend on any version so that a new version reuses its cached result.
    for argument in action.argv:
        for prefix in ("--image-version", "--image-id", "--slot-label"):
            asserts.false(env, argument.startswith(prefix), argument)
    inputs = action.inputs.to_list()
    asserts.true(env, snapshot.repository in inputs)
    for version_input in ctx.files.version_inputs:
        asserts.false(env, version_input in inputs, version_input.path)
    asserts.false(env, "image_version.py" in [file.basename for file in inputs])
    return analysistest.end(env)

_base_test = analysistest.make(
    _base_test_impl,
    attrs = {
        "debian_snapshot": attr.label(providers = [DebianSnapshotInfo], mandatory = True),
        "version_inputs": attr.label_list(allow_files = True),
    },
)

def _finalize_test_impl(ctx):
    env = analysistest.begin(ctx)
    info = analysistest.target_under_test(env)[MkosiImageInfo]
    base = ctx.attr.base[MkosiBaseInfo]
    version_file = ctx.file.version_file
    asserts.equals(env, "rules-mkosi-ab", info.image_id)
    asserts.equals(env, None, info.image_version)
    asserts.equals(env, version_file, info.image_version_file)
    for field in ("raw_image", "partition_metadata", "uki", "uki_metadata", "build_metadata"):
        asserts.true(env, getattr(info, field) != None, field)

    image_action = _action(env, "MkosiImage")
    preamble = _preamble(image_action.argv)
    asserts.false(env, "--debian-snapshot-repository" in preamble)
    asserts.equals(env, base.root_tree.path, _option_value(preamble, "--release-base-tree"))
    asserts.equals(env, base.initrd.path, _option_value(preamble, "--release-initrd"))
    asserts.equals(env, base.release_seed, _option_value(preamble, "--release-seed"))
    asserts.equals(env, str(base.release_source_date_epoch), _option_value(preamble, "--release-source-date-epoch"))
    asserts.equals(env, base.debian_snapshot.snapshot, _option_value(preamble, "--release-snapshot"))
    asserts.equals(env, version_file.path, _option_value(preamble, "--image-version-file"))
    arguments = _mkosi_arguments(image_action.argv)
    asserts.equals(env, base.root_tree.path, _option_value(arguments, "--base-tree"))
    asserts.equals(env, base.initrd.path, _option_value(arguments, "--initrd"))
    asserts.true(env, "--image-id=rules-mkosi-ab" in arguments)
    asserts.true(env, "--cache-only=always" in arguments)
    asserts.equals(env, base.debian_snapshot.distribution, image_action.env["MKOSI_HOST_DISTRIBUTION"])
    asserts.equals(env, str(base.release_source_date_epoch), image_action.env["SOURCE_DATE_EPOCH"])

    # Finalization consumes the base artifacts and the version, but neither the snapshot nor package installation.
    inputs = image_action.inputs.to_list()
    asserts.true(env, base.root_tree in inputs)
    asserts.true(env, base.initrd in inputs)
    asserts.true(env, version_file in inputs)
    asserts.false(env, base.debian_snapshot.repository in inputs)
    for action in analysistest.target_actions(env):
        asserts.false(env, action.mnemonic == "MkosiBase")
        for output in action.outputs.to_list():
            asserts.false(env, output in (base.root_tree, base.initrd), output.path)

    metadata_action = _action(env, "MkosiBuildMetadata")
    metadata = json.decode(_option_value(metadata_action.argv, "--metadata-json"))
    asserts.equals(env, "mkosi-image-build-metadata-v3", metadata["format_version"])
    asserts.equals(env, base.debian_snapshot.lock_sha256, metadata["debian_snapshot"]["lock_sha256"])
    asserts.equals(
        env,
        {"seed": base.release_seed, "source_date_epoch": base.release_source_date_epoch},
        metadata["reproducibility"],
    )
    asserts.equals(env, "release", metadata["mode"])
    return analysistest.end(env)

_finalize_test = analysistest.make(
    _finalize_test_impl,
    attrs = {
        "base": attr.label(providers = [MkosiBaseInfo], mandatory = True),
        "version_file": attr.label(allow_single_file = True, mandatory = True),
    },
)

def _expected_failure_test_impl(ctx):
    env = analysistest.begin(ctx)
    asserts.expect_failure(env, ctx.attr.expected_error)
    return analysistest.end(env)

_expected_failure_test = analysistest.make(
    _expected_failure_test_impl,
    expect_failure = True,
    attrs = {"expected_error": attr.string(mandatory = True)},
)

def mkosi_base_test_suite(name):
    """Declares two-stage release fixtures and their analysis tests.

    The stamped fixtures are also built by ci/verify-two-stage-cache.sh and
    ci/verify-release-reproducibility.sh.

    Args:
      name: Name of the test suite.
    """
    mkosi_config_tree(
        name = "two_stage_base_config_tree",
        src = "testdata/two-stage-base-config",
    )
    mkosi_config_tree(
        name = "two_stage_config_tree",
        src = "testdata/two-stage-config",
    )
    mkosi_base(
        name = "two_stage_base",
        config_tree = ":two_stage_base_config_tree",
        debian_snapshot = "@mkosi_debian_snapshot//:repository",
        release_seed = _SEED,
        release_source_date_epoch = 0,
        tags = ["manual"],
    )

    # The version comes from Bazel workspace status, as in the documented stamping example.
    native.genrule(
        name = "two_stage_version",
        outs = ["two_stage_version.txt"],
        cmd = "sed -n 's/^STABLE_RULES_MKOSI_TWO_STAGE_VERSION //p' bazel-out/stable-status.txt > $@",
        stamp = 1,
        tags = ["manual"],
    )
    mkosi_image(
        name = "two_stage_release",
        base = ":two_stage_base",
        config_tree = ":two_stage_config_tree",
        image_id = "rules-mkosi-ab",
        image_version_file = ":two_stage_version",
        mode = "release",
        unified_kernel_image = "unsigned",
        tags = ["manual"],
    )
    mkosi_reproducibility_manifest(
        name = "two_stage_reproducibility",
        image = ":two_stage_release",
        tags = ["manual"],
    )
    _base_test(
        name = "two_stage_base_test",
        debian_snapshot = "@mkosi_debian_snapshot//:repository",
        target_under_test = ":two_stage_base",
        version_inputs = [":two_stage_version"],
    )
    _finalize_test(
        name = "two_stage_finalize_test",
        base = ":two_stage_base",
        target_under_test = ":two_stage_release",
        version_file = ":two_stage_version",
    )
    tests = [":two_stage_base_test", ":two_stage_finalize_test"]

    mkosi_source_tree(
        name = "two_stage_source_tree",
        src = "testdata/source-tree",
        tags = ["manual"],
    )
    common = {
        "base": ":two_stage_base",
        "config_tree": ":two_stage_config_tree",
        "mode": "release",
        "tags": ["manual"],
    }
    inherited = "debian_snapshot, release_seed, and release_source_date_epoch come from base"
    for subject, kwargs, expected_error in [
        ("tracer", {"mode": "tracer"}, "base requires release mode"),
        ("snapshot", {"debian_snapshot": "@mkosi_debian_snapshot//:repository"}, inherited),
        ("seed", {"release_seed": _SEED}, inherited),
        ("epoch", {"release_source_date_epoch": 0}, inherited),
        ("bios", {"firmware": "bios"}, "base requires uefi firmware"),
        (
            "source_trees",
            {"source_trees": {"src": ":two_stage_source_tree"}},
            "source_trees cannot be combined with base",
        ),
    ]:
        mkosi_image(name = "invalid_%s_finalize_subject" % subject, **dict(common, **kwargs))
        _expected_failure_test(
            name = "invalid_%s_finalize_test" % subject,
            expected_error = expected_error,
            target_under_test = ":invalid_%s_finalize_subject" % subject,
        )
        tests.append(":invalid_%s_finalize_test" % subject)

    epoch_error = "mkosi_base requires a non-negative release_source_date_epoch"
    for subject, kwargs, expected_error in [
        ("seed", {"release_source_date_epoch": 0}, "mkosi_base requires release_seed"),
        ("epoch", {"release_seed": _SEED}, epoch_error),
        ("negative_epoch", {"release_seed": _SEED, "release_source_date_epoch": -2}, epoch_error),
    ]:
        mkosi_base(
            name = "invalid_%s_base_subject" % subject,
            config_tree = ":two_stage_base_config_tree",
            debian_snapshot = "@mkosi_debian_snapshot//:repository",
            tags = ["manual"],
            **kwargs
        )
        _expected_failure_test(
            name = "invalid_%s_base_test" % subject,
            expected_error = expected_error,
            target_under_test = ":invalid_%s_base_subject" % subject,
        )
        tests.append(":invalid_%s_base_test" % subject)

    native.test_suite(
        name = name,
        tests = tests,
    )
