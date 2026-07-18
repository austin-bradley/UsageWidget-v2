# Display Options UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Tkinter Display Options modal (icon + DnD tooltip slots, presets, Save→YAML→refresh), a single-instance details window, and a more readable default icon — without new pip dependencies.

**Architecture:** Keep YAML as source of truth. New `tray/ui_thread.py` owns one Tk mainloop; `tray/details_window.py` and `tray/display_options.py` open windows on that thread. `UsageTray` exposes thread-safe callbacks to reload config + refresh. `patch_config_profile_display` updates only the active profile’s icon/tooltip in the on-disk YAML (same spirit as `patch_config_toggles`).

**Tech Stack:** Python 3.12, tkinter (stdlib), pystray, Pillow, PyYAML, PyInstaller on Windows.

## Global Constraints

- Prototype: no formal pytest suite; manual smoke is enough
- No new pip dependencies (tkinter only)
- Config path: `%APPDATA%\UsageWidget\config.yaml`
- Do not forcibly migrate existing user configs; update `config.example.yaml` defaults
- Frozen exe must open Display options (bundle Tk in spec)
- Details and Display options are each single-instance (focus if already open)
- Save applies via reload + refresh (restart not required)
- Second tray icon is out of scope

---

### Task 1: Config helpers + available metric refs

**Files:**
- Modify: `core/config.py`
- Create: `display/available_metrics.py`
- Modify: `config.example.yaml` (readable default icon)

**Interfaces:**
- Produces: `patch_config_profile_display(cfg, path=None) -> None`
- Produces: `list_available_metric_refs(config: AppConfig, snapshot: AppSnapshot) -> list[tuple[str, str]]`  
  (ref, human label) e.g. `("claude-personal.session", "Claude Personal · Session")`
- Produces: known show modes constant `SHOW_MODES = ("percent", "remaining_pct", "reset", "percent_and_reset", "used_of_limit")`

- [ ] **Step 1: Add `patch_config_profile_display`**

Load YAML like `patch_config_toggles`. Locate `profiles[cfg.active_profile]`. Replace only `icon` and `tooltip` keys using `_icon_to_dict` / `_tooltip_to_dict` from the in-memory active profile. Write YAML back. If profile missing on disk, create it from dataclass.

```python
def patch_config_profile_display(cfg: AppConfig, path: Path | None = None) -> None:
    path = path or config_path()
    if not path.exists():
        save_config(cfg, path)
        return
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    profiles = data.setdefault("profiles", {})
    name = cfg.active_profile
    profile = cfg.profiles.get(name)
    if profile is None:
        return
    entry = profiles.get(name) if isinstance(profiles.get(name), dict) else {}
    entry["icon"] = _icon_to_dict(profile.icon)
    entry["tooltip"] = _tooltip_to_dict(profile.tooltip)
    if "details" not in entry:
        entry["details"] = _details_to_dict(profile.details)
    profiles[name] = entry
    data["active_profile"] = cfg.active_profile
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
```

- [ ] **Step 2: Add `display/available_metrics.py`**

Build refs from: (1) metrics present in snapshot for enabled accounts; (2) fallback common ids per provider (`session`, `week`, `fable_week`, `included`, …) for enabled accounts so the picker isn’t empty before first poll.

- [ ] **Step 3: Update `config.example.yaml` default profile**

Icon: `mode: single`, `layout: primary_only`, one slot `claude-personal.session` / `show: percent`.  
Tooltip: session `percent_and_reset`, week `percent`.

- [ ] **Step 4: Smoke**

```powershell
python -c "from core.config import load_config, patch_config_profile_display; from display.available_metrics import list_available_metric_refs; c=load_config(); print(list_available_metric_refs(c, __import__('core.models',fromlist=['AppSnapshot']).AppSnapshot(__import__('datetime').datetime.now(), []))[:5])"
```

- [ ] **Step 5: Commit**

```bash
git add core/config.py display/available_metrics.py config.example.yaml
git commit -m "Add profile display patch helper and available metric refs."
```

---

### Task 2: Shared Tk UI thread + details singleton

**Files:**
- Create: `tray/ui_thread.py`
- Create: `tray/details_window.py`
- Modify: `tray/app.py` (`_on_details`, remove MessageBox path for details)

**Interfaces:**
- Produces: `ui_thread.call(fn, *args, **kwargs)` — schedule callable on Tk thread
- Produces: `ui_thread.ensure_started()`
- Produces: `show_details(app_name: str, text: str) -> None` — open or update singleton

- [ ] **Step 1: Implement `tray/ui_thread.py`**

Daemon thread: create `tk.Tk()`, withdraw root, `mainloop`. Queue of callables drained via `root.after(100, ...)`. `call()` puts work on the queue.

