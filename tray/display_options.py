"""Display Options modal — edit active profile icon + tooltip slots."""
from __future__ import annotations

import copy
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

from PIL import ImageTk

from core.models import AppConfig, AppSnapshot, DisplayProfile, DisplaySlot, TooltipDisplay
from display.available_metrics import SHOW_MODES, list_available_metric_refs
from display.icon import render_icon
from display.profiles import get_active_profile
from display.tooltip import build_tooltip
from tray import ui_thread

_window: tk.Toplevel | None = None


def open_display_options(
    *,
    get_state: Callable[[], tuple[AppConfig, AppSnapshot]],
    on_save: Callable[[AppConfig], None],
) -> None:
    ui_thread.call(_open, get_state, on_save)


def _open(
    get_state: Callable[[], tuple[AppConfig, AppSnapshot]],
    on_save: Callable[[AppConfig], None],
) -> None:
    global _window
    root = ui_thread.root()
    if root is None:
        return

    if _window is not None:
        try:
            if _window.winfo_exists():
                _window.deiconify()
                _window.lift()
                _window.focus_force()
                return
        except tk.TclError:
            _window = None

    config, snapshot = get_state()
    draft = copy.deepcopy(get_active_profile(config))
    refs = list_available_metric_refs(config, snapshot)
    ref_labels = [label for _, label in refs]
    ref_by_label = {label: ref for ref, label in refs}
    label_by_ref = {ref: label for ref, label in refs}

    win = tk.Toplevel(root)
    win.title("Display options")
    win.geometry("560x520")
    win.minsize(480, 420)
    _window = win

    tip = tk.Label(
        win,
        text="Tray icons are tiny — prefer one large number. Tooltip changes apply after Save + refresh.",
        wraplength=520,
        justify=tk.LEFT,
        fg="#444",
    )
    tip.pack(fill=tk.X, padx=12, pady=(10, 4))

    preset_row = tk.Frame(win)
    preset_row.pack(fill=tk.X, padx=12, pady=4)
    tk.Label(preset_row, text="Preset:").pack(side=tk.LEFT)
    available_refs = {ref for ref, _ in refs}
    # Presets that bind live meters must not trust catalog fallbacks alone.
    live_refs = {
        f"{account.account_id}.{metric.id}"
        for account in snapshot.accounts
        for metric in account.metrics
    }
    preset_values = [
        "(choose)",
        "Session %",
        "Session % + reset",
        "Week %",
        "Reset countdown only",
    ]
    if (
        "claude-personal.session" in live_refs
        and "cursor-main.overall" in live_refs
    ):
        preset_values.append("Claude + Cursor split")

    preset_var = tk.StringVar(value="(choose)")
    preset_box = ttk.Combobox(
        preset_row,
        textvariable=preset_var,
        state="readonly",
        width=36,
        values=preset_values,
    )
    preset_box.pack(side=tk.LEFT, padx=8)

    notebook = ttk.Notebook(win)
    notebook.pack(fill=tk.BOTH, expand=True, padx=12, pady=6)

    icon_tab = tk.Frame(notebook)
    tip_tab = tk.Frame(notebook)
    notebook.add(icon_tab, text="Icon")
    notebook.add(tip_tab, text="Tooltip")

    # --- Icon tab ---
    if draft.icon.mode == "rotate":
        initial_layout = "rotate"
    elif draft.icon.mode == "single" or draft.icon.layout == "primary_only":
        initial_layout = "single"
    else:
        initial_layout = "split"
    layout_var = tk.StringVar(value=initial_layout)
    tk.Label(icon_tab, text="Layout").grid(row=0, column=0, sticky="w", padx=8, pady=6)
    tk.Radiobutton(icon_tab, text="Single (large)", variable=layout_var, value="single").grid(
        row=0, column=1, sticky="w"
    )
    tk.Radiobutton(icon_tab, text="Split (2 values)", variable=layout_var, value="split").grid(
        row=0, column=2, sticky="w"
    )
    tk.Radiobutton(icon_tab, text="Rotate", variable=layout_var, value="rotate").grid(
        row=0, column=3, sticky="w"
    )

    color_by_var = tk.StringVar(value=draft.icon.color_by or "percent")
    tk.Label(icon_tab, text="Color by").grid(row=3, column=0, sticky="w", padx=8, pady=4)
    ttk.Combobox(
        icon_tab,
        textvariable=color_by_var,
        values=["percent", "remaining_pct", "none"],
        state="readonly",
        width=16,
    ).grid(row=3, column=1, sticky="w", padx=4, pady=4)

    preview_label = tk.Label(icon_tab)
    preview_label.grid(row=0, column=4, rowspan=4, padx=12, pady=6)
    _preview_photo: list[ImageTk.PhotoImage | None] = [None]

    icon_slots: list[dict[str, object]] = []
    icon_frames: list[tk.LabelFrame] = []
    for i in range(2):
        slot = draft.icon.slots[i] if i < len(draft.icon.slots) else None
        frame = tk.LabelFrame(icon_tab, text=f"Slot {i + 1}")
        frame.grid(row=1 + i, column=0, columnspan=3, sticky="ew", padx=8, pady=4)
        icon_tab.columnconfigure(0, weight=1)
        icon_frames.append(frame)

        ref_var = tk.StringVar(
            value=label_by_ref.get(slot.ref, slot.ref) if slot else ""
        )
        show_var = tk.StringVar(value=slot.show if slot else "percent")
        label_var = tk.StringVar(value=(slot.label or "") if slot else "")

        tk.Label(frame, text="Metric").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        ref_box = ttk.Combobox(frame, textvariable=ref_var, values=ref_labels, width=40)
        ref_box.grid(row=0, column=1, sticky="ew", padx=4, pady=2)
        tk.Label(frame, text="Show").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        show_box = ttk.Combobox(
            frame, textvariable=show_var, values=list(SHOW_MODES), width=20, state="readonly"
        )
        show_box.grid(row=1, column=1, sticky="w", padx=4, pady=2)
        tk.Label(frame, text="Label").grid(row=2, column=0, sticky="w", padx=4, pady=2)
        tk.Entry(frame, textvariable=label_var, width=12).grid(
            row=2, column=1, sticky="w", padx=4, pady=2
        )
        frame.columnconfigure(1, weight=1)
        icon_slots.append(
            {"ref": ref_var, "show": show_var, "label": label_var, "box": ref_box}
        )

    # --- Tooltip tab ---
    tip_slots: list[DisplaySlot] = [copy.deepcopy(s) for s in draft.tooltip.slots]

    list_frame = tk.Frame(tip_tab)
    list_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)
    tip_list = tk.Listbox(list_frame, height=12, activestyle="dotbox")
    tip_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scroll = tk.Scrollbar(list_frame, command=tip_list.yview)
    scroll.pack(side=tk.RIGHT, fill=tk.Y)
    tip_list.configure(yscrollcommand=scroll.set)

    preview_var = tk.StringVar(value="")
    tk.Label(tip_tab, text="Preview:").pack(anchor="w", padx=8)
    tk.Label(tip_tab, textvariable=preview_var, wraplength=500, justify=tk.LEFT, fg="#222").pack(
        anchor="w", padx=8, pady=(0, 6)
    )

    def slot_summary(slot: DisplaySlot) -> str:
        pretty = label_by_ref.get(slot.ref, slot.ref)
        label = f" [{slot.label}]" if slot.label else ""
        return f"{pretty} · {slot.show}{label}"

    def refresh_tip_list() -> None:
        tip_list.delete(0, tk.END)
        for slot in tip_slots:
            tip_list.insert(tk.END, slot_summary(slot))
        update_preview()

    def update_preview() -> None:
        probe = copy.deepcopy(draft)
        probe.tooltip.slots = [copy.deepcopy(s) for s in tip_slots]
        preview_var.set(build_tooltip(probe, snapshot) or "(empty)")

    def move(delta: int) -> None:
        sel = tip_list.curselection()
        if not sel:
            return
        i = sel[0]
        j = i + delta
        if j < 0 or j >= len(tip_slots):
            return
        tip_slots[i], tip_slots[j] = tip_slots[j], tip_slots[i]
        refresh_tip_list()
        tip_list.selection_set(j)

    def remove_slot() -> None:
        sel = tip_list.curselection()
        if not sel:
            return
        del tip_slots[sel[0]]
        refresh_tip_list()

    def add_slot() -> None:
        dlg = tk.Toplevel(win)
        dlg.title("Add tooltip row")
        dlg.transient(win)
        dlg.grab_set()
        ref_v = tk.StringVar(value=ref_labels[0] if ref_labels else "")
        show_v = tk.StringVar(value="percent_and_reset")
        label_v = tk.StringVar(value="")
        tk.Label(dlg, text="Metric").grid(row=0, column=0, padx=8, pady=6, sticky="w")
        ttk.Combobox(dlg, textvariable=ref_v, values=ref_labels, width=40).grid(
            row=0, column=1, padx=8, pady=6
        )
        tk.Label(dlg, text="Show").grid(row=1, column=0, padx=8, pady=6, sticky="w")
        ttk.Combobox(
            dlg, textvariable=show_v, values=list(SHOW_MODES), state="readonly", width=20
        ).grid(row=1, column=1, padx=8, pady=6, sticky="w")
        tk.Label(dlg, text="Label").grid(row=2, column=0, padx=8, pady=6, sticky="w")
        tk.Entry(dlg, textvariable=label_v, width=16).grid(
            row=2, column=1, padx=8, pady=6, sticky="w"
        )

        def ok() -> None:
            label = ref_v.get().strip()
            ref = ref_by_label.get(label, label)
            if not ref:
                return
            tip_slots.append(
                DisplaySlot(
                    ref=ref,
                    show=show_v.get() or "percent",
                    label=label_v.get().strip() or None,
                )
            )
            refresh_tip_list()
            dlg.destroy()

        tk.Button(dlg, text="Add", command=ok, width=10).grid(row=3, column=1, sticky="e", padx=8, pady=10)
        tk.Button(dlg, text="Cancel", command=dlg.destroy, width=10).grid(
            row=3, column=0, sticky="e", padx=8, pady=10
        )

    # Simple drag reorder within listbox
    _drag_index: list[int | None] = [None]

    def on_drag_start(event: tk.Event) -> None:
        _drag_index[0] = tip_list.nearest(event.y)

    def on_drag_motion(event: tk.Event) -> None:
        i = _drag_index[0]
        if i is None:
            return
        j = tip_list.nearest(event.y)
        if j == i or j < 0 or j >= len(tip_slots):
            return
        tip_slots.insert(j, tip_slots.pop(i))
        _drag_index[0] = j
        refresh_tip_list()
        tip_list.selection_set(j)

    def on_drag_end(_event: tk.Event) -> None:
        _drag_index[0] = None

    # Right-drag reorders so left-click can select a row.
    tip_list.bind("<ButtonPress-3>", on_drag_start)
    tip_list.bind("<B3-Motion>", on_drag_motion)
    tip_list.bind("<ButtonRelease-3>", on_drag_end)

    btns = tk.Frame(tip_tab)
    btns.pack(fill=tk.X, padx=8, pady=4)
    tk.Button(btns, text="Add…", command=add_slot, width=8).pack(side=tk.LEFT, padx=2)
    tk.Button(btns, text="Remove", command=remove_slot, width=8).pack(side=tk.LEFT, padx=2)
    tk.Button(btns, text="Up", command=lambda: move(-1), width=6).pack(side=tk.LEFT, padx=2)
    tk.Button(btns, text="Down", command=lambda: move(1), width=6).pack(side=tk.LEFT, padx=2)
    tk.Label(btns, text="Right-drag to reorder", fg="#666").pack(side=tk.LEFT, padx=8)

    def resolve_ref(raw: str) -> str | None:
        raw = raw.strip()
        if not raw:
            return None
        return ref_by_label.get(raw, raw if "." in raw else None)

    def collect_icon_slots() -> list[DisplaySlot]:
        slots: list[DisplaySlot] = []
        layout = layout_var.get()
        limit = 1 if layout == "single" else 2
        for i in range(limit):
            row = icon_slots[i]
            ref = resolve_ref(str(row["ref"].get()))  # type: ignore[arg-type]
            if not ref:
                continue
            label = str(row["label"].get()).strip() or None  # type: ignore[union-attr]
            slots.append(
                DisplaySlot(
                    ref=ref,
                    show=str(row["show"].get()) or "percent",  # type: ignore[union-attr]
                    label=label,
                )
            )
        return slots

    def apply_layout_to_icon(icon) -> None:
        layout = layout_var.get()
        if layout == "single":
            icon.mode = "single"
            icon.layout = "primary_only"
            icon.max_slots = 1
        elif layout == "rotate":
            icon.mode = "rotate"
            icon.layout = "primary_only"
            icon.max_slots = max(1, len(collect_icon_slots()) or 1)
        else:
            icon.mode = "composite"
            icon.layout = "split"
            icon.max_slots = 2

    def sync_layout_ui(*_args: object) -> None:
        if layout_var.get() == "single":
            icon_frames[1].grid_remove()
        else:
            icon_frames[1].grid()
        refresh_icon_preview()

    def refresh_icon_preview(*_args: object) -> None:
        probe = DisplayProfile(
            icon=copy.deepcopy(draft.icon),
            tooltip=copy.deepcopy(draft.tooltip),
            details=copy.deepcopy(draft.details),
        )
        apply_layout_to_icon(probe.icon)
        probe.icon.slots = collect_icon_slots()
        probe.icon.color_by = color_by_var.get() or "percent"
        image = render_icon(probe, snapshot).resize((72, 72))
        photo = ImageTk.PhotoImage(image)
        _preview_photo[0] = photo
        preview_label.configure(image=photo)

    def apply_preset(_event: object | None = None) -> None:
        name = preset_var.get()
        personal = "claude-personal.session"
        week = "claude-personal.week"
        # Icon % uses Cursor's usage gauge only — never Monthly $ as a %.
        cursor_pct = (
            "cursor-main.overall" if "cursor-main.overall" in live_refs else ""
        )
        cursor_dollars = (
            "cursor-main.included" if "cursor-main.included" in live_refs else ""
        )
        if name == "Session %":
            layout_var.set("single")
            icon_slots[0]["ref"].set(label_by_ref.get(personal, personal))
            icon_slots[0]["show"].set("percent")
            tip_slots.clear()
            tip_slots.extend(
                [
                    DisplaySlot(ref=personal, show="percent_and_reset", label="Session"),
                    DisplaySlot(ref=week, show="percent", label="Week"),
                ]
            )
        elif name == "Session % + reset":
            layout_var.set("single")
            icon_slots[0]["ref"].set(label_by_ref.get(personal, personal))
            icon_slots[0]["show"].set("percent_and_reset")
            tip_slots.clear()
            tip_slots.append(
                DisplaySlot(ref=personal, show="percent_and_reset", label="Session")
            )
        elif name == "Week %":
            layout_var.set("single")
            icon_slots[0]["ref"].set(label_by_ref.get(week, week))
            icon_slots[0]["show"].set("percent")
            tip_slots.clear()
            tip_slots.append(DisplaySlot(ref=week, show="percent", label="Week"))
        elif name == "Reset countdown only":
            layout_var.set("single")
            icon_slots[0]["ref"].set(label_by_ref.get(personal, personal))
            icon_slots[0]["show"].set("reset")
            tip_slots.clear()
            tip_slots.append(DisplaySlot(ref=personal, show="reset", label="Reset"))
        elif name == "Claude + Cursor split":
            if personal not in available_refs or not cursor_pct:
                messagebox.showinfo(
                    "Display options",
                    "Enable Claude Personal and Cursor (with Overall usage) first.",
                    parent=win,
                )
                preset_var.set("(choose)")
                return
            layout_var.set("split")
            icon_slots[0]["ref"].set(label_by_ref.get(personal, personal))
            icon_slots[0]["show"].set("percent")
            icon_slots[0]["label"].set("P")
            icon_slots[1]["ref"].set(label_by_ref.get(cursor_pct, cursor_pct))
            icon_slots[1]["show"].set("percent")
            icon_slots[1]["label"].set("C")
            tip_slots.clear()
            tip_slots.append(
                DisplaySlot(ref=personal, show="percent_and_reset", label="Session")
            )
            tip_slots.append(
                DisplaySlot(ref=cursor_pct, show="percent", label="Cursor")
            )
            if cursor_dollars:
                tip_slots.append(
                    DisplaySlot(
                        ref=cursor_dollars, show="used_of_limit", label="Cursor $"
                    )
                )
        else:
            return
        sync_layout_ui()
        refresh_tip_list()

    preset_box.bind("<<ComboboxSelected>>", apply_preset)
    layout_var.trace_add("write", sync_layout_ui)
    color_by_var.trace_add("write", refresh_icon_preview)
    for row in icon_slots:
        row["ref"].trace_add("write", refresh_icon_preview)  # type: ignore[union-attr]
        row["show"].trace_add("write", refresh_icon_preview)  # type: ignore[union-attr]
        row["label"].trace_add("write", refresh_icon_preview)  # type: ignore[union-attr]

    def close() -> None:
        global _window
        _window = None
        win.destroy()

    def persist(*, close_after: bool) -> None:
        slots = collect_icon_slots()
        if not slots:
            messagebox.showerror("Display options", "Icon needs at least one metric.", parent=win)
            return
        cfg, _ = get_state()
        cfg = copy.deepcopy(cfg)
        profile = get_active_profile(cfg)
        apply_layout_to_icon(profile.icon)
        profile.icon.slots = slots
        if layout_var.get() == "rotate":
            profile.icon.max_slots = max(1, len(slots))
        profile.tooltip = TooltipDisplay(
            format=draft.tooltip.format,
            max_chars=draft.tooltip.max_chars,
            slots=[copy.deepcopy(s) for s in tip_slots],
        )
        profile.icon.color_by = color_by_var.get() or "percent"
        profile.icon.thresholds = dict(draft.icon.thresholds)
        profile.icon.show_labels = draft.icon.show_labels
        profile.icon.rotate_seconds = draft.icon.rotate_seconds
        try:
            on_save(cfg)
        except Exception as error:
            messagebox.showerror("Display options", f"Couldn't save:\n{error}", parent=win)
            return
        draft.icon.color_by = profile.icon.color_by
        refresh_icon_preview()
        update_preview()
        if close_after:
            close()

    action = tk.Frame(win)
    action.pack(fill=tk.X, padx=12, pady=10)
    tk.Button(action, text="Cancel", width=10, command=close).pack(side=tk.RIGHT, padx=4)
    tk.Button(
        action, text="Save", width=10, command=lambda: persist(close_after=True)
    ).pack(side=tk.RIGHT, padx=4)
    tk.Button(
        action, text="Apply", width=10, command=lambda: persist(close_after=False)
    ).pack(side=tk.RIGHT, padx=4)

    win.protocol("WM_DELETE_WINDOW", close)
    sync_layout_ui()
    refresh_tip_list()
    win.lift()
    win.focus_force()
