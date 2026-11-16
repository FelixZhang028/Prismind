"""Optional progress reporting; no web dependency in the engine."""
from contextlib import contextmanager
from contextvars import ContextVar

_reporter = ContextVar("progress_reporter", default=None)


def report(stage: str, completed: int = 0, total: int = 0) -> None:
    callback = _reporter.get()
    if callback is not None:
        callback(stage, completed, total)


@contextmanager
def reporting(callback):
    token = _reporter.set(callback)
    try:
        yield
    finally:
        _reporter.reset(token)
