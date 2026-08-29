"""Debian build-time userspace toolchain."""

DebianToolsInfo = provider(
    doc = "Pinned Debian userspace tools and provenance.",
    fields = {
        "format_version": "Toolchain contract version.",
        "distribution": "Distribution name.",
        "release": "Numeric Debian release.",
        "codename": "Debian codename.",
        "architecture": "Debian package architecture.",
        "snapshot": "Pinned snapshot identifier.",
        "snapshot_url": "Pinned snapshot URL.",
        "lock_sha256": "SHA-256 digest of the checked-in package lockfile.",
        "archive_sha256": "SHA-256 digest of the flattened package archive.",
        "tree": "Flattened tar archive containing the installed package tree.",
        "tree_root": "Extracted Debian tools TreeArtifact.",
        "launcher": "Root-isolated executable launcher.",
        "launcher_files_to_run": "FilesToRunProvider for the root launcher.",
        "python": "Bazel-managed standalone Python interpreter.",
        "python_files_to_run": "FilesToRunProvider for the standalone interpreter.",
        "launcher_script": "Python launcher script passed to the interpreter.",
        "extractor": "Shared strict extraction implementation.",
        "tree_files_to_run": "FilesToRunProvider preserving tree mappings.",
        "tree_runfiles": "Runfiles for the package tree.",
        "provenance": "Checked-in package provenance metadata.",
        "components": "Checked-in required component manifest.",
        "required_components": "Initial tracer-required component names.",
    },
)

def _tree_impl(ctx):
    root = ctx.actions.declare_directory(ctx.label.name + "_root")
    ctx.actions.run(
        executable = ctx.executable._python,
        arguments = [ctx.file.extractor.path, ctx.file.archive.path, root.path],
        inputs = [ctx.file.extractor, ctx.file.archive],
        tools = [ctx.executable._python],
        outputs = [root],
        mnemonic = "ExtractDebianTools",
        progress_message = "Extracting Debian tools tree %{label}",
    )
    return [DefaultInfo(files = depset([root]))]

debian_tools_tree = rule(
    implementation = _tree_impl,
    attrs = {
        "archive": attr.label(mandatory = True, allow_single_file = True),
        "extractor": attr.label(mandatory = True, allow_single_file = True),
        "_python": attr.label(
            allow_files = True,
            executable = True,
            cfg = "exec",
            default = "@python_3_11//:python3",
        ),
    },
    doc = "Extracts a Debian archive with the Bazel-managed Python runtime.",
)

def _launcher_impl(ctx):
    output = ctx.actions.declare_file(ctx.label.name)
    root = ctx.attr.root[DefaultInfo].files.to_list()[0]
    ctx.actions.write(
        output = output,
        is_executable = True,
        content = """#!/bin/sh
set -eu
PATH=
export PATH
runfiles_root="${{RUNFILES_DIR:-$0.runfiles}}"
root="{root}"
case "$root" in
    ../*) root="${{root#../}}" ;;
    external/*) root="${{root#external/}}" ;;
esac
if [ -d "$runfiles_root/$root" ]; then root="$runfiles_root/$root"
elif [ -d "$runfiles_root/_main/$root" ]; then root="$runfiles_root/_main/$root"
elif [ -d "$runfiles_root/rules_mkosi/$root" ]; then root="$runfiles_root/rules_mkosi/$root"
else
    echo "Debian tools root is missing from runfiles: $root" >&2
    exit 1
fi
root="$(cd "$root" && pwd -P)"
bwrap="$root/usr/bin/bwrap"
libs="$root/usr/lib/x86_64-linux-gnu:$root/lib/x86_64-linux-gnu:$root/usr/lib/x86_64-linux-gnu/systemd:$root/usr/lib/systemd:$root/usr/lib64"
loader=
for candidate in \
    "$root/lib64/ld-linux-x86-64.so.2" \
    "$root/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2" \
    "$root/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2"
do
    if [ -x "$candidate" ]; then loader="$candidate"; break; fi
done
[ -n "$loader" ] || {{ echo "Debian bootstrap loader is missing from extracted root" >&2; exit 1; }}
[ -x "$bwrap" ] || {{ echo "Debian root-isolation launcher is missing: $bwrap" >&2; exit 1; }}
[ "$#" -gt 0 ] || {{ echo "usage: $0 /usr/bin/tool [args...]" >&2; exit 2; }}
case "$1" in
    /*) ;;
    *) echo "in-root tool path must be absolute: $1" >&2; exit 2 ;;
esac
[ -x "$root$1" ] || {{ echo "in-root executable is missing: $1" >&2; exit 1; }}
"$loader" --library-path "$libs" "$bwrap" \
    --die-with-parent --unshare-user-try --unshare-pid --unshare-ipc --unshare-uts --new-session \
    --ro-bind "$root" / \
    --setenv PATH /usr/bin:/usr/sbin \
    --setenv HOME /root \
    -- "$@"
status=$?
if [ "$status" -ne 0 ]; then
    echo "root-isolation or in-root ELF execution failed for $1 (status=$status)" >&2
    echo "bwrap argv: loader=$loader root=$root tool=$1 libraries=$libs" >&2
fi
exit "$status"
""".format(root = root.short_path),
    )
    return [
        DefaultInfo(
            executable = output,
            runfiles = ctx.runfiles(files = [output], transitive_files = depset([root])),
        ),
    ]

