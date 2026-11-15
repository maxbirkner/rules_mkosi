"""Test helper that fails when code under test reads a file without a size bound."""

from types import TracebackType
from typing import IO, Any, AnyStr, Generic


class BoundedReader(Generic[AnyStr]):
    """Wraps an open file and raises AssertionError for reads without a size or larger than limit bytes."""

    def __init__(self, wrapped: IO[AnyStr], limit: int, description: str) -> None:
        self.wrapped: IO[AnyStr] = wrapped
        self.limit = limit
        self.description = description

    def read(self, size: int = -1) -> AnyStr:
        if size < 0 or size > self.limit:
            raise AssertionError("unbounded %s read" % self.description)
        return self.wrapped.read(size)

    # The wrapper forwards every other file attribute unchanged, whatever its type.
    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        return getattr(self.wrapped, name)

    def __enter__(self) -> "BoundedReader[AnyStr]":
        self.wrapped.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return self.wrapped.__exit__(exc_type, exc, traceback)