- [ ] **Step 2: Implement `tray/details_window.py`**

Toplevel with scrolled `Text` (read-only), OK button. Module-level `_window`. If exists and alive: `deiconify`, `lift`, replace text. Else create. Title = app_name.

- [ ] **Step 3: Wire `UsageTray._on_details`**

Build text as today; `show_details(self.config.app_name, text)` instead of MessageBox thread.

- [ ] **Step 4: Manual smoke**

Run `python widget.py`, open Show details twice — one window, content updates / focuses.

- [ ] **Step 5: Commit**

```bash
git add tray/ui_thread.py tray/details_window.py tray/app.py
git commit -m "Use a singleton Tk details window instead of stacking MessageBoxes."
```

---

### Task 3: Display Options modal

**Files:**
- Create: `tray/display_options.py`
- Modify: `tray/app.py` (menu item + save callback)

**Interfaces:**
- Consumes: `patch_config_profile_display`, `list_available_metric_refs`, `SHOW_MODES`, `build_tooltip`, `get_active_profile`
- Produces: `open_display_options(*, get_state, on_save) -> None`
  - `get_state()` → `(AppConfig, AppSnapshot)` under lock-friendly copy
  - `on_save(AppConfig)` → tray patches file, `load_config`, refresh

**UI behavior:**
- Single instance Toplevel
- Presets combobox → fills draft icon/tooltip
- Tab Icon: layout radio (single/split); 1–2 slot editors (ref combobox, show combobox, label entry)
- Tab Tooltip: Listbox of slot summaries; Up/Down/Remove; Add row dialog; optional drag via listbox drag reorder if straightforward, else Up/Down is enough (spec allows both)
- Preview label using `build_tooltip` on draft profile + current snapshot
- Save: mutate `cfg.profiles[active]` icon/tooltip from draft → `on_save(cfg)`; Cancel destroys window

- [ ] **Step 1: Implement modal + presets**

Presets at minimum:
- `session_pct` — single icon session percent; tooltip session percent_and_reset + week percent
- `session_reset` — icon percent_and_reset
- `week_pct` — icon week percent
- `claude_cursor_split` — split personal session + cursor included (if refs exist)

- [ ] **Step 2: Wire menu**

Top-level or Settings: **Display options…** → `open_display_options(...)`.

`on_save`:
```python
def _on_display_options_save(self, cfg: AppConfig):
    from core.config import patch_config_profile_display, load_config
    patch_config_profile_display(cfg)
    self.config = load_config()
    self.refresh_async()
```

- [ ] **Step 3: Manual smoke**

Open Display options, change tooltip order, Save, hover tray — tooltip matches after refresh. Change icon to single session %, confirm large digit.

- [ ] **Step 4: Commit**

```bash
git add tray/display_options.py tray/app.py
git commit -m "Add Display Options modal for icon and tooltip slots."
```

---

### Task 4: Icon readability pass + packaging + docs

**Files:**
- Modify: `display/icon.py` (slightly larger single-mode start font if needed; keep 64×64)
- Modify: `UsageWidget-v2.spec` (collect tkinter)
- Modify: `README.md`
- Modify: user config optionally via note only (do not auto-overwrite)

- [ ] **Step 1: Icon**

For `single` / `primary_only` / rotate with one value: start_size 40–44, status ring; avoid `percent_and_reset` in example default.

- [ ] **Step 2: PyInstaller**

```python
from PyInstaller.utils.hooks import collect_all
datas, binaries, hiddenimports = collect_all('tkinter')
# merge into Analysis
```

Or equivalent that works on this machine — verify `import tkinter` inside frozen run.

- [ ] **Step 3: README**

Document Display options, details singleton, Save→refresh; note YAML still works.

- [ ] **Step 4: Build + smoke exe**

```powershell
.\scripts\build.ps1
Start-Process .\dist\UsageWidget-v2.exe
# Open Display options + Show details twice
```

- [ ] **Step 5: Commit**

```bash
git add display/icon.py UsageWidget-v2.spec README.md
git commit -m "Bundle Tk for Display options and document the UI."
```

---

## Spec coverage check

| Spec requirement | Task |
|------------------|------|
| Readable default icon | 1, 4 |
| Display Options modal | 3 |
| Tooltip DnD / reorder | 3 (Up/Down + drag if easy) |
| Presets + YAML | 3, 1 |
| Save → refresh | 3 |
| Details singleton | 2 |
| Tk in frozen exe | 4 |
| No second tray icon | deferred (non-goal) |

## Placeholder scan

None intentional. DnD: Up/Down required; listbox drag optional enhancement inside Task 3.
