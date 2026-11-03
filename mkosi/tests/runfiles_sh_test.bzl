"""Shell test macro that resolves runfiles in both runfiles-directory and manifest mode."""

load("@rules_shell//shell:sh_test.bzl", "sh_test")

def runfiles_sh_test(name, src, args = [], data = [], **kwargs):
    """Runs the shell script src with an `rlocation` function for its arguments.

    The script is sourced with `set -eu` already active, receives args as positional parameters, and resolves each
    runfile passed as `$(rlocationpath ...)` with `rlocation`.

    Args:
      name: Test name.
      src: Shell script to source.
      args: Arguments passed to src.
      data: Files available to the test at run time.
      **kwargs: Further sh_test attributes.
    """
    sh_test(
        name = name,
        srcs = [Label(":run_with_runfiles.sh")],
        args = ["$(rlocationpath %s)" % src] + args,
        data = [src] + data,
        **kwargs
    )