debian_tools_launcher = rule(
    implementation = _launcher_impl,
    executable = True,
    attrs = {
        "root": attr.label(mandatory = True),
    },
    doc = "Runs a Debian tool inside its packaged root and loader.",
)

def _preflight_impl(ctx):
    output = ctx.actions.declare_file(ctx.label.name + ".sh")
    required = " ".join(ctx.attr.required_components)
    components = ctx.file.components.short_path
    tree = ctx.attr.tree[DefaultInfo].files.to_list()[0].short_path
    launcher = ctx.attr.launcher[DefaultInfo].files_to_run.executable.short_path
    provenance = ctx.file.provenance.short_path
    ctx.actions.write(
        output = output,
        is_executable = True,
        content = """#!/bin/sh
set -eu
PATH=
export PATH
runfiles_root="${{RUNFILES_DIR:-$0.runfiles}}"
runfile() {{
    path="$1"
    path="${{path#../}}"
    path="${{path#external/}}"
    if [ -e "$runfiles_root/$path" ]; then printf '%s/%s' "$runfiles_root" "$path"
    elif [ -e "$runfiles_root/_main/$path" ]; then printf '%s/_main/%s' "$runfiles_root" "$path"
    else printf '%s/%s' "$runfiles_root" "$path"; fi
}}
tree="$(runfile {tree})"
launcher="$(runfile {launcher})"
provenance="$(runfile {provenance})"
components="$(runfile {components})"
[ -d "$tree" ] || {{ echo "Debian tools extracted root is missing: $tree" >&2; exit 1; }}
[ -x "$launcher" ] || {{ echo "Debian root-isolated launcher is missing: $launcher" >&2; exit 1; }}
[ -s "$provenance" ] || {{ echo "Debian tools provenance is missing: $provenance" >&2; exit 1; }}
[ -s "$components" ] || {{ echo "Debian tools component manifest is missing: $components" >&2; exit 1; }}
for component in {required}
do
    found=0
    while IFS='|' read -r declared_name declared_path declared_package
    do
        if [ "$declared_name" = "$component" ]; then
            if [ ! -x "$tree$declared_path" ]; then
                echo "Debian tools executable is missing or not executable: $declared_name ($declared_path)" >&2
                exit 1
            fi
            found=1
            break
        fi
    done < "$components"
    if [ "$found" -ne 1 ]; then
        echo "Debian tools component is missing from the pinned tree: $component" >&2
        exit 1
    fi
    echo "validated Debian tools component: $component"
done
""".format(
            tree = repr(tree),
            launcher = repr(launcher),
            provenance = repr(provenance),
            components = repr(components),
            required = required,
        ),
    )
    return [
        DefaultInfo(
            executable = output,
            runfiles = ctx.runfiles(files = [output, ctx.file.provenance, ctx.file.components], transitive_files = depset([
                ctx.attr.tree[DefaultInfo].files.to_list()[0],
                ctx.attr.launcher[DefaultInfo].files_to_run.executable,
            ])),
        ),
    ]

