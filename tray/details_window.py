"""Single-instance details window (replaces stacking MessageBox dialogs)."""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import scrolledtext

from tray import ui_thread

_window: tk.Toplevel | None = None
_text: scrolledtext.ScrolledText | None = None
_fix_btn: tk.Button | None = None
_on_refresh: Callable[[], None] | None = None
_on_copy: Callable[[str], None] | None = None
_on_display_options: Callable[[], None] | None = None
_on_fix_auth: Callable[[], bool] | None = None


def show_details(
    app_name: str,
    body: str,
    *,
    on_refresh: Callable[[], None] | None = None,
    on_copy: Callable[[str], None] | None = None,
    on_display_options: Callable[[], None] | None = None,
    on_fix_auth: Callable[[], bool] | None = None,
    fix_auth_visible: bool = False,
) -> None:
    ui_thread.call(
        _show,
        app_name,
        body,
        on_refresh,
        on_copy,
        on_display_options,
        on_fix_auth,
        fix_auth_visible,
    )


def update_details_text(
    body: str,
    *,
    fix_auth_visible: bool | None = None,
) -> None:
    """Replace details body from any thread (no-op if window closed)."""
    ui_thread.call(_apply_text, body, fix_auth_visible)


def _show(
    app_name: str,
    body: str,
    on_refresh: Callable[[], None] | None,
    on_copy: Callable[[str], None] | None,
    on_display_options: Callable[[], None] | None,
    on_fix_auth: Callable[[], bool] | None,
    fix_auth_visible: bool,
) -> None:
    global _window, _text, _fix_btn
    global _on_refresh, _on_copy, _on_display_options, _on_fix_auth
    root = ui_thread.root()
    if root is None:
        return

    _on_refresh = on_refresh
    _on_copy = on_copy
    _on_display_options = on_display_options
    _on_fix_auth = on_fix_auth

    if _window is not None:
        try:
            if _window.winfo_exists():
                _apply_text(body, fix_auth_visible)
                _window.title(app_name)
                _window.deiconify()
                _window.lift()
                _window.focus_force()
                return
        except tk.TclError:
            _window = None
            _text = None
            _fix_btn = None

    win = tk.Toplevel(root)
    win.title(app_name)
    win.geometry("540x460")
    win.minsize(380, 280)

    text = scrolledtext.ScrolledText(win, wrap=tk.WORD, font=("Segoe UI", 10))
    text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 6))
    text.insert("1.0", body)
    text.configure(state=tk.DISABLED)

    def close() -> None:
        global _window, _text, _fix_btn
        global _on_refresh, _on_copy, _on_display_options, _on_fix_auth
        _window = None
        _text = None
        _fix_btn = None
        _on_refresh = None
        _on_copy = None
        _on_display_options = None
        _on_fix_auth = None
        win.destroy()

    def do_refresh() -> None:
        if _on_refresh is None:
            return
        _apply_text("Refreshing…", False)
        try:
            _on_refresh()
        except Exception as error:
            _apply_text(f"Refresh failed:\n{error}", None)

    def do_copy() -> None:
        if _on_copy is None:
            return
        content = text.get("1.0", tk.END).rstrip()
        try:
            _on_copy(content)
        except Exception:
            pass

    def do_options() -> None:
        if _on_display_options is not None:
            _on_display_options()

    def do_fix_auth() -> None:
        if _on_fix_auth is None:
            return
        # Callback must return quickly and do login work off this UI thread.
        # Only show Checking… when a new job was accepted.
        try:
            started = _on_fix_auth()
        except Exception as error:
            _apply_text(f"Claude login update failed:\n{error}", True)
            return
        if started:
            _apply_text("Checking Claude login…", False)

    bar = tk.Frame(win)
    bar.pack(fill=tk.X, padx=10, pady=(0, 10))
    if on_refresh is not None:
        tk.Button(bar, text="Refresh", width=10, command=do_refresh).pack(
            side=tk.LEFT, padx=2
        )
    if on_copy is not None:
        tk.Button(bar, text="Copy", width=10, command=do_copy).pack(side=tk.LEFT, padx=2)
    if on_display_options is not None:
        tk.Button(bar, text="Display options…", width=16, command=do_options).pack(
            side=tk.LEFT, padx=2
        )
    fix_btn = tk.Button(
        bar, text="Update Claude login…", width=20, command=do_fix_auth
    )
    if on_fix_auth is not None and fix_auth_visible:
        fix_btn.pack(side=tk.LEFT, padx=2)
    tk.Button(bar, text="OK", width=10, command=close).pack(side=tk.RIGHT, padx=2)

    win.protocol("WM_DELETE_WINDOW", close)
    _window = win
    _text = text
    _fix_btn = fix_btn if on_fix_auth is not None else None
    win.lift()
    win.focus_force()


def _apply_text(body: str, fix_auth_visible: bool | None = None) -> None:
    global _fix_btn
    if _text is not None:
        try:
            if _text.winfo_exists():
                _text.configure(state=tk.NORMAL)
                _text.delete("1.0", tk.END)
                _text.insert("1.0", body)
                _text.configure(state=tk.DISABLED)
        except tk.TclError:
            pass
    if fix_auth_visible is None or _fix_btn is None:
        return
    try:
        if not _fix_btn.winfo_exists():
            return
        if fix_auth_visible:
            if not _fix_btn.winfo_ismapped():
                _fix_btn.pack(side=tk.LEFT, padx=2)
        else:
            _fix_btn.pack_forget()
    except tk.TclError:
        pass
