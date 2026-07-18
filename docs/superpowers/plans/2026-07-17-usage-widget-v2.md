# Usage Widget v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prototype a model-agnostic Windows system tray usage widget with plugin providers, multi-account support, and fully configurable display slots (including reset countdowns).

**Architecture:** Copy v1 into a sibling project. Core speaks only `Metric` / `AccountSnapshot` / `AppSnapshot`. Each provider is a plugin (`discover_accounts` + `fetch`). YAML config defines account instances and display profiles. Tray polls accounts in parallel and renders icon/tooltip/details from slots.

**Tech Stack:** Python 3.12, pystray, Pillow, PyYAML, PyInstaller (Windows). Reuse v1 patterns for hidden subprocess + Always-visible registry toggle.

## Global Constraints

- Prototype-first: **no formal test suite** — verify with manual smoke runs only.
- Leave v1 untouched at `C:\Users\austi\ClaudeUsageWidget` (including `dist\ClaudeUsage.exe`).
- Build v2 at sibling `C:\Users\austi\UsageWidget-v2`.
- Hybrid auth: auto-discover first; allow `api_key` / `token_file` overrides.
- Multi-account: multiple config entries can share a `provider` id (e.g. two Claudes).
- Metrics are dynamic (Claude may emit optional `api` meter).
- Display slots are first-class; `show: reset` and `percent_and_reset` required.
- Day-one providers: `claude`, `cursor`, `gpt`, `gemini` (Claude solid; others best-effort OK).
- User config path: `%APPDATA%\UsageWidget\config.yaml`.
- Subscription quotas only (not API billing dashboards) for GPT/Gemini/Cursor.

**Spec:** `docs/superpowers/specs/2026-07-17-usage-widget-v2-design.md` (in the v1 folder; copy into v2 `docs/` during scaffold).

---

## File structure (create in v2)

| Path | Responsibility |
|------|----------------|
| `widget.py` | Entrypoint only — load config, start tray |
| `core/models.py` | `Metric`, `AccountSnapshot`, `AppSnapshot`, config dataclasses |
| `core/config.py` | Load/save YAML, first-run seed, path helpers |
| `core/poller.py` | Parallel account fetch → `AppSnapshot` |
| `providers/base.py` | `Provider` protocol, `DiscoveredAccount`, auth helpers |
| `providers/registry.py` | Map provider id → implementation |
| `providers/claude.py` | Extracted/adapted from v1 `widget.py` |
| `providers/cursor.py` | Best-effort Cursor usage |
| `providers/gpt.py` | Best-effort Codex/ChatGPT quotas |
| `providers/gemini.py` | Best-effort Gemini CLI quotas |
| `display/format_value.py` | Slot `show` modes → short strings |
| `display/icon.py` | Render tray icon from slots |
| `display/tooltip.py` | Compact tooltip (≤127 chars) |
| `display/details.py` | Details popup text |
| `display/profiles.py` | Resolve active profile |
| `tray/win_notify.py` | Always-visible registry helpers (from v1) |
| `tray/app.py` | `UsageTray` — menu, poll loop, render |
| `config.example.yaml` | Documented defaults |
| `requirements.txt` | `pystray`, `Pillow`, `PyYAML` |
| `UsageWidget-v2.spec` | PyInstaller |
| `README.md` | Prototype setup notes |

---

### Task 1: Scaffold sibling v2 project

