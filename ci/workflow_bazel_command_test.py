"""Checks workflow shell sources for unscoped Bazel build/test commands."""

import pathlib
import re
import shlex
import sys


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
_RUN_BLOCK = re.compile(
    r"^(\s*)run:\s*([|>])([+-]?[1-9]?|[1-9]?[+-]?)\s*$"
)
_RUN_INLINE = re.compile(r"^\s*run:\s*(?![|>])(.+)$")
_SHELL_WRAPPERS = {"bash", "command", "env", "exec", "run_bazel", "sh", "sudo"}


def _variable_is_command(tokens, index):
    """Recognize a variable in command position without flagging arguments."""
    if index == 0:
        return True
    prefix = tokens[:index]
    return all(
        value in _SHELL_WRAPPERS
        or value.startswith("-")
        or "=" in value
        for value in prefix
    )


def _yaml_shell_bodies(text):
    """Extract literal and folded `run:` block scalars without a YAML parser."""
    lines = text.splitlines()
    bodies = []
    index = 0
    while index < len(lines):
        match = _RUN_BLOCK.match(lines[index])
        if not match:
            inline = _RUN_INLINE.match(lines[index])
            if inline:
                bodies.append(inline.group(1))
            index += 1
            continue
        base_indent = len(match.group(1))
        style = match.group(2)
        indicator = match.group(3)
        explicit_indent = int("".join(c for c in indicator if c.isdigit()) or 0)
        index += 1
        content = []
        content_indent = None
        while index < len(lines):
            line = lines[index]
            if line.strip():
                indent = len(line) - len(line.lstrip())
                if indent <= base_indent:
                    break
                if content_indent is None:
                    content_indent = (
                        base_indent + explicit_indent
                        if explicit_indent
                        else indent
                    )
            elif content_indent is None:
                content.append("")
                index += 1
                continue
            if content_indent is not None:
                content.append(line[content_indent:])
            index += 1
        if style == "|":
            bodies.append("\n".join(content))
        else:
            folded = []
            for line in content:
                if not line:
                    folded.append("\n")
                elif folded and not folded[-1].endswith("\n"):
                    folded.append(" " + line)
                else:
                    folded.append(line)
            bodies.append("".join(folded))
    return bodies


def _command_segments(text):
    text = re.sub(
        r"\$\{\{.*?\}\}",
        "$GITHUB_EXPRESSION",
        text,
        flags=re.DOTALL,
    )
    text = text.replace("\\\n", " ")
    start = 0
    for match in _SHELL_SEPARATOR.finditer(text):
        yield text[start : match.start()]
        start = match.end()
    yield text[start:]


def _launcher_command(tokens, launcher_index):
    launcher = tokens[launcher_index]
    index = launcher_index + 1
    if launcher == "run_bazel" and index < len(tokens):
        if (
            _LAUNCHER.fullmatch(tokens[index])
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


def validate_shell_sources(sources):
    """Return human-readable violations from workflow/helper shell sources."""
    violations = []
    for source_name, text, workflow in sources:
        bodies = _yaml_shell_bodies(text) if workflow else [text]
        for body in bodies:
            for segment in _command_segments(body):
                if not _LAUNCHER.search(segment) and not _VARIABLE.search(segment):
                    continue
                try:
                    tokens = shlex.split(segment)
                except ValueError as error:
                    if _LAUNCHER.search(segment) and re.search(
                        r"\b(?:test|build)\b", segment
                    ):
                        violations.append(
                            f"{source_name}: cannot parse build/test command: {error}"
                        )
                    continue
                for token in tokens:
                    if (
                        any(character.isspace() for character in token)
                        and _LAUNCHER.search(token)
                        and re.search(r"\b(?:test|build)\b", token)
                        and not _LAUNCHER.fullmatch(token)
                    ):
                        # Shell wrappers such as `sh -c "bazel test ..."`
                        # leave the nested command as one shlex token.
                        violations.extend(
                            validate_shell_sources(
                                [(source_name, token, False)]
                            )
                        )
                for index, token in enumerate(tokens):
                    if _LAUNCHER.fullmatch(token):
                        pass
                    elif token.startswith(
                        "$GITHUB_EXPRESSION"
                    ) and _variable_is_command(tokens, index):
                        pass
                    elif _VARIABLE.fullmatch(token) and _variable_is_command(
                        tokens, index
                    ):
                        pass
                    else:
                        continue
                    command_index = _launcher_command(tokens, index)
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
