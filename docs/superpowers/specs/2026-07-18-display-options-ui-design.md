# Display Options UI + Details Singleton — Design Spec

**Status:** Draft for review (2026-07-18)  
**Parent:** `2026-07-17-usage-widget-v2-design.md`  
**Revises:** Parent non-goal “Polished settings UI (config file + tray menu is enough)” — YAML remains source of truth; a lightweight Display Options UI is now in scope.

## Problem

1. **Tray icon is hard to read** — Windows draws ~16–24px from a 64×64 bitmap. Split layouts with `percent_and_reset` compress to noise (e.g. `0·…` + `27`).
2. **Configuration is YAML-only** — slots/profiles already exist, but day-to-day changes need a file editor + Reload.
3. **Details stacks MessageBoxes** — each “Show details” spawns a new modal thread; nothing focuses or replaces an existing dialog.

## Goals

1. **Readable default icon** — prefer one large primary value (session %) with color ring; split only when the user opts in.
2. **Display Options modal** — quick UI to edit the active profile’s **icon** and **tooltip** slots; save to `%APPDATA%\UsageWidget\config.yaml`.
3. **Tooltip DnD configurator** — reorder / add / remove tooltip rows in the modal; applied on **Save → refresh** (restart not required).
4. **Both paths** — tray presets + modal for common edits; full YAML still works via Open config / Reload.
5. **Single details dialog** — at most one details window; repeat open focuses / replaces content.

## Non-goals (this change)

- Second tray icon / dual taskbar glyph (possible later; not in this slice)
- Live drag-and-drop on the OS hover tooltip itself (unsupported by Windows tooltips)
- Full visual page builder / multi-column flyout
- Replacing pystray or rewriting the poller
- Formal automated UI tests

## Approaches considered

| Approach | Pros | Cons |
|----------|------|------|
| Tray presets only | Tiny | Can’t pick exact metric rows |
| **Tkinter Display Options modal (chosen)** | Ships with Python; no new deps; enough for lists + DnD; works in frozen exe if bundled | Looks basic; must run UI on a dedicated thread carefully |
| Custom hover flyout with live DnD | Richer hover | Large scope; hover + DnD UX is fiddly on tray |

**Chosen:** Tkinter modal with Icon + Tooltip tabs, presets, Save writes YAML; tray refresh applies.

## UX

### Entry points

- Tray menu: **Display options…** (near Display profile)
- Optional: Settings → Display options
- Existing **Display profile** submenu kept for switching named profiles

### Modal: Display options

**Window:** single instance (if already open → focus; don’t spawn another).

**Presets** (top): apply a named template to the *draft* (not saved until Save):

- Session % (big icon)
- Session % + reset (icon `percent_and_reset`)
- Week %
- Claude session + Cursor % (split) — only if those accounts exist/enabled
- Reset countdown only

**Tab — Icon**

- Layout: `single` (primary_only) | `split` (max 2)
- Slot rows (1 or 2): metric ref (`account_id.metric_id`), show mode, optional short label
- Metric picker: dropdown of known refs from last snapshot + enabled account configs (even if last poll missed a meter)
- Show modes: `percent` | `remaining_pct` | `reset` | `percent_and_reset` | `used_of_limit`
- Hint text: “Tray icons are tiny — prefer one large number.”

**Tab — Tooltip**

- Ordered list of slots (DnD reorder)
- Each row: ref, show mode, optional label
- **Add** from pool of available metrics; **Remove** selected
- Format: `compact` (· joined) vs `lines` (if we keep lines; Windows tooltips often flatten newlines — document limitation)
- Live preview string (truncated to `max_chars`, default 127)

**Actions**

- **Save** — write active profile’s `icon` + `tooltip` into config.yaml (preserve accounts, details, other profiles); trigger config reload + refresh
- **Cancel** / close — discard draft
- No auto-save on DnD

### Apply timing

Per product choice: changes apply on **next refresh after Save**. Implementation should call the same path as **Reload config** + **Refresh now** so users don’t need a process restart. Restart also picks up the file (YAML is source of truth).

### Default profile tweak (example + first-run)

When seeding / documenting defaults:

- Icon: `mode: single`, `layout: primary_only`, one slot `claude-personal.session` / `show: percent` (large digit)
- Tooltip: session `percent_and_reset`, week `percent`, plus other enabled accounts as available

Existing user configs are **not** forcibly rewritten on upgrade; only example + Reset-to-example change.

## Details dialog singleton

Replace fire-and-forget `MessageBox` threads with a single-owner pattern:

1. Prefer a small **Tkinter details window** (read-only `Text` + OK) owned by one thread/loop, **or** Win32: find existing dialog by title and `SetForegroundWindow` + update (MessageBox text is not updatable — so Tkinter details is cleaner).
2. Second “Show details” while open → bring to front and replace body text with latest `build_details(...)`.
3. About / confirm dialogs may stay MessageBox (short-lived).

## Architecture

```
tray/app.py              # menu items; single-instance gates for options + details
tray/display_options.py  # Tkinter Display Options modal (new)
tray/details_window.py   # Tkinter details singleton (new; or combined module)
core/config.py           # save_profile_display(active) helper if needed
display/*                # unchanged render contract; maybe slightly larger fonts for single mode
```

Frozen exe: ensure Tk data files are available (PyInstaller often needs `collect_all('tkinter')` / similar). Verify in `UsageWidget-v2.spec`.

### Config write rules

- Only mutate `profiles[active_profile].icon` and `.tooltip` (and optionally `active_profile` if preset implies profile switch — **no**: presets edit current profile draft only).
- Preserve comments if possible is **nice-to-have**; `save_config` today rewrites YAML — acceptable for prototype (same as Reset/toggles).
- Validate refs loosely: allow saving a ref whose metric isn’t in the latest snapshot (shows after next successful poll).

### Threading

- pystray runs its own loop; Tk must not block it.
- Pattern: dedicated daemon thread with `tk.Tk` mainloop for UI windows, or one shared UI thread for Options + Details.
- Marshal Save → tray via a thread-safe callback (`reload_config` + `refresh_async`).

## Second tray icon (deferred)

Documented as future option: second `pystray.Icon` for a second permanent glyph. Out of scope here; tooltip richness + single big icon is the readability fix for this slice.

## Risks

| Risk | Mitigation |
|------|------------|
| Tk missing / broken in frozen exe | Spec update + smoke launch of Display options from packaged exe |
| DnD awkward in plain Tk | Use `Listbox` + Up/Down buttons as fallback if pure DnD is flaky; prefer both |
| Users expect live hover DnD | Copy in modal: “Drag here to set hover contents; Save applies on refresh” |
| YAML comment loss on Save | Accept for prototype; document |

## Success criteria

1. Default / recommended icon shows one large readable percentage in the tray.
2. User can open Display options, DnD-reorder tooltip rows, Save, and see new tooltip after refresh without restarting the process.
3. Icon tab can switch single vs split and choose which metrics without editing YAML by hand.
4. Presets + YAML Reload both still work.
5. Spamming Show details never stacks multiple detail windows.
6. Packaged `UsageWidget-v2.exe` can open the modal.

## Open points (resolve during implementation if needed)

- Exact DnD widget (`tkinter.dnd` vs buttons-only + optional drag) — ship Up/Down + drag if easy.
- Whether Details moves fully off MessageBox in the same PR (yes, preferred for singleton).