**Files:**
- Create: `C:\Users\austi\UsageWidget-v2\` (full tree of empty packages + copied assets)
- Copy: `icon.ico`, `make_icon.py`, `version_info.txt`, design/plan docs

**Interfaces:**
- Produces: runnable empty package layout; v1 unchanged

- [ ] **Step 1: Create sibling project and copy assets**

```powershell
$src = "C:\Users\austi\ClaudeUsageWidget"
$dst = "C:\Users\austi\UsageWidget-v2"
New-Item -ItemType Directory -Path $dst -Force | Out-Null
foreach ($d in @("core","providers","display","tray","docs\superpowers\specs","docs\superpowers\plans")) {
  New-Item -ItemType Directory -Path (Join-Path $dst $d) -Force | Out-Null
}
Copy-Item "$src\icon.ico","$src\make_icon.py","$src\version_info.txt" $dst
Copy-Item "$src\docs\superpowers\specs\*.md" "$dst\docs\superpowers\specs\"
Copy-Item "$src\docs\superpowers\plans\*.md" "$dst\docs\superpowers\plans\"
# Keep a reference copy of v1 widget for extraction
Copy-Item "$src\widget.py" "$dst\_v1_widget_reference.py"
```

- [ ] **Step 2: Add package markers and requirements**

Create empty `__init__.py` in `core`, `providers`, `display`, `tray`.

Create `requirements.txt`:

```text
pystray>=0.19.5
Pillow>=10.0.0
PyYAML>=6.0
```

Create stub `widget.py`:

```python
"""Usage Widget v2 entrypoint."""

def main():
    raise SystemExit("Usage Widget v2 scaffold — not wired yet")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Init git in v2 (optional but useful) and smoke**

```powershell
cd C:\Users\austi\UsageWidget-v2
git init
python -m pip install -r requirements.txt
python widget.py
```

Expected: exits with scaffold message.

- [ ] **Step 4: Move agent workspace to v2**

Use `move_agent_to_root` with `C:\Users\austi\UsageWidget-v2` before continuing implementation tasks.

---

### Task 2: Core models + config load/save

**Files:**
- Create: `core/models.py`, `core/config.py`, `config.example.yaml`

**Interfaces:**
- Produces:
  - `Metric`, `AccountSnapshot`, `AppSnapshot`
  - `AccountConfig`, `AuthConfig`, `DisplaySlot`, `DisplayProfile`, `AppConfig`
  - `load_config() -> AppConfig`, `save_config(cfg)`, `config_path() -> Path`
  - `ensure_config() -> AppConfig` (copy example / seed on first run)

- [ ] **Step 1: Implement `core/models.py`**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Metric:
    id: str
    label: str
    used_pct: int | None = None
    used: float | None = None
    limit: float | None = None
    unit: str | None = None
    resets_at: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class AccountSnapshot:
    account_id: str
    provider_id: str
    display_name: str
    logged_in: bool
    plan: str | None
    metrics: list[Metric]
    error: str | None = None


@dataclass
class AppSnapshot:
    fetched_at: datetime
    accounts: list[AccountSnapshot]


@dataclass
class AuthConfig:
    mode: str = "auto"  # auto | api_key | token_file
    api_key: str | None = None
    token_file: str | None = None
    claude_home: str | None = None  # multi-account override
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class AccountConfig:
    id: str
    provider: str
    label: str | None = None
    enabled: bool = True
    auth: AuthConfig = field(default_factory=AuthConfig)
    poll_seconds: int | None = None


@dataclass
class DisplaySlot:
    ref: str  # "account_id.metric_id"
    show: str = "percent"
    label: str | None = None


@dataclass
class IconDisplay:
    mode: str = "composite"
    layout: str = "split"
    max_slots: int = 3
    rotate_seconds: int = 8
    color_by: str = "percent"
    thresholds: dict[str, int] = field(default_factory=lambda: {"warn": 60, "critical": 85})
    show_labels: bool = False
    slots: list[DisplaySlot] = field(default_factory=list)


@dataclass
class TooltipDisplay:
    format: str = "compact"
    max_chars: int = 127
    slots: list[DisplaySlot] = field(default_factory=list)


@dataclass
class DetailsDisplay:
    show: str = "all_enabled_accounts"
    group_by: str = "account"
    metric_order: str = "as_returned"
    always_include_resets: bool = True
    show_errors: bool = True
    show_plan: bool = True
    show_fetched_at: bool = True


@dataclass
class DisplayProfile:
    icon: IconDisplay = field(default_factory=IconDisplay)
    tooltip: TooltipDisplay = field(default_factory=TooltipDisplay)
    details: DetailsDisplay = field(default_factory=DetailsDisplay)


