"""Analysis tests for versioned image identity, A/B update rules and multi-boot lifecycle tests."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")
load(
    "//mkosi:defs.bzl",
    "MkosiImageInfo",
    "MkosiRootfsPayloadInfo",
    "SecureBootSignedUkiInfo",
    "SysupdatePayloadInfo",
    "mkosi_image",
    "qemu_ovmf_boot_config",
    "sysupdate_payload",
    "sysupdate_transfers",
)
load(":analysis_test_helpers.bzl", "argv_preamble", "option_value", "single_action")

def _template_variables_impl(ctx):
    return [platform_common.TemplateVariableInfo(ctx.attr.variables)]

_template_variables = rule(
    implementation = _template_variables_impl,
    attrs = {"variables": attr.string_dict(mandatory = True)},
)

def _signed_uki_impl(ctx):
    request = ctx.actions.declare_file(ctx.label.name + ".secure-boot-request.json")
    signed_uki = ctx.actions.declare_file(ctx.label.name + ".signed.efi")
    ctx.actions.write(request, "{}")
    ctx.actions.write(signed_uki, "")
    return [SecureBootSignedUkiInfo(
        format_version = "mkosi-secure-boot-signed-uki-v2",
        request = request,
        signed_uki = signed_uki,
        verification_metadata = request,
    )]

_signed_uki = rule(implementation = _signed_uki_impl)

def _image_identity_test_impl(ctx):
    env = analysistest.begin(ctx)
    info = analysistest.target_under_test(env)[MkosiImageInfo]
    expected_id = ctx.attr.expected_id or None
    expected_version = ctx.attr.expected_version or None
    asserts.equals(env, expected_id, info.image_id)
    asserts.equals(env, expected_version, info.image_version)
    asserts.equals(env, None, info.image_version_file)

    argv = single_action(env, "MkosiImage").argv
    asserts.false(env, "--image-version-file" in argv)
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
        partition_argv = single_action(env, "MkosiPartitionMetadata").argv
        expected_slot = ctx.attr.expected_slot_label or None
        asserts.equals(env, expected_slot, option_value(partition_argv, "--slot-label"))
    return analysistest.end(env)

_image_identity_test = analysistest.make(
    _image_identity_test_impl,
    attrs = {
        "expected_id": attr.string(),
        "expected_slot_label": attr.string(),
        "expected_version": attr.string(),
    },
)

def _image_version_file_identity_test_impl(ctx):
    env = analysistest.begin(ctx)
    info = analysistest.target_under_test(env)[MkosiImageInfo]
    version_file = ctx.file.version_file
    asserts.equals(env, "rules-mkosi-ab", info.image_id)
    asserts.equals(env, None, info.image_version)
    asserts.equals(env, version_file, info.image_version_file)

    image_action = single_action(env, "MkosiImage")
    argv = image_action.argv
    asserts.equals(env, version_file.path, option_value(argv_preamble(argv), "--image-version-file"))
    asserts.equals(env, "rules-mkosi-ab", option_value(argv_preamble(argv), "--slot-label-image-id"))
    asserts.true(env, "--image-id=rules-mkosi-ab" in argv)
    asserts.false(env, any([argument.startswith("--image-version=") for argument in argv]))
    image_inputs = image_action.inputs.to_list()
    asserts.true(env, version_file in image_inputs)
    asserts.true(env, "image_version.py" in [file.basename for file in image_inputs])

    partition_action = single_action(env, "MkosiPartitionMetadata")
    asserts.equals(env, None, option_value(partition_action.argv, "--slot-label"))
    asserts.equals(env, "rules-mkosi-ab", option_value(partition_action.argv, "--slot-label-image-id"))
    asserts.equals(env, version_file.path, option_value(partition_action.argv, "--image-version-file"))
    asserts.true(env, version_file in partition_action.inputs.to_list())

    metadata_action = single_action(env, "MkosiBuildMetadata")
    asserts.equals(env, [info.build_metadata], metadata_action.outputs.to_list())
    asserts.true(env, version_file in metadata_action.inputs.to_list())
    asserts.true(env, metadata_action.argv[1].endswith("/image_version.py"))
    asserts.equals(env, "build-metadata", metadata_action.argv[2])
    asserts.equals(env, version_file.path, option_value(metadata_action.argv, "--image-version-file"))
    asserts.equals(env, info.build_metadata.path, option_value(metadata_action.argv, "--output"))
    metadata = json.decode(option_value(metadata_action.argv, "--metadata-json"))
    asserts.equals(env, {"id": "rules-mkosi-ab", "version": None}, metadata["image"])
    asserts.equals(env, "mkosi-image-build-metadata-v3", metadata["format_version"])
    asserts.equals(env, "", metadata_action.env["PATH"])
    return analysistest.end(env)

_image_version_file_identity_test = analysistest.make(
    _image_version_file_identity_test_impl,
    attrs = {"version_file": attr.label(allow_single_file = True, mandatory = True)},
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
    action = single_action(env, "MkosiSysupdateTransfers")
    asserts.equals(env, [info.artifact], action.outputs.to_list())
    argv = action.argv
    asserts.true(env, argv[1].endswith("/sysupdate.py"))
    asserts.equals(env, "transfers", argv[2])
    asserts.equals(env, ctx.attr.expected_id, option_value(argv, "--image-id"))
    asserts.equals(env, ctx.attr.expected_boot_attempts, option_value(argv, "--boot-attempts"))
    asserts.equals(env, ctx.attr.expected_instances, option_value(argv, "--instances"))
    asserts.equals(env, "", action.env["PATH"])
    return analysistest.end(env)

_transfers_test = analysistest.make(
    _transfers_test_impl,
    attrs = {
        "expected_boot_attempts": attr.string(mandatory = True),
        "expected_destination": attr.string(mandatory = True),
        "expected_id": attr.string(mandatory = True),
        "expected_instances": attr.string(mandatory = True),
    },
)

def _assert_payload_version(env, ctx, info, action):
    argv = action.argv
    version_file = ctx.file.expected_version_file
    if version_file:
        asserts.equals(env, None, info.image_version)
        asserts.equals(env, version_file, info.image_version_file)
        asserts.false(env, "--image-version" in argv)
        asserts.equals(env, version_file.path, option_value(argv, "--image-version-file"))
        asserts.true(env, version_file in action.inputs.to_list())
        asserts.true(env, "image_version.py" in [file.basename for file in action.inputs.to_list()])
    else:
        asserts.equals(env, "7", info.image_version)
        asserts.equals(env, None, info.image_version_file)
        asserts.equals(env, "7", option_value(argv, "--image-version"))
        asserts.false(env, "--image-version-file" in argv)

def _payload_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    info = target[SysupdatePayloadInfo]
    asserts.equals(env, "rules-mkosi-ab", info.image_id)
    asserts.true(env, info.directory.is_directory)
    asserts.equals(env, [info.directory], target[DefaultInfo].files.to_list())
    action = single_action(env, "MkosiSysupdatePayload")
    argv = action.argv
    asserts.equals(env, "payload", argv[2])
    asserts.equals(env, "rules-mkosi-ab", option_value(argv, "--image-id"))
    _assert_payload_version(env, ctx, info, action)
    image = ctx.attr.image_name
    for option, basename in (
        ("--root-hash", image + ".roothash"),
        ("--partition-metadata", image + ".partitions.json"),
        ("--root-image", image + ".root.raw"),
        ("--verity-image", image + ".root-verity.raw"),
        ("--verity-metadata", image + ".verity.json"),
        ("--uki", image + ".efi"),
    ):
        asserts.true(env, option_value(argv, option).endswith("/" + basename), option)
        asserts.true(env, basename in [file.basename for file in action.inputs.to_list()], basename)
    for option, basename in (
        ("--signed-uki", "signed_uki_subject.signed.efi"),
        ("--signing-request", "signed_uki_subject.secure-boot-request.json"),
    ):
        if ctx.attr.expect_signed_uki:
            asserts.true(env, option_value(argv, option).endswith("/" + basename), option)
            asserts.true(env, basename in [file.basename for file in action.inputs.to_list()], basename)
        else:
            asserts.false(env, option in argv, option)
    asserts.equals(env, info.directory.path, option_value(argv, "--output"))
    return analysistest.end(env)

_payload_test = analysistest.make(
    _payload_test_impl,
    attrs = {
        "expect_signed_uki": attr.bool(),
        "expected_version_file": attr.label(allow_single_file = True),
        "image_name": attr.string(default = "versioned_release_subject"),
    },
)

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
        "expected_allow_reboot": attr.bool(),
        "expected_mount_tags": attr.string_list(),
        "expected_progress_markers": attr.string_list(),
    },
)

def _boot_config(name, **kwargs):
    attrs = {
        "boot_timeout_seconds": 180,
        "diagnostic_bytes": 4096,
        "image": ":debian_subject",
        "machine_args": ["-machine", "q35"],
        "qmp_initialization_timeout_seconds": 15,
        "readiness_marker": "READY",
        "shutdown_markers": ["SHUTDOWN"],
        "shutdown_timeout_seconds": 30,
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
    native.genrule(
        name = "release_version_file",
        outs = ["release_version.txt"],
        cmd = "echo 7 > $@",
        tags = ["manual"],
    )
    mkosi_image(
        name = "version_file_release_subject",
        config_tree = ":immutable_release_config_tree",
        debian_snapshot = "@mkosi_debian_snapshot//:repository",
        image_id = "rules-mkosi-ab",
        image_version_file = ":release_version_file",
        mode = "release",
        release_seed = "00000000-0000-4000-8000-000000000007",
        release_source_date_epoch = 0,
        unified_kernel_image = "unsigned",
        verity = "hash",
        tags = ["manual"],
    )
    _image_version_file_identity_test(
        name = "version_file_release_identity_test",
        target_under_test = ":version_file_release_subject",
        version_file = ":release_version_file",
    )

    # 'rules-mkosi-ab_<version>_verity' fills the 36-character GPT partition name limit exactly.
    mkosi_image(
        name = "longest_slot_label_release_subject",
        config_tree = ":immutable_release_config_tree",
        debian_snapshot = "@mkosi_debian_snapshot//:repository",
        image_id = "rules-mkosi-ab",
        image_version = "20261103.12abc",
        mode = "release",
        release_seed = "00000000-0000-4000-8000-000000000007",
        release_source_date_epoch = 0,
        unified_kernel_image = "unsigned",
        verity = "hash",
        tags = ["manual"],
    )
    _image_identity_test(
        name = "longest_slot_label_release_identity_test",
        expected_id = "rules-mkosi-ab",
        expected_slot_label = "rules-mkosi-ab_20261103.12abc",
        expected_version = "20261103.12abc",
        target_under_test = ":longest_slot_label_release_subject",
    )
    mkosi_image(
        name = "slot_label_too_long_release_subject",
        config_tree = ":immutable_release_config_tree",
        debian_snapshot = "@mkosi_debian_snapshot//:repository",
        image_id = "rules-mkosi-ab",
        image_version = "20261103.12abcd",
        mode = "release",
        release_seed = "00000000-0000-4000-8000-000000000007",
        release_source_date_epoch = 0,
        unified_kernel_image = "unsigned",
        verity = "hash",
        tags = ["manual"],
    )
    _expected_failure_test(
        name = "slot_label_too_long_release_test",
        expected_error = (
            "A/B verity partition label 'rules-mkosi-ab_20261103.12abcd_verity' is 37 characters, " +
            "but GPT partition names are limited to 36"
        ),
        target_under_test = ":slot_label_too_long_release_subject",
    )

    # Without verity there are no A/B slot labels, so a long version is accepted.
    mkosi_image(
        name = "long_version_without_verity_subject",
        config = "testdata/minimal.conf",
        image_id = "rules-mkosi-ab",
        image_version = "20261103011813.45eed0f.1",
        tags = ["manual"],
    )
    _image_identity_test(
        name = "long_version_without_verity_identity_test",
        expected_id = "rules-mkosi-ab",
        expected_version = "20261103011813.45eed0f.1",
        target_under_test = ":long_version_without_verity_subject",
    )
    mkosi_image(
        name = "versioned_plain_release_subject",
        config_tree = ":release_config_tree",
        debian_snapshot = "@mkosi_debian_snapshot//:repository",
        image_id = "rules-mkosi.plain_1",
        image_version = "1.2.RC1",
        mode = "release",
        release_seed = "00000000-0000-4000-8000-000000000007",
        release_source_date_epoch = 0,
        tags = ["manual"],
    )
    _image_identity_test(
        name = "versioned_plain_release_identity_test",
        expected_id = "rules-mkosi.plain_1",
        expected_version = "1.2.RC1",
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
        ":long_version_without_verity_identity_test",
        ":longest_slot_label_release_identity_test",
        ":slot_label_too_long_release_test",
        ":unversioned_release_identity_test",
        ":versioned_plain_release_identity_test",
        ":version_file_release_identity_test",
        ":versioned_release_identity_test",
    ]

    for subject, kwargs, expected_error in [
        ("uppercase_image_id", {"image_id": "Rules"}, "image_id must be non-empty and use only lowercase"),
        ("image_id_space", {"image_id": "rules mkosi"}, "image_id must be non-empty"),
        ("version_without_id", {"image_version": "1"}, "image_version requires image_id"),
        ("tilde_version", {"image_id": "rules", "image_version": "1~rc1"}, "image_version must be non-empty"),
        ("caret_version", {"image_id": "rules", "image_version": "1^git"}, "image_version must be non-empty"),
        ("underscore_version", {"image_id": "rules", "image_version": "1_2"}, "image_version must be non-empty"),
        ("boot_counter_version", {"image_id": "rules", "image_version": "1+2"}, "image_version must be non-empty"),
        ("dash_version", {"image_id": "rules", "image_version": "1-2"}, "image_version must be non-empty"),
        ("comma_version", {"image_id": "rules", "image_version": "1,2"}, "image_version must be non-empty"),
        ("undefined_variable_version", {"image_id": "rules", "image_version": "$(UNDEFINED_VERSION)"}, "UNDEFINED_VERSION"),
        (
            "version_and_version_file",
            {"image_id": "rules", "image_version": "7", "image_version_file": ":release_version_file"},
            "set at most one of image_version and image_version_file",
        ),
        ("version_file_without_id", {"image_version_file": ":release_version_file"}, "image_version_file requires image_id"),
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
        ("boot_attempts", {"boot_attempts": -1, "image_id": "rules"}, "boot_attempts must be non-negative"),
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
    _signed_uki(
        name = "signed_uki_subject",
        tags = ["manual"],
    )
    sysupdate_payload(
        name = "signed_payload_subject",
        image = ":versioned_release_subject",
        signed_uki = ":signed_uki_subject",
        tags = ["manual"],
    )
    _payload_test(
        name = "signed_payload_test",
        expect_signed_uki = True,
        target_under_test = ":signed_payload_subject",
    )
    sysupdate_payload(
        name = "version_file_payload_subject",
        image = ":version_file_release_subject",
        tags = ["manual"],
    )
    _payload_test(
        name = "version_file_payload_test",
        expected_version_file = ":release_version_file",
        image_name = "version_file_release_subject",
        target_under_test = ":version_file_payload_subject",
    )
    tests += [":signed_payload_test", ":version_file_payload_test", ":versioned_payload_test"]
    for subject, image, expected_error in [
        ("unversioned", ":immutable_release_subject", "image must set image_id and image_version or image_version_file"),
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
            {"expected_failure_marker": "FAILED", "progress_markers": ["FIRST"]},
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
