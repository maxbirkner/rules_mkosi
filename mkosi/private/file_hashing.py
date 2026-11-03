"""SHA-256 digests of files read by rules_mkosi actions."""

import hashlib


def sha256_file(path):
    """Returns the lowercase hex SHA-256 of the file at path; raises OSError if it cannot be read."""
    with open(path, "rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()