_PREFLIGHT_ATTRS = {
    "tree": attr.label(mandatory = True),
    "launcher": attr.label(mandatory = True, allow_files = True, executable = True, cfg = "exec"),
    "provenance": attr.label(mandatory = True, allow_single_file = True),
    "components": attr.label(mandatory = True, allow_single_file = True),
    "required_components": attr.string_list(mandatory = True),
}

debian_tools_preflight = rule(
    implementation = _preflight_impl,
    executable = True,
    attrs = _PREFLIGHT_ATTRS,
    doc = "Checks the pinned tree and every required tracer component.",
)

debian_tools_preflight_test = rule(
    implementation = _preflight_impl,
    test = True,
    attrs = _PREFLIGHT_ATTRS,
    doc = "Checks the pinned tree and every required tracer component.",
)

def _debian_tools_toolchain_impl(ctx):
    tree_info = ctx.attr.tree[DefaultInfo]
    tree_file = ctx.file.tree
    tree_root = ctx.attr.tree_root[DefaultInfo].files.to_list()[0]
    launcher = ctx.attr.python[DefaultInfo]
    info = DebianToolsInfo(
        format_version = ctx.attr.format_version,
        distribution = ctx.attr.distribution,
        release = ctx.attr.release,
        codename = ctx.attr.codename,
        architecture = ctx.attr.architecture,
        snapshot = ctx.attr.snapshot,
        snapshot_url = ctx.attr.snapshot_url,
        lock_sha256 = ctx.attr.lock_sha256,
        archive_sha256 = ctx.attr.archive_sha256,
        tree = tree_file,
        tree_root = tree_root,
        launcher = launcher.files_to_run.executable,
        launcher_files_to_run = launcher.files_to_run,
        python = ctx.attr.python[DefaultInfo].files_to_run.executable,
        python_files_to_run = ctx.attr.python[DefaultInfo].files_to_run,
        launcher_script = ctx.file.launcher_script,
        extractor = ctx.file.extractor,
        tree_files_to_run = tree_info.files_to_run,
        tree_runfiles = tree_info.default_runfiles,
        provenance = ctx.file.provenance,
        components = ctx.file.components,
        required_components = ctx.attr.required_components,
    )
    return [platform_common.ToolchainInfo(debian_tools = info), info]

debian_tools_toolchain = rule(
    implementation = _debian_tools_toolchain_impl,
    attrs = {
        "format_version": attr.string(default = "debian-tools-v1"),
        "distribution": attr.string(default = "debian"),
        "release": attr.string(mandatory = True),
        "codename": attr.string(mandatory = True),
        "architecture": attr.string(mandatory = True),
        "snapshot": attr.string(mandatory = True),
        "snapshot_url": attr.string(mandatory = True),
        "lock_sha256": attr.string(mandatory = True),
        "archive_sha256": attr.string(mandatory = True),
        "tree": attr.label(mandatory = True, allow_single_file = True),
        "tree_root": attr.label(mandatory = True),
        "python": attr.label(mandatory = True, allow_files = True, executable = True, cfg = "exec"),
        "launcher_script": attr.label(mandatory = True, allow_single_file = True),
        "extractor": attr.label(mandatory = True, allow_single_file = True),
        "provenance": attr.label(mandatory = True, allow_single_file = True),
        "components": attr.label(mandatory = True, allow_single_file = True),
        "required_components": attr.string_list(mandatory = True),
    },
    doc = "Defines the pinned Debian userspace toolchain.",
)
