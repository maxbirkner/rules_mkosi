#!/bin/sh
# Checks that a pull request title is a Conventional Commit subject, because it becomes the squashed commit message.
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: check-pr-title TITLE" >&2
    exit 2
fi

title="$1"
types="build|chore|ci|deps|docs|feat|fix|perf|refactor|revert|style|test"
pattern="^($types)(\([a-z0-9._/-]+\))?!?: [a-z0-9\`]"

if [ "${#title}" -gt 100 ]; then
    echo "PR title is longer than 100 characters: $title" >&2
    exit 1
fi
if ! printf '%s\n' "$title" | grep -Eq "$pattern"; then
    echo "PR title is not a Conventional Commit subject: $title" >&2
    echo "Use '<type>[(scope)][!]: <lowercase summary>' with type one of: $types" >&2
    exit 1
fi
