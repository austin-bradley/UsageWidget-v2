"""Always-visible tray-icon helpers (ported from v1, path matching fixed)."""
from __future__ import annotations

import os
import sys
import winreg

NOTIFY_ICON_SETTINGS = r"Control Panel\NotifyIconSettings"


def _candidate_executable_paths() -> list[str]:
    """Paths Explorer may have stored as NotifyIconSettings ExecutablePath.

    Frozen builds register as the .exe. Source runs register as python.exe /
    pythonw.exe (not this module's __file__).
    """
    paths: list[str] = []
    for raw in (sys.executable, sys.argv[0] if sys.argv else None):
        if not raw:
            continue
        try:
            paths.append(os.path.normcase(os.path.abspath(raw)))
        except OSError:
            continue
    # Preserve order, drop duplicates
    seen: set[str] = set()
    unique: list[str] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def _notify_icon_key():
    """Find this process's entry under Windows 11's tray-icon settings."""
    candidates = _candidate_executable_paths()
    if not candidates:
        return None
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, NOTIFY_ICON_SETTINGS) as root:
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(root, i)
            except OSError:
                return None
            i += 1
            try:
                with winreg.OpenKey(root, sub) as k:
                    path, _ = winreg.QueryValueEx(k, "ExecutablePath")
                if os.path.normcase(path) in candidates:
                    return sub
            except OSError:
                continue


def get_always_visible():
    try:
        sub = _notify_icon_key()
        if not sub:
            return False
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, NOTIFY_ICON_SETTINGS + "\\" + sub) as k:
            return bool(winreg.QueryValueEx(k, "IsPromoted")[0])
    except OSError:
        return False


def set_always_visible(value):
    """Toggle whether the icon sits on the taskbar or in the overflow drawer.
    Explorer owns this setting; it re-reads the key when the tray is next
    rebuilt, so the icon may not move until the icon is re-registered."""
    sub = _notify_icon_key()
    if not sub:
        return False
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, NOTIFY_ICON_SETTINGS + "\\" + sub,
                        0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "IsPromoted", 0, winreg.REG_DWORD, 1 if value else 0)
    return True
