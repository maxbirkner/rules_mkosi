"""Test helper that fails when code under test reads a file without a size bound."""


class BoundedReader:
    """Wraps an open file and raises AssertionError for reads without a size or larger than limit bytes."""

    def __init__(self, wrapped, limit, description):
        self.wrapped = wrapped
        self.limit = limit
        self.description = description

    def read(self, size=-1):
        if size < 0 or size > self.limit:
            raise AssertionError("unbounded %s read" % self.description)
        return self.wrapped.read(size)

    def __getattr__(self, name):
        return getattr(self.wrapped, name)

    def __enter__(self):
        self.wrapped.__enter__()
        return self

    def __exit__(self, *args):
        return self.wrapped.__exit__(*args)