@dataclass
class AppConfig:
    poll_seconds: int = 60
    app_name: str = "Usage Widget v2"
    accounts: list[AccountConfig] = field(default_factory=list)
    active_profile: str = "default"
    profiles: dict[str, DisplayProfile] = field(default_factory=dict)
```

- [ ] **Step 2: Implement `core/config.py`**

Key behaviors:
- `config_path()` → `Path(os.environ["APPDATA"]) / "UsageWidget" / "config.yaml"`
- `load_config()` parses YAML into dataclasses (nested dict → `AuthConfig`, slots as dict or string shorthand `"acct.metric"`)
- `ensure_config()`: if missing, write `config.example.yaml` contents (bundled next to exe or repo root) and return loaded config
- `save_config(cfg)` round-trips enabled flags / active_profile for tray menu toggles
- Expand `~` in `token_file` / `claude_home`

Slot parsing helper:

```python
def parse_slot(raw) -> DisplaySlot:
    if isinstance(raw, str):
        return DisplaySlot(ref=raw, show="percent")
    return DisplaySlot(
        ref=raw["ref"],
        show=raw.get("show", "percent"),
        label=raw.get("label"),
    )
```

- [ ] **Step 3: Write `config.example.yaml`**

Include two Claude account stubs, cursor/gpt/gemini stubs, and a `default` profile with `percent_and_reset` icon slots (see design spec §Display). Keep comments short.

- [ ] **Step 4: Manual smoke**

```powershell
cd C:\Users\austi\UsageWidget-v2
python -c "from core.config import ensure_config; c=ensure_config(); print(c.app_name, len(c.accounts), c.active_profile)"
```

Expected: prints app name, account count from example, `default`. Config file created under `%APPDATA%\UsageWidget\`.

---

### Task 3: Provider protocol + Claude provider (multi-account)

**Files:**
- Create: `providers/base.py`, `providers/registry.py`, `providers/claude.py`
- Reference: `_v1_widget_reference.py` (do not modify v1)

**Interfaces:**
- Consumes: `AccountConfig`, `AuthConfig`
- Produces:
  - `class Provider(Protocol): id; discover_accounts(); fetch(account) -> AccountSnapshot`
  - `get_provider(provider_id) -> Provider`
  - `ClaudeProvider` returning dynamic metrics including optional `api`

- [ ] **Step 1: Implement `providers/base.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from core.models import AccountConfig, AccountSnapshot


@dataclass
class DiscoveredAccount:
    suggested_id: str
    display_name: str
    auth_hints: dict  # e.g. {"claude_home": "..."} 


class Provider(Protocol):
    id: str

    def discover_accounts(self) -> list[DiscoveredAccount]: ...
    def fetch(self, account: AccountConfig) -> AccountSnapshot: ...


def resolve_auth_path(path: str | None) -> str | None:
    if not path:
        return None
    import os
    return os.path.expanduser(path)
```

- [ ] **Step 2: Port Claude fetch/parse into `providers/claude.py`**

Move from `_v1_widget_reference.py`:
- `find_claude_exe` / `get_claude_exe`
- regex meter parsing (`_meter_re`, session/week/fable)
- `_parse_reset`, account file readers

Adapt so meters are **dynamic**:

```python
# After getting usage text from CLI:
METER_PATTERNS = [
    ("session", "Session", r"Current session"),
    ("week", "Week (all models)", r"Current week \(all models\)"),
    ("fable_week", "Week (Fable)", r"Current week \(Fable\)"),
    ("api", "API", r"API(?: usage)?"),  # best-effort; adjust once real label known
]

metrics: list[Metric] = []
for mid, label, label_re in METER_PATTERNS:
    m = _meter_re(label_re).search(text)
    if not m:
        continue
    metrics.append(Metric(
        id=mid,
        label=label,
        used_pct=int(m.group(1)),
        unit="percent",
        resets_at=_parse_reset(m.group(2), m.group(3)) if m.group(2) else None,
    ))
