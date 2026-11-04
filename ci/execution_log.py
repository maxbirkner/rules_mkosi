"""Read Bazel `--execution_log_json_file` output."""

import json


def read_entries(path):
    """Returns the JSON objects of an execution log, which Bazel writes as concatenated, not line-delimited, JSON."""
    content = path.read_text()
    decoder = json.JSONDecoder()
    entries = []
    index = 0
    while index < len(content):
        while index < len(content) and content[index].isspace():
            index += 1
        if index < len(content):
            entry, index = decoder.raw_decode(content, index)
            entries.append(entry)
    return entries
