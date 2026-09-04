"""Typed systemd-sysupdate A/B release bundle."""

load("//mkosi/private:mkosi_image.bzl", "MkosiImageInfo")
load("//mkosi/private:secure_boot.bzl", "SecureBootSignedUkiInfo")

SysupdateAbInfo = provider(
    doc = "Immutable A/B update artifacts, definitions, layout, and boot policy.",
    fields = {
        "format_version": "Provider schema, rules-mkosi-sysupdate-ab-v1.",
        "slot_a": "Typed slot A root, verity, signed UKI, and version.",
        "slot_b": "Typed slot B root, verity, signed UKI, and version.",
        "layout": "Validated JSON layout and immutable artifact digests.",
        "root_transfer": "systemd-sysupdate root partition transfer definition.",
        "verity_transfer": "systemd-sysupdate verity partition transfer definition.",
        "uki_transfer": "systemd-sysupdate signed UKI transfer definition.",
        "boot_attempts": "Initial systemd-boot attempts for a new UKI.",
        "sysupdate_binary": "Declared absolute binary path inside the built guest.",
        "firmware": "Firmware policy; always uefi.",
    },
)

def _slot(image, signed_uki, version):
    return struct(
        root = image.root_image,
        verity = image.root_hash_image,
        signed_uki = signed_uki.signed_uki,
        version = version,
    )

def _transfer(source_pattern, target, boot_attempts = 0):
    if target == "partition":
        target_lines = """Type=partition
Path=auto
MatchPattern={pattern}
MatchPartitionType={partition_type}
ReadOnly=yes
InstancesMax=2
""".format(
            pattern = source_pattern[:-4],
            partition_type = "root-x86-64" if source_pattern.startswith("root-") else "root-x86-64-verity",
        )
    else:
        target_lines = """Type=regular-file
Path=EFI/Linux
PathRelativeTo=boot
MatchPattern=rules-mkosi_@v+@l-@d.efi
Mode=0444
TriesLeft={boot_attempts}
TriesDone=0
InstancesMax=2
""".format(boot_attempts = boot_attempts)
    return """[Transfer]
MinVersion=257
ProtectVersion=%A
Verify=no

[Source]
Type=regular-file
Path=.
PathRelativeTo=explicit
MatchPattern={source}

[Target]
{target}""".format(source = source_pattern, target = target_lines)

