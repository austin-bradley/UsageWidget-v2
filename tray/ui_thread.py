"""Shared Tk mainloop for tray-owned windows (details, display options)."""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from collections.abc import Callable
from typing import Any

_lock = threading.Lock()
_started = False
_ready = threading.Event()
_root: tk.Tk | None = None
_jobs: queue.Queue[Callable[[], None]] = queue.Queue()


def ensure_started() -> None:
    global _started
    with _lock:
        if _started:
            return
        _started = True
        thread = threading.Thread(target=_run, name="usage-widget-ui", daemon=True)
        thread.start()
    _ready.wait(timeout=5)


def call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    """Schedule ``fn`` on the Tk thread."""
    ensure_started()

    def job() -> None:
        fn(*args, **kwargs)

    _jobs.put(job)


def _run() -> None:
    global _root
    root = tk.Tk()
    root.withdraw()
    root.title("Usage Widget v2 UI")
    _root = root
    _ready.set()

    def pump() -> None:
        while True:
            try:
                job = _jobs.get_nowait()
            except queue.Empty:
                break
            try:
                job()
            except Exception:
                pass
        root.after(50, pump)

    root.after(50, pump)
    root.mainloop()


def root() -> tk.Tk | None:
    if not _ready.is_set():
        _ready.wait(timeout=5)
    return _root
