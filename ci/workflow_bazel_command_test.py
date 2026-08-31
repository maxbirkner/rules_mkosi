"""Checks workflow shell sources for unscoped Bazel build/test commands."""

import re
import shlex
import sys


_LAUNCHER = re.compile(
    r"(?<![\w$])(?:run_bazel|\b(?:bazel|bazelisk)\b|"
    r"\$\{?(?:BAZEL|bazel|BAZELISK|bazelisk)\}?|"
    r"/(?:[\w.-]+/)*bazel(?:isk)?)(?![\w.-])"
)
_SHELL_SEPARATOR = re.compile(r"(?:&&|\|\||[;&|\n])")
_RUN_BLOCK = re.compile(r"^(\s*)run:\s*([|>])([+-]?)\s*$")


def _yaml_shell_bodies(text):
    """Extract literal and folded `run:` block scalars without a YAML parser."""
    lines = text.splitlines()
    bodies = []
    index = 0
    while index < len(lines):
        match = _RUN_BLOCK.match(lines[index])
        if not match:
            index += 1
            continue
        base_indent = len(match.group(1))
        style = match.group(2)
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
                    content_indent = indent
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
        if _LAUNCHER.fullmatch(tokens[index]) and tokens[index] != "run_bazel":
            index += 1
    while index < len(tokens) and tokens[index] not in ("test", "build"):
        index += 1
    if index == len(tokens):
        return None
    return index


def validate_shell_sources(sources):
    """Return human-readable violations from workflow/helper shell sources."""
    violations = []
    for source_name, text, workflow in sources:
        bodies = _yaml_shell_bodies(text) if workflow else [text]
        for body in bodies:
            for segment in _command_segments(body):
                if not _LAUNCHER.search(segment):
                    continue
                try:
                    tokens = shlex.split(segment)
                except ValueError as error:
                    if re.search(r"\b(?:test|build)\b", segment):
                        violations.append(
                            f"{source_name}: cannot parse build/test command: {error}"
                        )
                    continue
                for index, token in enumerate(tokens):
                    if not _LAUNCHER.fullmatch(token):
                        continue
                    command_index = _launcher_command(tokens, index)
                    if command_index is None:
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
    sources = [
        (workflow, open(workflow, encoding="utf-8").read(), True),
    ]
    for helper in sys.argv[2:]:
        sources.append((helper, open(helper, encoding="utf-8").read(), False))
    failures = validate_shell_sources(sources)
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("all workflow/helper bazel test/build commands use //...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
