"""Offline payload materialization for systemd-sysupdate runtime tests."""

load(":mkosi_image.bzl", "MkosiImageInfo")
load(":secure_boot.bzl", "SecureBootSignedUkiInfo")

def _impl(ctx):
    image = ctx.attr.image[MkosiImageInfo]
    signed = ctx.attr.signed_uki[SecureBootSignedUkiInfo]
    if image.root_image == None or image.root_hash_image == None:
        fail("image must expose split root and verity artifacts")
    output = ctx.actions.declare_directory(ctx.label.name)
    python = ctx.toolchains["//mkosi/toolchain:toolchain_type"].mkosi
    args = ctx.actions.args()
    args.add(ctx.file._builder)
    args.add("--root", image.root_image)
    args.add("--verity", image.root_hash_image)
    args.add("--uki", signed.signed_uki)
    args.add("--version", ctx.attr.version)
    args.add("--output", output.path)
    ctx.actions.run(
        executable = python.python,
        arguments = [args],
        inputs = depset(
            [ctx.file._builder, image.root_image, image.root_hash_image, signed.signed_uki],
            transitive = [python.python_runtime_files],
        ),
        tools = [python.python_files_to_run],
        outputs = [output],
        env = {"PATH": "", "PYTHONNOUSERSITE": "1"},
        mnemonic = "MkosiSysupdatePayload",
    )
    return [DefaultInfo(files = depset([output]))]

sysupdate_update_payload = rule(
    implementation = _impl,
    attrs = {
        "image": attr.label(mandatory = True, providers = [MkosiImageInfo]),
        "signed_uki": attr.label(mandatory = True, providers = [SecureBootSignedUkiInfo]),
        "version": attr.string(mandatory = True),
        "_builder": attr.label(
            default = "//mkosi/private:sysupdate_payload.py",
            allow_single_file = True,
        ),
    },
    toolchains = ["//mkosi/toolchain:toolchain_type"],
)
