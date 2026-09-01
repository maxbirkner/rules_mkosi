"""Validation helpers for hermetic actions in CI aquery graphs."""

import pathlib


_FIXED_ZIG_PATH = "/bin:/usr/bin:/usr/local/bin"
_HOST_TOOL_BASENAMES = {
    "ar",
    "bash",
    "cc",
    "clang",
    "gcc",
    "ld",
    "sh",
    "strip",
}
_HERMETIC_PATH_ACTIONS = {
    "CppArchive",
    "CppCompile",
    "CppLink",
    "PythonZipper",
}


def validate_action_environment(action, input_paths):
    """Reject host-resolved executables exposed through action environments."""
    mnemonic = action["mnemonic"]
    arguments = action.get("arguments", [])
    for variable in action.get("environmentVariables", []):
        key = variable.get("key", "")
        value = variable.get("value", "")
        if not value or value == "/proc/self/cwd":
            continue
        if key == "PATH" and value == _FIXED_ZIG_PATH:
            if mnemonic == "CcStrip" and arguments[:1] == ["/usr/bin/false"]:
                continue
            if mnemonic not in _HERMETIC_PATH_ACTIONS or not arguments:
                raise ValueError(
                    f"nonempty PATH on unsupported action: {mnemonic}"
                )
            executable = arguments[0]
            basename = pathlib.PurePosixPath(executable).name
            if "/" not in executable and basename in _HOST_TOOL_BASENAMES:
                raise ValueError(
                    f"host-tool basename exposed through PATH: {basename}"
                )
            if executable not in input_paths:
                raise ValueError(
                    f"PATH executable is not a declared input: {executable}"
                )
            continue
        if value.startswith("/"):
            raise ValueError(
                f"host environment path: {mnemonic} {key}={value}"
            )
