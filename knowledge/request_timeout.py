"""Share an answer's time budget across sequential provider calls in its thread."""
from contextlib import contextmanager
from contextvars import ContextVar
import time


class AnswerTimeout(TimeoutError):
    pass


_deadline = ContextVar('answer_deadline', default=None)


@contextmanager
def answer_deadline(seconds=270):
    deadline = time.monotonic() + seconds
    parent = _deadline.get()
    token = _deadline.set(min(deadline, parent) if parent is not None else deadline)
    try:
        yield
    finally:
        _deadline.reset(token)


def remaining_timeout(maximum):
    deadline = _deadline.get()
    if deadline is None:
        return maximum
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise AnswerTimeout('The answer took too long to prepare. Please retry your question.')
    return min(maximum, remaining)
