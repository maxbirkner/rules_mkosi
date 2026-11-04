"""Compiler options shared by the C and C++ helpers of rules_mkosi.

The helpers also build inside consumer workspaces with whatever compiler those select, so these lists only enable
warnings. The repository's own .bazelrc turns them into errors for rules_mkosi sources with --per_file_copt.
"""

_WARNINGS = [
    "-Wall",
    "-Wextra",
    "-Wshadow",
    "-Wformat=2",
    "-Wundef",
    "-Wconversion",
    "-Wsign-conversion",
    "-Wimplicit-fallthrough",
    "-Wpointer-arith",
    "-Wvla",
]

# Options for targets whose sources are C.
C_WARNINGS = _WARNINGS + [
    "-Wstrict-prototypes",
    "-Wmissing-prototypes",
]

# Options for targets whose sources are C++, which rejects the C-only prototype warnings.
CXX_WARNINGS = _WARNINGS
