"""Update and staleness targets for a consumer-owned Debian snapshot lock."""

def _generator_impl(ctx):
    generator = ctx.attr._generator[DefaultInfo]
    executable = ctx.actions.declare_file(ctx.label.name)
    ctx.actions.symlink(
        output = executable,
        target_file = generator.files_to_run.executable,
        is_executable = True,
    )
    runfiles = ctx.runfiles(files = ctx.files.data).merge(generator.default_runfiles)
    return [DefaultInfo(executable = executable, runfiles = runfiles)]

_ATTRS = {
    "data": attr.label_list(allow_files = True),
    "_generator": attr.label(
        default = Label("//mkosi/debian:generate_lock"),
        executable = True,
        cfg = "target",
    ),
}

_debian_lock_update = rule(
    implementation = _generator_impl,
    executable = True,
    attrs = _ATTRS,
    doc = "Runs the Debian lock generator with args.",
)

_debian_lock_test = rule(
    implementation = _generator_impl,
    test = True,
    attrs = _ATTRS,
    doc = "Tests with the Debian lock generator and args.",
)

def _workspace_path(label):
    if label.repo_name:
        fail("debian_lock specification and lock must be in the main repository: %s" % label)
    return label.package + "/" + label.name if label.package else label.name

def debian_lock(name, spec, lock, tags = [], visibility = None):
    """Declares `<name>.update`, which regenerates `lock` from `spec`, and `<name>_test`, which fails when it is stale.

    `bazel run :<name>.update` resolves `spec` with network access and rewrites `lock` in the source tree; further
    arguments such as `--release` reach the generator. `<name>_test` runs offline and fails unless `lock` records
    the SHA-256 of the normalized `spec`, so any change to the snapshot, components, or packages needs an update.

    Args:
      name: Prefix of the generated targets.
      spec: Debian package specification JSON in the main repository.
      lock: Lock JSON in the main repository; it need not exist before the first update.
      tags: Tags of both targets.
      visibility: Visibility of both targets.
    """
    spec_label = native.package_relative_label(spec)
    lock_label = native.package_relative_label(lock)
    update = name + ".update"
    _debian_lock_update(
        name = update,
        args = ["--spec", _workspace_path(spec_label), "--output", _workspace_path(lock_label)],
        tags = tags,
        visibility = visibility,
    )
    _debian_lock_test(
        name = name + "_test",
        size = "small",
        args = [
            "--check-spec",
            "--runfiles",
            "--spec",
            "$(rlocationpath %s)" % spec_label,
            "--output",
            "$(rlocationpath %s)" % lock_label,
            "--update-target",
            "//%s:%s" % (native.package_name(), update),
        ],
        data = [spec_label, lock_label],
        tags = tags,
        visibility = visibility,
    )
