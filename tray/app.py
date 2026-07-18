"""System tray shell for Usage Widget v2."""
from __future__ import annotations

import ctypes
import os
import threading
import time
from datetime import datetime

import pystray

from core.app_log import log_event, log_path
from core.config import config_path, load_config, patch_config_toggles
from core.models import AppConfig, AppSnapshot
from core.poller import fetch_all, filter_enabled, merge_last_good, next_poll_seconds
from core.snapshot_cache import load_snapshot, save_snapshot
from display.details import build_details
from display.icon import render_icon
from display.profiles import get_active_profile
from display.tooltip import build_tooltip
from tray.win_notify import get_always_visible, set_always_visible


class UsageTray:
    def __init__(self, config: AppConfig):
        self.config = config
        cached = load_snapshot()
        if cached is not None:
            self.snapshot = filter_enabled(cached, config)
        else:
            self.snapshot = AppSnapshot(fetched_at=datetime.now(), accounts=[])
        self._rotate_index = 0
        self._stop = False
        self._state_lock = threading.Lock()
        self._refreshing = False
        self._refresh_pending = False
        self._last_fetch_error: str | None = None

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
            pystray.MenuItem("Reload config", self._on_reload_config),
            pystray.MenuItem("Open log", self._on_open_log),
            pystray.MenuItem("Quit", self._on_quit),
        )
        log_event(f"tray start ({len(config.accounts)} accounts configured)")
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
            with self._state_lock:
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
        with self._state_lock:
            snapshot = self.snapshot
            fetch_error = self._last_fetch_error
        text = build_details(profile, snapshot)
        if fetch_error:
            text = f"Last refresh failed: {fetch_error}\n\n{text}"
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

    def _on_reload_config(self, icon, item):
        try:
            self.config = load_config()
            with self._state_lock:
                self._rotate_index = 0
                self.snapshot = filter_enabled(self.snapshot, self.config)
            log_event("config reloaded")
            self.refresh_async()
        except Exception as e:
            log_event(f"config reload failed: {e}")
            self._show_messagebox(f"Couldn't reload config:\n{e}")

    def _on_open_log(self, icon, item):
        path = log_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text("", encoding="utf-8")
            os.startfile(str(path))
        except Exception as e:
            self._show_messagebox(f"Couldn't open log:\n{e}")

    def _on_refresh(self, icon, item):
        self.refresh_async()

    def _on_quit(self, icon, item):
        self._stop = True
        icon.stop()

    def refresh_async(self) -> None:
        """Start at most one fetch; coalesce overlapping refresh requests."""
        with self._state_lock:
            if self._refreshing:
                self._refresh_pending = True
                return
            self._refreshing = True
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self) -> None:
        while True:
            try:
                fresh = fetch_all(self.config)
                fresh = filter_enabled(fresh, self.config)
                with self._state_lock:
                    self.snapshot = merge_last_good(self.snapshot, fresh)
                    self._last_fetch_error = None
                    to_save = self.snapshot
                for account in to_save.accounts:
                    if account.error:
                        log_event(f"{account.account_id}: {account.error}")
                try:
                    save_snapshot(to_save)
                except Exception as cache_error:
                    log_event(f"snapshot cache write failed: {cache_error}")
            except Exception as e:
                # Stale-last-good: keep prior snapshot on total failure.
                with self._state_lock:
                    self._last_fetch_error = str(e)
                log_event(f"refresh failed: {e}")
            self._render()
            with self._state_lock:
                if not self._refresh_pending or self._stop:
                    self._refreshing = False
                    self._refresh_pending = False
                    return
                self._refresh_pending = False

    def _refresh_once(self) -> None:
        """Compatibility helper for smokes/tests — runs a single fetch inline."""
        try:
            fresh = fetch_all(self.config)
            fresh = filter_enabled(fresh, self.config)
            with self._state_lock:
                self.snapshot = merge_last_good(self.snapshot, fresh)
                self._last_fetch_error = None
                to_save = self.snapshot
            try:
                save_snapshot(to_save)
            except Exception:
                pass
        except Exception as e:
            with self._state_lock:
                self._last_fetch_error = str(e)
            log_event(f"refresh failed: {e}")
        self._render()

    def _render(self) -> None:
        profile = get_active_profile(self.config)
        with self._state_lock:
            snapshot = self.snapshot
            rotate_index = self._rotate_index
            fetch_error = self._last_fetch_error
        image = render_icon(profile, snapshot, rotate_index)
        title = build_tooltip(profile, snapshot)
        if fetch_error:
            prefix = "refresh failed · "
            title = (prefix + title)[:127]
        # Serialize Win32 notify updates; pystray has no public schedule API.
        with self._state_lock:
            self.icon.icon = image
            self.icon.title = title

    def _poll_loop(self) -> None:
        while not self._stop:
            try:
                self.refresh_async()
            except Exception:
                pass
            for _ in range(next_poll_seconds(self.config)):
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
                with self._state_lock:
                    self._rotate_index += 1
                try:
                    self._render()
                except Exception:
                    pass

    def run(self) -> None:
        threading.Thread(target=self._poll_loop, daemon=True).start()
        threading.Thread(target=self._rotate_loop, daemon=True).start()
        self.icon.run()
