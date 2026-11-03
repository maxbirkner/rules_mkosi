"""Parser for Debian control data (deb822), such as Release files and Packages indexes."""


def paragraphs(text):
    """Returns the paragraphs of deb822 text as dictionaries that map field names to values, in file order.

    Lines that are empty or contain only whitespace separate paragraphs. A value has its surrounding whitespace
    removed. A continuation line, which starts with a space or a tab, is appended to the previous field's value after a
    newline, also without its surrounding whitespace, so multiline fields such as a Release file's SHA256 list keep
    one entry per line.

    Raises ValueError for a continuation line before the first field of a paragraph, a field line without a colon, and
    a field that occurs twice in one paragraph.
    """
    result = []
    current = {}
    field = None
    for line in text.splitlines():
        if not line.strip():
            if current:
                result.append(current)
                current = {}
                field = None
            continue
        if line[0].isspace():
            if field is None:
                raise ValueError("continuation without a Debian metadata field")
            current[field] += "\n" + line.strip()
            continue
        if ":" not in line:
            raise ValueError("malformed Debian metadata field: %s" % line)
        field, value = line.split(":", 1)
        if field in current:
            raise ValueError("duplicate Debian metadata field: %s" % field)
        current[field] = value.strip()
    if current:
        result.append(current)
    return result