```

**Multi-account:** if `account.auth.claude_home` or `token_file` set, point env / credential reads at that root. For prototype, support at least:
- Default account → current v1 paths (`~/.claude.json`, `~/.claude/.credentials.json`)
- Second account → `auth.claude_home` directory containing `.credentials.json` (and optional `claude.json`)

If Claude CLI cannot select profile via env, document prototype limitation: second account may need `token_file` + whatever env var the CLI respects; implement the cleanest working approach discovered during coding (spike ≤30 min). Prefer setting `CLAUDE_CONFIG_DIR` if supported.

`fetch` must never raise out of the provider — catch and return `AccountSnapshot(..., metrics=[], error=str(e), logged_in=False)`.

- [ ] **Step 3: Registry**

```python
# providers/registry.py
from providers.claude import ClaudeProvider
# cursor/gpt/gemini registered in Task 6

PROVIDERS = {
    "claude": ClaudeProvider(),
}

def get_provider(provider_id: str):
    try:
        return PROVIDERS[provider_id]
    except KeyError as e:
        raise KeyError(f"Unknown provider: {provider_id}") from e
```

- [ ] **Step 4: Manual smoke**

```powershell
python -c "
from core.models import AccountConfig, AuthConfig
from providers.claude import ClaudeProvider
p = ClaudeProvider()
print(p.discover_accounts())
snap = p.fetch(AccountConfig(id='claude-personal', provider='claude', label='Personal'))
print(snap.logged_in, snap.error, [(m.id, m.used_pct, m.resets_at) for m in snap.metrics])
"
```

Expected: discovers at least one account if Claude is installed; metrics list non-empty when logged in.

---

### Task 4: Poller

**Files:**
- Create: `core/poller.py`

**Interfaces:**
- Consumes: `AppConfig`, `get_provider`
- Produces: `fetch_all(config: AppConfig) -> AppSnapshot`

- [ ] **Step 1: Implement parallel fetch**

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from core.models import AppConfig, AppSnapshot, AccountSnapshot
from providers.registry import get_provider


def fetch_all(config: AppConfig) -> AppSnapshot:
    enabled = [a for a in config.accounts if a.enabled]
    accounts: list[AccountSnapshot] = []

    def one(acct):
        try:
            return get_provider(acct.provider).fetch(acct)
        except Exception as e:
            return AccountSnapshot(
                account_id=acct.id,
                provider_id=acct.provider,
                display_name=acct.label or acct.id,
                logged_in=False,
                plan=None,
                metrics=[],
                error=str(e),
            )

    if not enabled:
        return AppSnapshot(fetched_at=datetime.now(), accounts=[])

    with ThreadPoolExecutor(max_workers=min(8, len(enabled))) as pool:
        futs = {pool.submit(one, a): a for a in enabled}
        for fut in as_completed(futs):
            accounts.append(fut.result())

    # stable order matching config
    order = {a.id: i for i, a in enumerate(enabled)}
    accounts.sort(key=lambda s: order.get(s.account_id, 999))
    return AppSnapshot(fetched_at=datetime.now(), accounts=accounts)
```

- [ ] **Step 2: Manual smoke** — `fetch_all(ensure_config())` prints all account ids + metric counts.

---

### Task 5: Display engine (slots, reset-aware values, icon/tooltip/details)

**Files:**
- Create: `display/format_value.py`, `display/icon.py`, `display/tooltip.py`, `display/details.py`, `display/profiles.py`

**Interfaces:**
- Consumes: `AppSnapshot`, `DisplayProfile`
- Produces:
  - `resolve_metric(snapshot, ref) -> tuple[AccountSnapshot, Metric] | None`
  - `format_slot(slot, metric) -> str`
  - `render_icon(profile, snapshot, rotate_index=0) -> PIL.Image`
  - `build_tooltip(profile, snapshot) -> str`
  - `build_details(profile, snapshot) -> str`
  - `get_active_profile(config) -> DisplayProfile`

