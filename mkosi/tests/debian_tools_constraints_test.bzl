"""Analysis tests of the platform constraints of the Debian tools' static bootstrap executables."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")

_PLATFORMS = "//command_line_option:platforms"
_BOOTSTRAP_PLATFORM = str(Label("//mkosi/toolchain:bootstrap_platform"))

_ExecutableConstraintsInfo = provider(
    doc = "Platform constraints of a bootstrap executable, or of the static binary that it exposes.",
    fields = {
        "binary": "_ExecutableConstraintsInfo of the static binary of a bootstrap executable, None for the binary.",
        "exec_constraints": "ConstraintValueInfo of each value of exec_compatible_with.",
        "label": "Label of the target.",
        "target_constraints": "ConstraintValueInfo of each value of target_compatible_with.",
        "target_platform_constraints": "ConstraintValueInfo of each checked value that the target platform has.",
    },
)

def _collect_constraint_values(targets):
    return [target[platform_common.ConstraintValueInfo] for target in targets]

def _collect_executable_constraints_impl(target, ctx):
    binary = getattr(ctx.rule.attr, "binary", None)
    checked = _collect_constraint_values(ctx.attr._checked_constraints)
    return [_ExecutableConstraintsInfo(
        binary = binary[0][_ExecutableConstraintsInfo] if binary else None,
        exec_constraints = _collect_constraint_values(ctx.rule.attr.exec_compatible_with),
        label = target.label,
        target_constraints = _collect_constraint_values(ctx.rule.attr.target_compatible_with),
        target_platform_constraints = [value for value in checked if ctx.target_platform_has_constraint(value)],
    )]

# Bazel resolves aliases of constraint values to their ConstraintValueInfo, and the configured target platform through
# its constraints, including those of its parents, so the tests compare constraint values rather than labels.
_collect_executable_constraints = aspect(
    implementation = _collect_executable_constraints_impl,
    attr_aspects = ["binary"],
    attrs = {
        "_checked_constraints": attr.label_list(default = [
            "@platforms//cpu:aarch64",
            "@platforms//cpu:x86_64",
            "@platforms//os:linux",
        ]),
    },
)

def _assert_executable_constraints(env, info, linux, cpu, cpu_name):
    """Asserts that info's target runs actions on Linux and is built for, and restricted to, Linux on cpu."""
    asserts.true(
        env,
        linux in info.exec_constraints,
        "{} must require a Linux execution platform".format(info.label),
    )
    for value, name in [(linux, "Linux"), (cpu, cpu_name)]:
        asserts.true(
            env,
            value in info.target_constraints,
            "{} must be compatible only with {} target platforms".format(info.label, name),
        )
        asserts.true(
            env,
            value in info.target_platform_constraints,
            "{} must be built for a {} target platform".format(info.label, name),
        )

def _executable_constraints_test_impl(ctx):
    env = analysistest.begin(ctx)
    info = analysistest.target_under_test(env)[_ExecutableConstraintsInfo]
    linux = ctx.attr._linux[platform_common.ConstraintValueInfo]
    cpu = ctx.attr._cpu[platform_common.ConstraintValueInfo]
    cpu_name = ctx.attr._cpu.label.name
    _assert_executable_constraints(env, info, linux, cpu, cpu_name)
    asserts.true(env, info.binary != None, "{} must expose a static binary".format(info.label))
    if info.binary:
        _assert_executable_constraints(env, info.binary, linux, cpu, cpu_name)
    return analysistest.end(env)

def _make_executable_constraints_test(cpu):
    """Returns an analysis test of a bootstrap executable for Linux on cpu, configured for that platform."""
    platform = str(Label("//mkosi/toolchain/bootstrap_cc:linux_{}_musl".format(cpu)))
    return analysistest.make(
        _executable_constraints_test_impl,
        attrs = {
            "_cpu": attr.label(default = "@platforms//cpu:" + cpu),
            "_linux": attr.label(default = "@platforms//os:linux"),
        },
        config_settings = {
            _BOOTSTRAP_PLATFORM: platform,
            _PLATFORMS: [platform],
        },
        extra_target_under_test_aspects = [_collect_executable_constraints],
    )

_aarch64_executable_constraints_test = _make_executable_constraints_test("aarch64")
_x86_64_executable_constraints_test = _make_executable_constraints_test("x86_64")

_EXECUTABLE_CONSTRAINTS_TESTS = {
    "aarch64": _aarch64_executable_constraints_test,
    "x86_64": _x86_64_executable_constraints_test,
}

def debian_tools_constraints_test_suite(name, packages):
    """Checks the constraints of the launcher and the namespace runner of each Debian tools package.

    Each executable and its static binary must require a Linux execution platform, and be restricted to and built for
    Linux on the package's CPU.

    Args:
      name: Name of the test suite.
      packages: Dictionary from a Debian tools package, such as `@mkosi_debian_tools//`, to the CPU of its
        executables, `x86_64` or `aarch64`.
    """
    tests = []
    for package, cpu in packages.items():
        for executable in ["launcher", "namespace_runner"]:
            test = "{}_{}_{}_test".format(name, cpu, executable)
            _EXECUTABLE_CONSTRAINTS_TESTS[cpu](
                name = test,
                target_under_test = "{}:{}".format(package, executable),
            )
            tests.append(":" + test)
    native.test_suite(
        name = name,
        tests = tests,
    )
