"""Test-only rule that builds a small, reproducible Debian binary package with deb_fixture.py."""

def _test_deb_package_impl(ctx):
    package = ctx.actions.declare_file(ctx.label.name + ".deb")
    specification = ctx.actions.declare_file(ctx.label.name + ".deb.json")
    control = [
        ["Package", ctx.attr.package],
        ["Version", ctx.attr.version],
        ["Architecture", ctx.attr.architecture],
        ["Maintainer", "rules_mkosi tests <rules-mkosi-tests@example.invalid>"],
    ] + [[field, value] for field, value in ctx.attr.control_fields.items()] + [["Description", ctx.attr.description]]
    ctx.actions.write(specification, json.encode({"control": control, "files": ctx.attr.files, "scripts": ctx.attr.scripts}))
    builder = ctx.attr._builder[DefaultInfo]
    ctx.actions.run(
        executable = ctx.executable._builder,
        arguments = [specification.path, package.path],
        inputs = [specification],
        tools = [builder.files_to_run],
        outputs = [package],
        mnemonic = "TestDebPackage",
    )
    return [DefaultInfo(files = depset([package]))]

test_deb_package = rule(
    implementation = _test_deb_package_impl,
    attrs = {
        "architecture": attr.string(default = "all", doc = "Debian architecture of the package."),
        "control_fields": attr.string_dict(doc = "Further control fields, such as Depends, in order."),
        "description": attr.string(default = "rules_mkosi test package", doc = "Description field."),
        "files": attr.string_dict(doc = "Content of the packaged files, keyed by absolute path."),
        "package": attr.string(mandatory = True, doc = "Package name."),
        "scripts": attr.string_dict(doc = "Maintainer scripts, such as postinst, keyed by name."),
        "version": attr.string(mandatory = True, doc = "Package version."),
        "_builder": attr.label(cfg = "exec", default = "//mkosi/tests:deb_fixture", executable = True),
    },
    doc = "Builds <name>.deb, owned by root with zero timestamps, so that equal attributes give equal bytes.",
)
