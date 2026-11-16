"""Test helpers that wrap the files that code under test opens, such as a reader that fails reads without a bound."""

import builtins
import os
import pathlib
from collections.abc import Callable
from contextlib import AbstractContextManager
from types import TracebackType
from typing import IO, Any, AnyStr, Generic, TypeVar
from unittest import mock

_Wrapper = TypeVar("_Wrapper", bound="FileWrapper[Any]")

# Receives the path and mode that the code under test opens and the opened file, and returns what open() returns.
OpenWrapper = Callable[[str | os.PathLike[str], str, IO[Any]], object]


class FileWrapper(Generic[AnyStr]):
    """Wraps an open file and forwards everything to it; subclasses replace read."""

    def __init__(self, wrapped: IO[AnyStr]) -> None:
        self.wrapped: IO[AnyStr] = wrapped

    def read(self, size: int = -1) -> AnyStr:
        return self.wrapped.read(size)

    # The wrapper forwards every other file attribute unchanged, whatever its type.
    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        return getattr(self.wrapped, name)

    def __enter__(self: _Wrapper) -> _Wrapper:
        self.wrapped.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return self.wrapped.__exit__(exc_type, exc, traceback)


class BoundedReader(FileWrapper[AnyStr]):
    """Wraps an open file and raises AssertionError for reads without a size or larger than limit bytes."""

    def __init__(self, wrapped: IO[AnyStr], limit: int, description: str) -> None:
        # mypy rejects super().__init__() with the constrained AnyStr of a generic subclass.
        FileWrapper.__init__(self, wrapped)
        self.limit = limit
        self.description = description

    def read(self, size: int = -1) -> AnyStr:
        if size < 0 or size > self.limit:
            raise AssertionError("unbounded %s read" % self.description)
        return self.wrapped.read(size)


def _wrapping_open(original: Callable[..., IO[Any]], wrap: OpenWrapper) -> Callable[..., object]:
    def wrapped_open(
        path: str | os.PathLike[str],
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> object:
        return wrap(path, mode, original(path, mode, buffering, encoding, errors, newline))

    return wrapped_open


def wrap_path_open(wrap: OpenWrapper) -> AbstractContextManager[object]:
    """Patches pathlib.Path.open so that it returns wrap(path, mode, file) for each file that it opens."""
    return mock.patch.object(pathlib.Path, "open", _wrapping_open(pathlib.Path.open, wrap))


def wrap_builtin_open(wrap: OpenWrapper) -> AbstractContextManager[object]:
    """Patches the built-in open() so that it returns wrap(path, mode, file) for each file that it opens."""
    return mock.patch.object(builtins, "open", _wrapping_open(builtins.open, wrap))
