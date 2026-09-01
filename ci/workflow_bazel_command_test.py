"""Checks workflow shell sources for unscoped Bazel build/test commands."""

import pathlib
import re
import shlex
import sys

import yaml


_LAUNCHER = re.compile(
    r"(?<![\w$])(?:run_bazel|\b(?:bazel|bazelisk)\b|"
    r"\$(?:\{(?:BAZEL|bazel|BAZELISK|bazelisk|"
    r"[A-Za-z_][A-Za-z0-9_]*bazel[A-Za-z0-9_]*)(?::-[^}]*)?\}|"
    r"(?:BAZEL|bazel|BAZELISK|bazelisk|"
    r"[A-Za-z_][A-Za-z0-9_]*bazel[A-Za-z0-9_]*))|"
    r"/(?:[\w.-]+/)*bazel(?:isk)?)(?![\w.-])"
)
_VARIABLE = re.compile(
    r"\$(?:\{[A-Za-z_][A-Za-z0-9_]*(?::-[^}]*)?\}|"
    r"[A-Za-z_][A-Za-z0-9_]*)"
)
_SHELL_SEPARATOR = re.compile(r"(?:&&|\|\||[;&|\n])")
_SHELL_LINE_CONTINUATION = re.compile(r"\\(?:\r\n|\n)")
_GITHUB_EXPRESSION = re.compile(r"\$\{\{.*?\}\}", re.DOTALL)
_GITHUB_LAUNCHER_BASE = "GITHUB_EXPRESSION_LAUNCHER"
_SHELL_WRAPPERS = {"bash", "command", "env", "exec", "run_bazel", "sh", "sudo"}
_SHELL_CONTROL_PREFIXES = {
    "!",
    "(",
    "{",
    "do",
    "elif",
    "else",
    "if",
    "then",
    "time",
    "until",
    "while",
}


def _token_is_command_position(tokens, index):
    """Recognize executable positions after shell controls and wrappers."""
    if index == 0:
        return True
    prefix = tokens[:index]
    return all(
        value in _SHELL_WRAPPERS
        or value in _SHELL_CONTROL_PREFIXES
        or value.startswith("-")
        or "=" in value
        for value in prefix
    )


def _yaml_shell_bodies(text):
    """Extract workflow step shell sources through structural YAML parsing."""
    workflow = yaml.safe_load(text)
    if not isinstance(workflow, dict):
        return []
    jobs = workflow.get("jobs", {})
    if not isinstance(jobs, dict):
        return []
    bodies = []
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps", [])
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict):
                continue
            run = step.get("run")
            if isinstance(run, str):
                bodies.append(run)
    return bodies


def _normalize_shell_continuations(text):
    """Apply the shell's physical backslash-newline removal."""
    return _SHELL_LINE_CONTINUATION.sub("", text)


def _expression_marker(text):
    """Choose a deterministic expression marker absent from source text."""
    marker = _GITHUB_LAUNCHER_BASE
    suffix = 0
    while marker in text:
        suffix += 1
        marker = f"{_GITHUB_LAUNCHER_BASE}_{suffix}"
    return marker


def _shell_command_segments(text, expression_marker):
    """Yield normalized command segments with expression provenance."""
    text = _normalize_shell_continuations(text)
    text = _GITHUB_EXPRESSION.sub(expression_marker, text)
    start = 0
    for match in _SHELL_SEPARATOR.finditer(text):
        yield text[start : match.start()]
        start = match.end()
    yield text[start:]


def _is_launcher_token(tokens, index, expression_marker):
    token = tokens[index]
    return bool(
        _LAUNCHER.fullmatch(token)
        or (
            expression_marker in token
            and _token_is_command_position(tokens, index)
        )
    )


