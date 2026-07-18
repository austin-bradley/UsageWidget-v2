"""System tray shell for Usage Widget v2."""
from __future__ import annotations

import ctypes
import os
import threading
import time
from datetime import datetime

import pystray

from core.config import config_path, patch_config_toggles
from core.models import AppConfig, AppSnapshot
from core.poller import fetch_all, merge_last_good
from display.details import build_details
from display.icon import render_icon
from display.profiles import get_active_profile
from display.tooltip import build_tooltip
from tray.win_notify import get_always_visible, set_always_visible


class UsageTray:
    def __init__(self, config: AppConfig):
        self.config = config
        self.snapshot = AppSnapshot(fetched_at=datetime.now(), accounts=[])
        self._rotate_index = 0
        self._stop = False

        menu = pystray.Menu(
            pystray.MenuItem("Show details", self._on_details, default=True),
            pystray.MenuItem("Refresh now", self._on_refresh),
            pystray.MenuItem("Display profile", pystray.Menu(self._profile_menu)),
            pystray.MenuItem("Accounts", pystray.Menu(self._accounts_menu)),
            pystray.MenuItem(
                "Always visible",
                self._on_toggle_visible,
                checked=lambda item: get_always_visible(),
            ),
            pystray.MenuItem("Open config", self._on_open_config),
            pystray.MenuItem("Quit", self._on_quit),
        )
        profile = get_active_profile(self.config)
        self.icon = pystray.Icon(
            "usage-widget",
            render_icon(profile, self.snapshot, self._rotate_index),
            f"{self.config.app_name}: loading…",
            menu,
        )

    def _profile_menu(self):
        items = []
        for name in self.config.profiles:
            items.append(
                pystray.MenuItem(
                    name,
                    self._make_profile_handler(name),
                    checked=lambda item, n=name: self.config.active_profile == n,
                    radio=True,
                )
            )
        if not items:
            items.append(pystray.MenuItem("(none)", None, enabled=False))
        return pystray.Menu(*items)

    def _accounts_menu(self):
        items = []
        for account in self.config.accounts:
            items.append(
                pystray.MenuItem(
                    account.label or account.id,
                    self._make_account_handler(account.id),
                    checked=lambda item, aid=account.id: self._is_account_enabled(aid),
                )
            )
        if not items:
            items.append(pystray.MenuItem("(none)", None, enabled=False))
        return pystray.Menu(*items)

    def _is_account_enabled(self, account_id: str) -> bool:
        for account in self.config.accounts:
            if account.id == account_id:
                return account.enabled
        return False

    def _make_profile_handler(self, name: str):
        def handler(icon, item):
            self.config.active_profile = name
            patch_config_toggles(self.config)
            self._rotate_index = 0
            self._render()

        return handler

    def _make_account_handler(self, account_id: str):
        def handler(icon, item):
            for account in self.config.accounts:
                if account.id == account_id:
                    account.enabled = not account.enabled
                    break
            patch_config_toggles(self.config)
            self.refresh_async()

        return handler

    def _on_details(self, icon, item):
        profile = get_active_profile(self.config)
        text = build_details(profile, self.snapshot)
        threading.Thread(target=self._show_messagebox, args=(text,), daemon=True).start()

    def _on_toggle_visible(self, icon, item):
        want = not get_always_visible()
        if not set_always_visible(want):
            self._show_messagebox(
                "Couldn't find this app's tray-icon setting yet.\n\n"
                "Windows creates it the first time the icon appears. Try again "
                "in a moment, or set it via Settings > Personalization > "
                "Taskbar > Other system tray icons."
            )

    def _show_messagebox(self, text: str) -> None:
        ctypes.windll.user32.MessageBoxW(0, text, self.config.app_name, 0x40)

    def _on_open_config(self, icon, item):
        os.startfile(str(config_path()))

    def _on_refresh(self, icon, item):
        self.refresh_async()

    def _on_quit(self, icon, item):
        self._stop = True
        icon.stop()

    def refresh_async(self) -> None:
        threading.Thread(target=self._refresh_once, daemon=True).start()

    def _refresh_once(self) -> None:
        try:
            fresh = fetch_all(self.config)
            self.snapshot = merge_last_good(self.snapshot, fresh)
        except Exception:
            # Stale-last-good: keep prior snapshot on total failure.
            pass
        self._render()

    def _render(self) -> None:
        profile = get_active_profile(self.config)
        self.icon.icon = render_icon(profile, self.snapshot, self._rotate_index)
        self.icon.title = build_tooltip(profile, self.snapshot)

    def _poll_loop(self) -> None:
        while not self._stop:
            try:
                self._refresh_once()
            except Exception:
                pass
            for _ in range(max(1, self.config.poll_seconds)):
                if self._stop:
                    return
                time.sleep(1)

    def _rotate_loop(self) -> None:
        while not self._stop:
            profile = get_active_profile(self.config)
            seconds = max(1, profile.icon.rotate_seconds)
            for _ in range(seconds):
                if self._stop:
                    return
                time.sleep(1)
            if get_active_profile(self.config).icon.mode == "rotate":
                self._rotate_index += 1
                try:
                    self._render()
                except Exception:
                    pass

    def run(self) -> None:
        threading.Thread(target=self._poll_loop, daemon=True).start()
        threading.Thread(target=self._rotate_loop, daemon=True).start()
        self.icon.run()
