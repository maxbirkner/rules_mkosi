"""Analysis tests for isolating rules_mkosi's Python line and bootstrap platform from consumer defaults."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")
load("//mkosi:defs.bzl", "managed_python_test")
load("//mkosi/private:bootstrap_binary.bzl", "bootstrap_binary")

_BOOTSTRAP_PLATFORM = str(Label("//mkosi/toolchain:bootstrap_platform"))
_PYTHON_BOOTSTRAP = str(Label("@rules_python//python/config_settings:bootstrap_impl"))
_PYTHON_VERSION = str(Label("@rules_python//python/config_settings:python_version"))

# A Python line that rules_python knows but rules_mkosi does not register, standing in for a consumer's default.
_CONSUMER_PYTHON_VERSION = "3.13"

def _runfile_paths(target):
    return [file.short_path for file in target[DefaultInfo].default_runfiles.files.to_list()]

def _mkosi_toolchain_python_test_impl(ctx):
    env = analysistest.begin(ctx)
    info = analysistest.target_under_test(env)[platform_common.ToolchainInfo].mkosi
    asserts.equals(env, "3.14", info.python_version)
    asserts.true(
        env,
        info.resolved_python_version.startswith("3.14."),
        "mkosi Python resolved {} instead of 3.14".format(info.resolved_python_version),
    )
    asserts.equals(env, "pefile.py", info.pefile.basename)
    return analysistest.end(env)

_mkosi_toolchain_python_test = analysistest.make(
    _mkosi_toolchain_python_test_impl,
    config_settings = {_PYTHON_VERSION: _CONSUMER_PYTHON_VERSION},
)

def _debian_launcher_python_test_impl(ctx):
    env = analysistest.begin(ctx)
    paths = _runfile_paths(analysistest.target_under_test(env))
    asserts.true(
        env,
        any(["mkosi_pypi_314_click" in path and path.endswith("/click/core.py") for path in paths]),
        "Debian launcher runfiles lack the locked Python 3.14 Click wheel",
    )
    return analysistest.end(env)

_debian_launcher_python_test = analysistest.make(
    _debian_launcher_python_test_impl,
    config_settings = {_PYTHON_VERSION: _CONSUMER_PYTHON_VERSION},
)

def _managed_python_line_test_impl(ctx):
    env = analysistest.begin(ctx)
    paths = _runfile_paths(analysistest.target_under_test(env))
    asserts.true(
        env,
        any([path.endswith("/lib/python3.14/os.py") for path in paths]),
        "managed_python_test lacks the Python 3.14 runtime",
    )
    asserts.false(
        env,
        any(["/lib/python{}/".format(_CONSUMER_PYTHON_VERSION) in path for path in paths]),
        "managed_python_test used the consumer's default Python line",
    )
    return analysistest.end(env)

_managed_python_line_test = analysistest.make(
    _managed_python_line_test_impl,
    config_settings = {_PYTHON_VERSION: _CONSUMER_PYTHON_VERSION},
)

def _bootstrap_probe_impl(ctx):
    executable = ctx.actions.declare_file(ctx.label.name)
    ctx.actions.write(executable, "", is_executable = True)
    marker = ctx.actions.declare_file("{}.{}.{}".format(
        ctx.label.name,
        ctx.attr.platform_marker,
        ctx.attr.python_bootstrap_marker,
    ))
    ctx.actions.write(marker, "")
    return [DefaultInfo(executable = executable, runfiles = ctx.runfiles(files = [marker]))]

_bootstrap_probe = rule(
    implementation = _bootstrap_probe_impl,
    executable = True,
    attrs = {
        "platform_marker": attr.string(mandatory = True),
        "python_bootstrap_marker": attr.string(mandatory = True),
    },
    doc = "Records the configured target platform and Python bootstrap in a runfile name.",
)

def _bootstrap_marker_test_impl(ctx):
    env = analysistest.begin(ctx)
    target = analysistest.target_under_test(env)
    expected = "bootstrap_probe.{}.system_python".format(ctx.attr.expected_platform)
    names = [path.rsplit("/", 1)[-1] for path in _runfile_paths(target)]
    asserts.true(env, expected in names, "expected runfile {} in {}".format(expected, names))
    asserts.equals(env, ctx.label.package, target[DefaultInfo].files_to_run.executable.owner.package)
    return analysistest.end(env)

_BOOTSTRAP_MARKER_ATTRS = {"expected_platform": attr.string(mandatory = True)}

_bootstrap_inherited_platform_test = analysistest.make(
    _bootstrap_marker_test_impl,
    attrs = _BOOTSTRAP_MARKER_ATTRS,
    config_settings = {_PYTHON_BOOTSTRAP: "script"},
)

_bootstrap_selected_platform_test = analysistest.make(
    _bootstrap_marker_test_impl,
    attrs = _BOOTSTRAP_MARKER_ATTRS,
    config_settings = {
        _BOOTSTRAP_PLATFORM: str(Label(":bootstrap_probe_platform")),
        _PYTHON_BOOTSTRAP: "script",
    },
)

def consumer_isolation_test_suite(name):
    """Defines analysis tests for consumer-independent Python and bootstrap configuration.

    Args:
      name: Name of the generated test suite.
    """
    _mkosi_toolchain_python_test(
        name = "mkosi_toolchain_python_line_test",
        target_under_test = "@mkosi_toolchains//:mkosi_toolchain",
    )
    _debian_launcher_python_test(
        name = "debian_launcher_python_line_test",
        target_under_test = "@mkosi_debian_tools//:launcher",
    )
    managed_python_test(
        name = "managed_python_line_subject",
        src = "testdata/managed_python_line.py",
        data = ["testdata/managed_python_line.py"],
        tags = ["manual"],
    )
    _managed_python_line_test(
        name = "managed_python_line_test",
        target_under_test = ":managed_python_line_subject",
    )

    native.constraint_setting(name = "bootstrap_probe_setting")
    native.constraint_value(
        name = "bootstrap_probe_selected",
        constraint_setting = ":bootstrap_probe_setting",
    )
    native.platform(
        name = "bootstrap_probe_platform",
        constraint_values = [
            ":bootstrap_probe_selected",
            "@platforms//cpu:x86_64",
            "@platforms//os:linux",
        ],
    )
    native.config_setting(
        name = "bootstrap_probe_platform_selected",
        constraint_values = [":bootstrap_probe_selected"],
    )
    native.config_setting(
        name = "bootstrap_probe_system_python",
        flag_values = {_PYTHON_BOOTSTRAP: "system_python"},
    )
    _bootstrap_probe(
        name = "bootstrap_probe",
        platform_marker = select({
            ":bootstrap_probe_platform_selected": "selected",
            "//conditions:default": "inherited",
        }),
        python_bootstrap_marker = select({
            ":bootstrap_probe_system_python": "system_python",
            "//conditions:default": "other",
        }),
        tags = ["manual"],
    )
    bootstrap_binary(
        name = "bootstrap_probe_subject",
        binary = ":bootstrap_probe",
        tags = ["manual"],
    )
    _bootstrap_inherited_platform_test(
        name = "bootstrap_inherited_platform_test",
        expected_platform = "inherited",
        target_under_test = ":bootstrap_probe_subject",
    )
    _bootstrap_selected_platform_test(
        name = "bootstrap_selected_platform_test",
        expected_platform = "selected",
        target_under_test = ":bootstrap_probe_subject",
    )

    native.test_suite(
        name = name,
        tests = [
            ":bootstrap_inherited_platform_test",
            ":bootstrap_selected_platform_test",
            ":debian_launcher_python_line_test",
            ":managed_python_line_test",
            ":mkosi_toolchain_python_line_test",
        ],
    )
