"""Analysis tests for versioned image identity, A/B update rules and multi-boot lifecycle tests."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")
load(
    "//mkosi:defs.bzl",
    "MkosiImageInfo",
    "MkosiRootfsPayloadInfo",
    "SysupdatePayloadInfo",
    "mkosi_image",
    "qemu_ovmf_boot_config",
    "sysupdate_payload",
    "sysupdate_transfers",
)

def _template_variables_impl(ctx):
    return [platform_common.TemplateVariableInfo(ctx.attr.variables)]

_template_variables = rule(
    implementation = _template_variables_impl,
    attrs = {"variables": attr.string_dict(mandatory = True)},
)

def _action(env, mnemonic):
    actions = [action for action in analysistest.target_actions(env) if action.mnemonic == mnemonic]
    asserts.equals(env, 1, len(actions), "expected one %s action" % mnemonic)
    return actions[0]

def _option_value(argv, option):
    if option not in argv:
        return None
    return argv[argv.index(option) + 1]

def _image_identity_test_impl(ctx):
    env = analysistest.begin(ctx)
    info = analysistest.target_under_test(env)[MkosiImageInfo]
    expected_id = ctx.attr.expected_id or None
    expected_version = ctx.attr.expected_version or None
    asserts.equals(env, expected_id, info.image_id)
    asserts.equals(env, expected_version, info.image_version)

    argv = _action(env, "MkosiImage").argv
    asserts.equals(env, expected_id != None, "--image-id=%s" % ctx.attr.expected_id in argv)
    asserts.equals(env, expected_version != None, "--image-version=%s" % ctx.attr.expected_version in argv)
    if expected_id == None:
        asserts.false(env, any([argument.startswith("--image-id") for argument in argv]))
    if expected_version == None:
        asserts.false(env, any([argument.startswith("--image-version") for argument in argv]))

    metadata_writes = [
        action
        for action in analysistest.target_actions(env)
        if action.outputs.to_list() == [info.build_metadata]
    ]
    asserts.equals(env, 1, len(metadata_writes))
    metadata = json.decode(metadata_writes[0].content)
    if expected_id == None:
        asserts.false(env, "image" in metadata)
    else:
        asserts.equals(env, {"id": expected_id, "version": expected_version}, metadata["image"])

    if info.partition_metadata != None:
        partition_argv = _action(env, "MkosiPartitionMetadata").argv
        expected_slot = ctx.attr.expected_slot_label or None
        asserts.equals(env, expected_slot, _option_value(partition_argv, "--slot-label"))
    return analysistest.end(env)

_image_identity_test = analysistest.make(
    _image_identity_test_impl,
    attrs = {
        "expected_id": attr.string(),
        "expected_version": attr.string(),
        "expected_slot_label": attr.string(),
    },
)

def _expected_failure_test_impl(ctx):
    env = analysistest.begin(ctx)
    asserts.expect_failure(env, ctx.attr.expected_error)
    return analysistest.end(env)

_expected_failure_test = analysistest.make(
    _expected_failure_test_impl,
    attrs = {"expected_error": attr.string(mandatory = True)},
    expect_failure = True,
)

def _transfers_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    info = target[MkosiRootfsPayloadInfo]
    asserts.equals(env, ctx.attr.expected_destination, info.destination)
    asserts.true(env, info.is_tree)
    asserts.true(env, info.is_generated)
    asserts.true(env, info.artifact.is_directory)
    asserts.equals(env, [info.artifact], target[DefaultInfo].files.to_list())
    action = _action(env, "MkosiSysupdateTransfers")
    asserts.equals(env, [info.artifact], action.outputs.to_list())
    argv = action.argv
    asserts.true(env, argv[1].endswith("/sysupdate.py"))
    asserts.equals(env, "transfers", argv[2])
    asserts.equals(env, ctx.attr.expected_id, _option_value(argv, "--image-id"))
    asserts.equals(env, ctx.attr.expected_boot_attempts, _option_value(argv, "--boot-attempts"))
    asserts.equals(env, ctx.attr.expected_instances, _option_value(argv, "--instances"))
    asserts.equals(env, "", action.env["PATH"])
    return analysistest.end(env)

_transfers_test = analysistest.make(
    _transfers_test_impl,
    attrs = {
        "expected_id": attr.string(mandatory = True),
        "expected_boot_attempts": attr.string(mandatory = True),
        "expected_instances": attr.string(mandatory = True),
        "expected_destination": attr.string(mandatory = True),
    },
)

def _payload_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    info = target[SysupdatePayloadInfo]
    asserts.equals(env, "rules-mkosi-ab", info.image_id)
    asserts.equals(env, "7", info.image_version)
    asserts.true(env, info.directory.is_directory)
    asserts.equals(env, [info.directory], target[DefaultInfo].files.to_list())
    action = _action(env, "MkosiSysupdatePayload")
    argv = action.argv
    asserts.equals(env, "payload", argv[2])
    asserts.equals(env, "rules-mkosi-ab", _option_value(argv, "--image-id"))
    asserts.equals(env, "7", _option_value(argv, "--image-version"))
    for option, basename in (
        ("--root-hash", "versioned_release_subject.roothash"),
        ("--partition-metadata", "versioned_release_subject.partitions.json"),
        ("--root-image", "versioned_release_subject.root.raw"),
        ("--verity-image", "versioned_release_subject.root-verity.raw"),
        ("--uki", "versioned_release_subject.efi"),
    ):
        asserts.true(env, _option_value(argv, option).endswith("/" + basename), option)
        asserts.true(env, basename in [file.basename for file in action.inputs.to_list()], basename)
    asserts.equals(env, info.directory.path, _option_value(argv, "--output"))
    return analysistest.end(env)

_payload_test = analysistest.make(_payload_test_impl)

def _lifecycle_boot_config_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    config_writes = [action for action in analysistest.target_actions(env) if action.mnemonic == "FileWrite"]
    asserts.equals(env, 1, len(config_writes))
    config = json.decode(config_writes[0].content)
    asserts.equals(env, ctx.attr.expected_progress_markers, config["progress_markers"])
    asserts.equals(env, ctx.attr.expected_allow_reboot, config["allow_reboot"])
    asserts.equals(env, ctx.attr.expected_mount_tags, [share["mount_tag"] for share in config["read_only_shares"]])
    runfiles = target[DefaultInfo].default_runfiles.files.to_list()
    for share in config["read_only_shares"]:
        asserts.true(
            env,
            share["directory"] in [file.short_path for file in runfiles if file.is_directory],
            "share %s is a directory runfile" % share["directory"],
        )
    return analysistest.end(env)

_lifecycle_boot_config_test = analysistest.make(
    _lifecycle_boot_config_test_impl,
    attrs = {
        "expected_progress_markers": attr.string_list(),
        "expected_allow_reboot": attr.bool(),
        "expected_mount_tags": attr.string_list(),
    },
)

def _boot_config(name, **kwargs):
    attrs = {
        "image": ":debian_subject",
        "readiness_marker": "READY",
        "shutdown_markers": ["SHUTDOWN"],
        "machine_args": ["-machine", "q35"],
        "boot_timeout_seconds": 180,
        "qmp_initialization_timeout_seconds": 15,
        "shutdown_timeout_seconds": 30,
        "diagnostic_bytes": 4096,
        "tags": ["manual"],
    }
    attrs.update(kwargs)
    qemu_ovmf_boot_config(name = name, **attrs)

def sysupdate_test_suite(name):
    """Defines analysis tests for image identity, sysupdate rules and multi-boot lifecycle configuration.

    The subjects reuse configuration trees declared by mkosi_image_test_suite in the same package.

    Args:
      name: Name of the generated test suite.
    """
    tests = []

    _template_variables(
        name = "os_release_variables",
        variables = {"OS_VERSION": "7"},
    )
    mkosi_image(
        name = "versioned_release_subject",
        config_tree = ":immutable_release_config_tree",
        debian_snapshot = "@mkosi_debian_snapshot//:repository",
        image_id = "rules-mkosi-ab",
        image_version = "$(OS_VERSION)",
        mode = "release",
        release_seed = "00000000-0000-4000-8000-000000000007",
        release_source_date_epoch = 0,
        toolchains = [":os_release_variables"],
        unified_kernel_image = "unsigned",
        verity = "hash",
        tags = ["manual"],
    )
    _image_identity_test(
        name = "versioned_release_identity_test",
        expected_id = "rules-mkosi-ab",
        expected_slot_label = "rules-mkosi-ab_7",
        expected_version = "7",
        target_under_test = ":versioned_release_subject",
    )
    mkosi_image(
        name = "versioned_plain_release_subject",
        config_tree = ":release_config_tree",
        debian_snapshot = "@mkosi_debian_snapshot//:repository",
        image_id = "rules-mkosi.plain_1",
        image_version = "1.2~rc1^git",
        mode = "release",
        release_seed = "00000000-0000-4000-8000-000000000007",
        release_source_date_epoch = 0,
        tags = ["manual"],
    )
    _image_identity_test(
        name = "versioned_plain_release_identity_test",
        expected_id = "rules-mkosi.plain_1",
        expected_version = "1.2~rc1^git",
        target_under_test = ":versioned_plain_release_subject",
    )
    mkosi_image(
        name = "image_id_only_subject",
        config = "testdata/minimal.conf",
        image_id = "rules-mkosi",
        tags = ["manual"],
    )
    _image_identity_test(
        name = "image_id_only_identity_test",
        expected_id = "rules-mkosi",
        target_under_test = ":image_id_only_subject",
    )
    _image_identity_test(
        name = "unversioned_release_identity_test",
        target_under_test = ":release_subject",
    )
    tests += [
        ":image_id_only_identity_test",
        ":unversioned_release_identity_test",
        ":versioned_plain_release_identity_test",
        ":versioned_release_identity_test",
    ]

    for subject, kwargs, expected_error in [
        ("uppercase_image_id", {"image_id": "Rules"}, "image_id must be non-empty and use only lowercase"),
        ("image_id_space", {"image_id": "rules mkosi"}, "image_id must be non-empty"),
        ("version_without_id", {"image_version": "1"}, "image_version requires image_id"),
        ("underscore_version", {"image_id": "rules", "image_version": "1_2"}, "image_version must be non-empty"),
        ("boot_counter_version", {"image_id": "rules", "image_version": "1+2"}, "image_version must be non-empty"),
        ("dash_version", {"image_id": "rules", "image_version": "1-2"}, "image_version must be non-empty"),
        ("undefined_variable_version", {"image_id": "rules", "image_version": "$(UNDEFINED_VERSION)"}, "UNDEFINED_VERSION"),
    ]:
        mkosi_image(
            name = "invalid_%s_subject" % subject,
            config = "testdata/minimal.conf",
            tags = ["manual"],
            **kwargs
        )
        _expected_failure_test(
            name = "invalid_%s_test" % subject,
            expected_error = expected_error,
            target_under_test = ":invalid_%s_subject" % subject,
        )
        tests.append(":invalid_%s_test" % subject)

    sysupdate_transfers(
        name = "default_transfers_subject",
        image_id = "rules-mkosi-ab",
        tags = ["manual"],
    )
    _transfers_test(
        name = "default_transfers_test",
        expected_boot_attempts = "3",
        expected_destination = "/usr/lib/sysupdate.d",
        expected_id = "rules-mkosi-ab",
        expected_instances = "2",
        target_under_test = ":default_transfers_subject",
    )
    sysupdate_transfers(
        name = "boundary_transfers_subject",
        boot_attempts = 0,
        destination = "/etc/sysupdate.d",
        image_id = "rules-mkosi-ab",
        instances = 3,
        tags = ["manual"],
    )
    _transfers_test(
        name = "boundary_transfers_test",
        expected_boot_attempts = "0",
        expected_destination = "/etc/sysupdate.d",
        expected_id = "rules-mkosi-ab",
        expected_instances = "3",
        target_under_test = ":boundary_transfers_subject",
    )
    tests += [":boundary_transfers_test", ":default_transfers_test"]
    for subject, kwargs, expected_error in [
        ("image_id", {"image_id": "Rules"}, "image_id must be non-empty"),
        ("boot_attempts", {"image_id": "rules", "boot_attempts": -1}, "boot_attempts must be non-negative"),
        ("instances", {"image_id": "rules", "instances": 1}, "instances must be at least 2"),
    ]:
        sysupdate_transfers(
            name = "invalid_transfers_%s_subject" % subject,
            tags = ["manual"],
            **kwargs
        )
        _expected_failure_test(
            name = "invalid_transfers_%s_test" % subject,
            expected_error = expected_error,
            target_under_test = ":invalid_transfers_%s_subject" % subject,
        )
        tests.append(":invalid_transfers_%s_test" % subject)

    sysupdate_payload(
        name = "versioned_payload_subject",
        image = ":versioned_release_subject",
        tags = ["manual"],
    )
    _payload_test(
        name = "versioned_payload_test",
        target_under_test = ":versioned_payload_subject",
    )
    tests.append(":versioned_payload_test")
    for subject, image, expected_error in [
        ("unversioned", ":immutable_release_subject", "image must set image_id and image_version"),
        ("without_verity", ":versioned_plain_release_subject", "unified_kernel_image = 'unsigned' and verity = 'hash'"),
    ]:
        sysupdate_payload(
            name = "invalid_%s_payload_subject" % subject,
            image = image,
            tags = ["manual"],
        )
        _expected_failure_test(
            name = "invalid_%s_payload_test" % subject,
            expected_error = expected_error,
            target_under_test = ":invalid_%s_payload_subject" % subject,
        )
        tests.append(":invalid_%s_payload_test" % subject)

    _boot_config(
        name = "lifecycle_boot_subject",
        allow_reboot = True,
        progress_markers = ["FIRST", "SECOND", "FIRST"],
        read_only_shares = {
            ":boundary_transfers_subject": "b.payload_2",
            ":default_transfers_subject": "a-payload",
        },
    )
    _lifecycle_boot_config_test(
        name = "lifecycle_boot_config_test",
        expected_allow_reboot = True,
        expected_mount_tags = ["a-payload", "b.payload_2"],
        expected_progress_markers = ["FIRST", "SECOND", "FIRST"],
        target_under_test = ":lifecycle_boot_subject",
    )
    _lifecycle_boot_config_test(
        name = "single_boot_config_test",
        target_under_test = ":analysis_boot_test_config",
    )
    tests += [":lifecycle_boot_config_test", ":single_boot_config_test"]
    for subject, kwargs, expected_error in [
        ("empty_progress_marker", {"progress_markers": ["FIRST", ""]}, "progress_markers must contain only nonempty markers"),
        (
            "progress_with_expected_failure",
            {"progress_markers": ["FIRST"], "expected_failure_marker": "FAILED"},
            "cannot be combined with expected_failure_marker",
        ),
        ("file_share", {"read_only_shares": {"testdata/minimal.conf": "payload"}}, "must provide exactly one directory"),
        ("empty_mount_tag", {"read_only_shares": {":default_transfers_subject": ""}}, "must be 1 to 31"),
        ("long_mount_tag", {"read_only_shares": {":default_transfers_subject": "p" * 32}}, "must be 1 to 31"),
        ("mount_tag_characters", {"read_only_shares": {":default_transfers_subject": "pay/load"}}, "must be 1 to 31"),
        (
            "duplicate_mount_tag",
            {"read_only_shares": {":boundary_transfers_subject": "payload", ":default_transfers_subject": "payload"}},
            "is used more than once",
        ),
    ]:
        _boot_config(name = "invalid_%s_boot_subject" % subject, **kwargs)
        _expected_failure_test(
            name = "invalid_%s_boot_test" % subject,
            expected_error = expected_error,
            target_under_test = ":invalid_%s_boot_subject" % subject,
        )
        tests.append(":invalid_%s_boot_test" % subject)

    native.test_suite(
        name = name,
        tests = tests,
    )
