"""Ensure only one Usage Widget v2 tray process runs at a time."""
from __future__ import annotations

import ctypes
import sys

_MUTEX_NAME = "Local\\UsageWidget-v2-single-instance"
_ERROR_ALREADY_EXISTS = 183

# Keep a process-wide handle so the mutex isn't released early.
_mutex_handle = None


def ensure_single_instance(app_name: str = "Usage Widget v2") -> bool:
    """Return True if this process should continue; False if another is running."""
    global _mutex_handle
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    if not handle:
        return True
    _mutex_handle = handle
    if kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
        ctypes.windll.user32.MessageBoxW(
            0,
            "Usage Widget v2 is already running in the system tray.",
            app_name,
            0x40,
        )
        return False
    return True


def release_single_instance() -> None:
    global _mutex_handle
    if _mutex_handle:
        ctypes.windll.kernel32.CloseHandle(_mutex_handle)
        _mutex_handle = None
