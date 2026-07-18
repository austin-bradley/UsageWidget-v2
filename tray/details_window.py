"""Single-instance details window (replaces stacking MessageBox dialogs)."""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import scrolledtext

from tray import ui_thread

_window: tk.Toplevel | None = None
_text: scrolledtext.ScrolledText | None = None
_get_body: Callable[[], str] | None = None
_on_refresh: Callable[[], str] | None = None
_on_copy: Callable[[str], None] | None = None
_on_display_options: Callable[[], None] | None = None


def show_details(
    app_name: str,
    body: str,
    *,
    get_body: Callable[[], str] | None = None,
    on_refresh: Callable[[], str] | None = None,
    on_copy: Callable[[str], None] | None = None,
    on_display_options: Callable[[], None] | None = None,
) -> None:
    ui_thread.call(
        _show,
        app_name,
        body,
        get_body,
        on_refresh,
        on_copy,
        on_display_options,
    )


def _show(
    app_name: str,
    body: str,
    get_body: Callable[[], str] | None,
    on_refresh: Callable[[], str] | None,
    on_copy: Callable[[str], None] | None,
    on_display_options: Callable[[], None] | None,
) -> None:
    global _window, _text, _get_body, _on_refresh, _on_copy, _on_display_options
    root = ui_thread.root()
    if root is None:
        return

    _get_body = get_body
    _on_refresh = on_refresh
    _on_copy = on_copy
    _on_display_options = on_display_options

    if _window is not None:
        try:
            if _window.winfo_exists():
                _apply_text(body)
                _window.title(app_name)
                _window.deiconify()
                _window.lift()
                _window.focus_force()
                return
        except tk.TclError:
            _window = None
            _text = None

    win = tk.Toplevel(root)
    win.title(app_name)
    win.geometry("540x460")
    win.minsize(380, 280)

    text = scrolledtext.ScrolledText(win, wrap=tk.WORD, font=("Segoe UI", 10))
    text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 6))
    text.insert("1.0", body)
    text.configure(state=tk.DISABLED)

    def close() -> None:
        global _window, _text, _get_body, _on_refresh, _on_copy, _on_display_options
        _window = None
        _text = None
        _get_body = None
        _on_refresh = None
        _on_copy = None
        _on_display_options = None
        win.destroy()

    def do_refresh() -> None:
        if _on_refresh is None:
            return
        try:
            _apply_text(_on_refresh())
        except Exception as error:
            _apply_text(f"Refresh failed:\n{error}")

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
    tk.Button(bar, text="OK", width=10, command=close).pack(side=tk.RIGHT, padx=2)

    win.protocol("WM_DELETE_WINDOW", close)
    _window = win
    _text = text
    win.lift()
    win.focus_force()


def _apply_text(body: str) -> None:
    if _text is None:
        return
    _text.configure(state=tk.NORMAL)
    _text.delete("1.0", tk.END)
    _text.insert("1.0", body)
    _text.configure(state=tk.DISABLED)
