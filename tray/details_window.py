"""Single-instance details window (replaces stacking MessageBox dialogs)."""
from __future__ import annotations

import tkinter as tk
from tkinter import scrolledtext

from tray import ui_thread

_window: tk.Toplevel | None = None
_text: scrolledtext.ScrolledText | None = None


def show_details(app_name: str, body: str) -> None:
    ui_thread.call(_show, app_name, body)


def _show(app_name: str, body: str) -> None:
    global _window, _text
    root = ui_thread.root()
    if root is None:
        return

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
    win.geometry("520x420")
    win.minsize(360, 240)

    text = scrolledtext.ScrolledText(win, wrap=tk.WORD, font=("Segoe UI", 10))
    text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 6))
    text.insert("1.0", body)
    text.configure(state=tk.DISABLED)

    def close() -> None:
        global _window, _text
        _window = None
        _text = None
        win.destroy()

    btn = tk.Button(win, text="OK", width=10, command=close)
    btn.pack(pady=(0, 10))
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
