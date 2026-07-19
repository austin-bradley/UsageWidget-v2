"""Shared Tk mainloop for tray-owned windows (details, display options)."""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from collections.abc import Callable
from typing import Any

from core.app_log import log_event

_lock = threading.Lock()
_started = False
_ready = threading.Event()
_failed = False
_root: tk.Tk | None = None
_jobs: queue.Queue[Callable[[], None]] = queue.Queue()


def ensure_started() -> bool:
    """Start the UI thread if needed. Returns False when Tk is unavailable."""
    global _started, _failed
    with _lock:
        if _failed:
            return False
        if _started:
            pass
        else:
            _started = True
            thread = threading.Thread(target=_run, name="usage-widget-ui", daemon=True)
            thread.start()
    if not _ready.wait(timeout=5):
        with _lock:
            if _root is None:
                _failed = True
                _started = False
                log_event("ui thread: Tk did not become ready")
                return False
    return not _failed and _root is not None


def call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    """Schedule ``fn`` on the Tk thread."""
    if not ensure_started():
        log_event(f"ui thread unavailable; dropped call to {getattr(fn, '__name__', fn)}")
        return

    def job() -> None:
        fn(*args, **kwargs)

    _jobs.put(job)


def _run() -> None:
    global _root, _started, _failed
    try:
        root = tk.Tk()
        root.withdraw()
        root.title("Usage Widget v2 UI")
        _root = root
        _ready.set()
    except Exception as error:
        log_event(f"ui thread: Tk init failed: {error}")
        with _lock:
            _failed = True
            _started = False
            _root = None
        _ready.set()
        return

    def pump() -> None:
        while True:
            try:
                job = _jobs.get_nowait()
            except queue.Empty:
                break
            try:
                job()
            except Exception as error:
                log_event(f"ui thread job failed: {error}")
        root.after(50, pump)

    root.after(50, pump)
    try:
        root.mainloop()
    finally:
        with _lock:
            _root = None
            _started = False
            _ready.clear()


def root() -> tk.Tk | None:
    if not _ready.is_set():
        _ready.wait(timeout=5)
    return _root
