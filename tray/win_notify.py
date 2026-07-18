"""Always-visible tray-icon helpers (ported unchanged from v1)."""
from __future__ import annotations

import os
import sys
import winreg

NOTIFY_ICON_SETTINGS = r"Control Panel\NotifyIconSettings"


def _notify_icon_key():
    """Find this exe's entry under Windows 11's tray-icon settings. The key is
    created by Explorer the first time the icon appears, and keyed by the exe
    path that registered it."""
    me = os.path.normcase(os.path.abspath(
        sys.executable if getattr(sys, "frozen", False) else __file__))
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
                if os.path.normcase(path) == me:
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