def _sysupdate_ab_impl(ctx):
    if ctx.attr.firmware != "uefi":
        fail("systemd-sysupdate A/B layouts require firmware='uefi'; BIOS/SeaBIOS is unsupported")
    images = [ctx.attr.slot_a_image[MkosiImageInfo], ctx.attr.slot_b_image[MkosiImageInfo]]
    signed = [
        ctx.attr.slot_a_signed_uki[SecureBootSignedUkiInfo],
        ctx.attr.slot_b_signed_uki[SecureBootSignedUkiInfo],
    ]
    for index, image in enumerate(images):
        if image.firmware != "uefi":
            fail("slot {} image must use uefi firmware".format(("a", "b")[index]))
        if image.root_image == None or image.root_hash_image == None:
            fail("slot {} image must expose split root and verity artifacts".format(("a", "b")[index]))
    if ctx.attr.slot_a_version == ctx.attr.slot_b_version:
        fail("slot versions must differ")

    root_transfer = ctx.actions.declare_file(ctx.label.name + ".root.transfer")
    verity_transfer = ctx.actions.declare_file(ctx.label.name + ".verity.transfer")
    uki_transfer = ctx.actions.declare_file(ctx.label.name + ".uki.transfer")
    ctx.actions.write(root_transfer, _transfer("root-@v.raw", "partition"))
    ctx.actions.write(verity_transfer, _transfer("verity-@v.raw", "partition"))
    ctx.actions.write(uki_transfer, _transfer("rules-mkosi_@v.efi", "file", ctx.attr.boot_attempts))

    layout = ctx.actions.declare_file(ctx.label.name + ".layout.json")
    specification = ctx.actions.declare_file(ctx.label.name + ".layout-input.json")
    slots = {}
    artifacts = {}
    files = []
    for index, name in enumerate(("a", "b")):
        image = images[index]
        uki = signed[index].signed_uki
        root_offset = ctx.attr.root_a_offset if name == "a" else ctx.attr.root_b_offset
        verity_offset = ctx.attr.verity_a_offset if name == "a" else ctx.attr.verity_b_offset
        version = ctx.attr.slot_a_version if name == "a" else ctx.attr.slot_b_version
        slots[name] = {
            "root": {"offset": root_offset, "size": ctx.attr.root_size},
            "verity": {"offset": verity_offset, "size": ctx.attr.verity_size},
            "version": version,
        }
        artifacts[name] = {
            "root": image.root_image.path,
            "verity": image.root_hash_image.path,
            "uki": uki.path,
        }
        files.extend([image.root_image, image.root_hash_image, uki])
    ctx.actions.write(specification, json.encode({
        "artifacts": artifacts,
        "boot_attempts": ctx.attr.boot_attempts,
        "slots": slots,
    }))
    python = ctx.toolchains["//mkosi/toolchain:toolchain_type"].mkosi
    arguments = ctx.actions.args()
    arguments.add(ctx.file._projector)
    arguments.add("--spec", specification)
    arguments.add("--output", layout)
    ctx.actions.run(
        executable = python.python,
        arguments = [arguments],
        inputs = depset([ctx.file._projector, specification] + files, transitive = [python.python_runtime_files]),
        tools = [python.python_files_to_run],
        outputs = [layout],
        env = {"PATH": "", "PYTHONNOUSERSITE": "1"},
        mnemonic = "MkosiSysupdateAbProjection",
    )
    slot_a = _slot(images[0], signed[0], ctx.attr.slot_a_version)
    slot_b = _slot(images[1], signed[1], ctx.attr.slot_b_version)
    outputs = files + [layout, root_transfer, verity_transfer, uki_transfer]
    return [
        DefaultInfo(files = depset(outputs)),
        SysupdateAbInfo(
            format_version = "rules-mkosi-sysupdate-ab-v1",
            slot_a = slot_a,
            slot_b = slot_b,
            layout = layout,
            root_transfer = root_transfer,
            verity_transfer = verity_transfer,
            uki_transfer = uki_transfer,
            boot_attempts = ctx.attr.boot_attempts,
            sysupdate_binary = "/usr/lib/systemd/systemd-sysupdate",
            firmware = "uefi",
        ),
    ]

sysupdate_ab = rule(
    implementation = _sysupdate_ab_impl,
    attrs = {
        "slot_a_image": attr.label(mandatory = True, providers = [MkosiImageInfo]),
        "slot_a_signed_uki": attr.label(mandatory = True, providers = [SecureBootSignedUkiInfo]),
        "slot_a_version": attr.string(mandatory = True),
        "slot_b_image": attr.label(mandatory = True, providers = [MkosiImageInfo]),
        "slot_b_signed_uki": attr.label(mandatory = True, providers = [SecureBootSignedUkiInfo]),
        "slot_b_version": attr.string(mandatory = True),
        "firmware": attr.string(default = "uefi"),
        "boot_attempts": attr.int(default = 3),
        "root_a_offset": attr.int(default = 1048576),
        "root_b_offset": attr.int(default = 537919488),
        "root_size": attr.int(default = 536870912),
        "verity_a_offset": attr.int(default = 1074790400),
        "verity_b_offset": attr.int(default = 1141899264),
        "verity_size": attr.int(default = 67108864),
        "_projector": attr.label(default = "//mkosi/private:sysupdate_ab.py", allow_single_file = True),
    },
    doc = "Builds a UEFI-only signed systemd-sysupdate A/B release bundle.",
    toolchains = ["//mkosi/toolchain:toolchain_type"],
)