- [ ] **Step 1: `format_value.py` — countdown + show modes**

Port `_fmt_countdown` from v1. Implement:

```python
def format_slot(show: str, metric: Metric) -> str:
    pct = metric.used_pct
    cd = _fmt_countdown(metric.resets_at)
    if show == "percent":
        return "?" if pct is None else str(pct)
    if show == "remaining_pct":
        return "?" if pct is None else str(max(0, 100 - pct))
    if show == "reset":
        return cd
    if show == "percent_and_reset":
        p = "?" if pct is None else str(pct)
        return f"{p}·{cd}"
    if show == "used_of_limit":
        if metric.used is not None and metric.limit is not None:
            if metric.unit == "usd":
                return f"${metric.used:g}/${metric.limit:g}"
            return f"{metric.used:g}/{metric.limit:g}"
        return "?" if pct is None else f"{pct}%"
    return "?" if pct is None else str(pct)
```

Use exhaustive `if/elif` + final fallback (prototype; can tighten to `assert_never` later).

- [ ] **Step 2: `icon.py`**

Port `_find_font`, `_color_for_pct`, `render_icon` from v1; generalize:

- Resolve up to `max_slots` from `profile.icon.slots` against snapshot
- `mode=single` / `layout=primary_only`: one big value
- `mode=composite` + `layout=split`: two cells
- `mode=composite` + `layout=stacked_bars`: 2–3 horizontal bars using `used_pct`
- `mode=rotate`: pick `slots[rotate_index % len(slots)]`
- Color from `used_pct` vs thresholds (for `reset`-only slots, still color by pct if available else gray)

Keep 64×64 RGBA.

- [ ] **Step 3: `tooltip.py` / `details.py`**

- Tooltip: join configured slots as `Label value` pieces; truncate to `max_chars`
- Details: group by account; list all metrics with pct + countdown; include errors/plan/fetched_at per profile.details flags

- [ ] **Step 4: Manual smoke — write PNGs**

```powershell
python -c "
from display.icon import render_icon
from display.profiles import get_active_profile
from core.config import ensure_config
from core.poller import fetch_all
cfg = ensure_config()
snap = fetch_all(cfg)
prof = get_active_profile(cfg)
img = render_icon(prof, snap)
img.save('smoke_icon.png')
print('wrote smoke_icon.png')
"
```

Open `smoke_icon.png` and confirm readable values / colors.

---

### Task 6: Cursor / GPT / Gemini best-effort providers

**Files:**
- Create: `providers/cursor.py`, `providers/gpt.py`, `providers/gemini.py`
- Modify: `providers/registry.py`

**Interfaces:**
- Same `Provider` protocol
- On missing auth: snapshot with `error` explaining setup; never crash tray

- [ ] **Step 1: Cursor provider (best-effort)**

1. Read `cursorAuth/accessToken` from `%APPDATA%\Cursor\User\globalStorage\state.vscdb` (sqlite3, read-only)
2. Call Cursor usage endpoint(s) used by community tools (try current-period usage; fall back to `/auth/usage`)
3. Normalize to metrics: prefer `included` with `unit="usd"` or percent; set `resets_at` if present

If anything fails: return clear error string (`"Cursor token not found"` / `"Cursor usage API failed: ..."`).

- [ ] **Step 2: GPT provider (best-effort)**

1. Auto: read `~/.codex/auth.json`
2. Fetch ChatGPT/Codex quota (`five_hour`, `week`) via the same approach community CLIs use (Bearer from auth file)
3. Metrics: `five_hour`, `week` with `used_pct` + `resets_at`

- [ ] **Step 3: Gemini provider (best-effort)**

1. Try invoking Gemini CLI non-interactively for quota/stats if available on PATH
2. Else return error instructing user to install/login Gemini CLI or set `api_key` for a later path
3. If parse works: metric `daily` (and others if exposed)

- [ ] **Step 4: Register all four in `PROVIDERS`**

