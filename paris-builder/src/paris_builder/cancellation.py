"""Cooperative job interruption; completed artifacts remain resumable."""
from contextlib import contextmanager
import threading


class RunInterrupted(RuntimeError):
    pass


class Cancellation:
    def __init__(self):
        self.requested = threading.Event()
        self.lock = threading.Lock()
        self.callbacks = set()

    def request(self):
        with self.lock:
            self.requested.set()
            callbacks = list(self.callbacks)
        for callback in callbacks:
            threading.Thread(target=callback, daemon=True).start()

    def register(self, callback):
        with self.lock:
            self.callbacks.add(callback)
            requested = self.requested.is_set()
        if requested:
            threading.Thread(target=callback, daemon=True).start()
        def unregister():
            with self.lock:
                self.callbacks.discard(callback)
        return unregister


CURRENT = threading.local()


@contextmanager
def scope(token):
    previous = getattr(CURRENT, 'token', None)
    CURRENT.token = token
    try:
        yield
    finally:
        CURRENT.token = previous


def interrupted():
    token = getattr(CURRENT, 'token', None)
    return bool(token and token.requested.is_set())


def checkpoint():
    if interrupted():
        raise RunInterrupted('任务已中断，已完成的记录和产物已保留，可继续执行')


def on_interrupt(callback):
    token = getattr(CURRENT, 'token', None)
    return token.register(callback) if token else lambda: None