def _launcher_command(tokens, launcher_index, expression_marker):
    launcher = tokens[launcher_index]
    index = launcher_index + 1
    if launcher == "run_bazel" and index < len(tokens):
        if (
            _is_launcher_token(tokens, index, expression_marker)
            or tokens[index].endswith("/tools/bazel")
            or (
                tokens[index].startswith("$")
                and "bazel" in tokens[index].lower()
            )
        ) and tokens[index] != "run_bazel":
            index += 1
            wrapped_command = True
        else:
            wrapped_command = False
    else:
        wrapped_command = False
    while index < len(tokens) and tokens[index] not in ("test", "build"):
        index += 1
    if index == len(tokens):
        if wrapped_command:
            return -1
        return None
    return index


def _validate_shell_body(source_name, body, expression_marker=None):
    violations = []
    if expression_marker is None:
        expression_marker = _expression_marker(body)
    for segment in _shell_command_segments(body, expression_marker):
        if (
            expression_marker not in segment
            and not _LAUNCHER.search(segment)
            and not _VARIABLE.search(segment)
        ):
            continue
        try:
            tokens = shlex.split(segment)
        except ValueError as error:
            if expression_marker in segment or (
                _LAUNCHER.search(segment)
                and re.search(r"\b(?:test|build)\b", segment)
            ):
                violations.append(
                    f"{source_name}: cannot parse potential "
                    f"Bazel command: {error}"
                )
            continue
        for index, token in enumerate(tokens):
            if (
                any(character.isspace() for character in token)
                and (
                    expression_marker in token
                    or _LAUNCHER.search(token)
                )
                and _token_is_command_position(tokens, index)
                and token != expression_marker
                and not _LAUNCHER.fullmatch(token)
            ):
                # Shell wrappers such as `sh -c "bazel test ..."`
                # leave the nested command as one shlex token.
                violations.extend(
                    _validate_shell_body(
                        source_name,
                        token,
                        expression_marker,
                    )
                )
        for index, token in enumerate(tokens):
            if _is_launcher_token(tokens, index, expression_marker):
                pass
            elif _VARIABLE.fullmatch(token) and _token_is_command_position(
                tokens, index
            ):
                pass
            else:
                continue
            command_index = _launcher_command(
                tokens,
                index,
                expression_marker,
            )
            if command_index == -1:
                continue
            if command_index is None:
                if any(
                    value in ("test", "build")
                    or (
                        value.startswith(("$", "${"))
                        and value != "$@"
                        and not value.startswith("${args[@]")
                    )
                    for value in tokens[index + 1 :]
                ):
                    violations.append(
                        f"{source_name}: ambiguous build/test command"
                    )
                continue
            target_tokens = [
                value
                for value in tokens[command_index + 1 :]
                if value.startswith(("//", "@"))
            ]
            if target_tokens != ["//..."]:
                violations.append(
                    f"{source_name}: expected only //..., "
                    f"got {target_tokens!r}"
                )
    return violations


def validate_shell_sources(sources):
    """Return human-readable violations from workflow/helper shell sources."""
    violations = []
    for source_name, text, workflow in sources:
        bodies = _yaml_shell_bodies(text) if workflow else [text]
        for body in bodies:
            violations.extend(_validate_shell_body(source_name, body))
    return violations


def main():
    workflow = sys.argv[1]
    workflow_text = open(workflow, encoding="utf-8").read()
    sources = [(workflow, workflow_text, True)]
    for helper in sys.argv[2:]:
        sources.append((helper, open(helper, encoding="utf-8").read(), False))
    # Workflow helpers are part of the policy surface even when they are
    # invoked indirectly from a shell step. Keep this discovery narrow and
    # deterministic rather than scanning the whole repository.
    workflow_path = pathlib.Path(workflow)
    for helper in re.findall(
        r"(?<![\w./-])([\w./-]+(?:\.sh|/bazel))\b", workflow_text
    ):
        if helper.endswith("/tools/bazel"):
            helper = "tools/bazel"
        helper_path = workflow_path.parent.parent.parent / helper
        if helper_path.is_file() and str(helper_path) not in {
            item[0] for item in sources
        }:
            sources.append(
                (str(helper_path), helper_path.read_text(encoding="utf-8"), False)
            )
    failures = validate_shell_sources(sources)
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("all workflow/helper bazel test/build commands use //...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