- [ ] **Step 5: Manual smoke** — fetch each provider once; Claude must work; others may error gracefully.

---

### Task 7: Tray app + entrypoint

**Files:**
- Create: `tray/win_notify.py`, `tray/app.py`
- Modify: `widget.py`

**Interfaces:**
- Produces: running tray icon with menu; parity with v1 interactions plus profiles/accounts

- [ ] **Step 1: Port Always-visible helpers to `tray/win_notify.py`** (unchanged logic from v1)

- [ ] **Step 2: Implement `tray/app.py`**

```python
class UsageTray:
    def __init__(self, config: AppConfig):
        self.config = config
        self.snapshot = AppSnapshot(fetched_at=datetime.now(), accounts=[])
        self._rotate_index = 0
        self._stop = False
        # build pystray.Icon with menu:
        # Show details (default), Refresh now, Display profile submenu,
        # Accounts submenu (checkbox enabled), Always visible, Open config, Quit
```

Behaviors:
- Poll loop: `fetch_all` every `config.poll_seconds`; on success replace snapshot; on total failure keep last snapshot
- Rotate timer: if icon.mode == `rotate`, increment `_rotate_index` every `rotate_seconds` and re-render
- Show details: `MessageBoxW` with `build_details(...)`
- Open config: `os.startfile(config_path())`
- Profile switch / account enable: update config + `save_config` + refresh
- Title/tooltip: `build_tooltip`
- Icon: `render_icon`

- [ ] **Step 3: Wire `widget.py`**

```python
from core.config import ensure_config
from tray.app import UsageTray

def main():
    cfg = ensure_config()
    UsageTray(cfg).run()

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Manual smoke (primary acceptance)**

```powershell
cd C:\Users\austi\UsageWidget-v2
python widget.py
```

Check:
- [ ] Tray icon appears
- [ ] Tooltip shows configured slots
- [ ] Details shows accounts/metrics/resets
- [ ] Refresh now works
- [ ] Two Claude accounts work if configured
- [ ] Always visible toggle still works
- [ ] Quit works

---

### Task 8: Packaging + README

**Files:**
- Create: `UsageWidget-v2.spec`, `README.md`
- Modify: `version_info.txt` product name → `Usage Widget v2`

- [ ] **Step 1: PyInstaller spec** (mirror v1 `ClaudeUsage.spec`, `console=False`, `name='UsageWidget-v2'`, include `config.example.yaml` as data)

```python
# datas=[('config.example.yaml', '.')],
```

Ensure `core.config` can find example when frozen (`sys._MEIPASS`).

- [ ] **Step 2: Build**

```powershell
pyinstaller UsageWidget-v2.spec
```

- [ ] **Step 3: README** — how to configure two Claude accounts, hybrid auth, display slots/profiles, note that Cursor/GPT/Gemini are best-effort in prototype.

- [ ] **Step 4: Final smoke on `dist\UsageWidget-v2.exe`**

---

## Manual verification checklist (prototype done)

- [ ] v1 `ClaudeUsage.exe` still present/unmodified in old folder
- [ ] v2 runs from source and from exe
- [ ] Config at `%APPDATA%\UsageWidget\config.yaml`
- [ ] Icon can show `percent`, `reset`, and `percent_and_reset`
- [ ] Multi-account Claude configurable
- [ ] Disabled account skipped; failed provider doesn’t kill tray
- [ ] Adding a provider only requires new module + registry + YAML account

---

## Self-review notes (plan vs spec)

| Spec requirement | Task |
|------------------|------|
| Plugin providers | 3, 6 |
| Hybrid auth + multi-account | 2, 3 |
| Dynamic metrics (incl. Claude API meter) | 3 |
| Configurable slots / reset first-class | 5 |
| Profiles | 5, 7 |
| Cursor/GPT/Gemini | 6 |
| Prototype, no formal tests | all (manual smoke only) |
| v1 untouched | 1 |

No automated test tasks by design (user request).
