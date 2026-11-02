import sys

# rules_mkosi's Python line must not change the consumer's own default.
assert sys.version_info[:2] == (3, 13), sys.version
