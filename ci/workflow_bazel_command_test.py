"""Checks that workflow build/test commands use the whole package universe."""

import re
import shlex
import sys


_BAZEL_COMMAND = re.compile(r"\bbazel\b")


def _workflow_commands(lines):
    commands = []
    for index, line in enumerate(lines):
        if line.lstrip().startswith("#") or not _BAZEL_COMMAND.search(line):
            continue
        command = line.rstrip()
        while command.endswith("\\"):
            if index + 1 == len(lines):
                break
            index += 1
            command = command[:-1] + " " + lines[index].strip()
        commands.append((index + 1, command))
    return commands


def main():
    workflow = sys.argv[1]
    lines = open(workflow, encoding="utf-8").read().splitlines()
    failures = []
    for line_number, command in _workflow_commands(lines):
        tokens = shlex.split(command)
        command_index = None
        for index, token in enumerate(tokens):
            if token != "bazel":
                continue
            subcommand_index = index + 1
            while (
                subcommand_index < len(tokens)
                and tokens[subcommand_index].startswith("-")
            ):
                subcommand_index += 1
            if (
                subcommand_index < len(tokens)
                and tokens[subcommand_index] in ("test", "build")
            ):
                command_index = subcommand_index
                break
        if command_index is None:
            continue
        target_tokens = [
            token
            for token in tokens[command_index + 1 :]
            if token.startswith(("//", "@"))
        ]
        if target_tokens != ["//..."]:
            failures.append(
                f"line {line_number}: expected only //..., got {target_tokens!r}"
            )
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("all workflow bazel test/build commands use //...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
