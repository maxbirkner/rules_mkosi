#!/bin/sh
set -eu

check="$1"
failures=0

expect() {
    expected="$1"
    title="$2"
    if "$check" "$title" >/dev/null 2>&1; then actual=pass; else actual=fail; fi
    if [ "$actual" != "$expected" ]; then
        echo "expected $expected, got $actual: $title" >&2
        failures=$((failures + 1))
    fi
}

expect pass "feat: add the manifest output"
expect pass "fix(ci): keep USER in group-free"
expect pass "feat(deps)!: upgrade mkosi to v27.1"
# shellcheck disable=SC2016 # The backticks are part of the title.
expect pass 'docs: explain `manifest = True`'
expect fail "Add kernel execution-platform preflight"
expect fail "feature: add something"
expect fail "feat:missing space"
expect fail "feat: Capitalized summary"
expect fail "feat(Scope): uppercase scope"
expect fail "feat: $(printf '%0100d' 0)"

if [ "$failures" -ne 0 ]; then
    exit 1
fi
echo "all PR title cases passed"
