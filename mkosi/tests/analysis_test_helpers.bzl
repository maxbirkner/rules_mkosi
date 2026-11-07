"""Helpers for analysis tests that inspect registered actions and their command lines."""

load("@bazel_skylib//lib:unittest.bzl", "analysistest", "asserts")

def single_action(env, mnemonic):
    """Returns the only action with mnemonic of the target under test, failing the test if there is not exactly one."""
    actions = [action for action in analysistest.target_actions(env) if action.mnemonic == mnemonic]
    asserts.equals(env, 1, len(actions), "expected one %s action" % mnemonic)
    return actions[0]

def option_value(argv, option):
    """Returns the argument after the first occurrence of option in argv, or None if option is absent."""
    if option not in argv:
        return None
    return argv[argv.index(option) + 1]

def argv_preamble(argv):
    """Returns the arguments before the first `--` separator in argv."""
    return argv[:argv.index("--")]

def _expected_failure_test_impl(ctx):
    """Passes when analysis of the target under test fails with expected_error in its message."""
    env = analysistest.begin(ctx)
    asserts.expect_failure(env, ctx.attr.expected_error)
    return analysistest.end(env)

expected_failure_test = analysistest.make(
    _expected_failure_test_impl,
    attrs = {"expected_error": attr.string(mandatory = True)},
    expect_failure = True,
)
