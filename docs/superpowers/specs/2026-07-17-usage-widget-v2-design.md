# Usage Widget v2 — Design Spec

**Status:** Approved for prototype (design discussion 2026-07-17)  
**Source:** Copy of `ClaudeUsageWidget` v1 (Claude-only tray)  
**Goal:** Model-agnostic system tray usage widget — multi-provider, multi-account, configurable at-a-glance display.

## Product intent

Keep v1’s tray feel (pystray icon, tooltip, details popup, Always visible toggle) but:

1. Support **Claude, Cursor, GPT (ChatGPT/Codex), Gemini** subscription-style quotas
2. Make adding providers a **plugin drop-in**
3. Support **multiple accounts of the same provider** (e.g. two Claude logins)
4. Use **hybrid auth**: auto-discover local logins first; allow API key / token file override
5. Make **display fully configurable** — including reset countdown as a first-class value, not only %

**Prototype priority:** Ship a working tray quickly. Skip formal test suite / CI fixtures for now. Manual smoke-check is enough.

## Non-goals (prototype)

- Comprehensive automated tests
- Polished settings UI (config file + tray menu is enough)
- API billing / dollar-spend providers (can come later as separate provider plugins)
- Changing or breaking v1 (`ClaudeUsage.exe` stays as-is)

## Architecture (Approach 2)

Provider plugin protocol + account instances. Core tray/display code only speaks shared models.

```
UsageWidget-v2/
  widget.py                 # entrypoint
  config.example.yaml
  core/
    models.py
    config.py
    poller.py
  providers/
    base.py
    registry.py
    claude.py
    cursor.py
    gpt.py
    gemini.py
  display/
    icon.py
    tooltip.py
    details.py
    profiles.py
  tray/
    app.py
    win_notify.py           # Always visible registry helpers from v1
  UsageWidget-v2.spec
  README.md
```

User config lives at `%APPDATA%\UsageWidget\config.yaml` (created from example on first run).

## Data model

```python
@dataclass(frozen=True)
class Metric:
    id: str                 # "session", "week", "fable_week", "api", "five_hour", ...
    label: str
    used_pct: int | None    # 0–100 when applicable
    used: float | None      # optional absolute
    limit: float | None
    unit: str | None        # "percent" | "usd" | "requests"
    resets_at: datetime | None
    extra: dict

@dataclass
class AccountSnapshot:
    account_id: str         # config id, e.g. "claude-personal"
    provider_id: str        # "claude" | "cursor" | "gpt" | "gemini"
    display_name: str
    logged_in: bool
    plan: str | None
    metrics: list[Metric]   # dynamic — whatever this poll returned
    error: str | None

@dataclass
class AppSnapshot:
    fetched_at: datetime
    accounts: list[AccountSnapshot]
```

**Rules**

- Account = unit of auth + polling (two Claudes = two instances).
- Metrics are dynamic. Claude may add an `api` meter when API usage is enabled — no fixed three-field schema.
- Display slots reference `account_id.metric_id`.
- One account failing must not blank the others; keep last-good metrics when possible.

## Providers & auth

```python
class Provider(Protocol):
    id: str

    def discover_accounts(self) -> list[DiscoveredAccount]: ...
    def fetch(self, account: AccountConfig) -> AccountSnapshot: ...
```

### Account config shape

```yaml
accounts:
  - id: claude-personal
    provider: claude
    label: "Claude Personal"
    enabled: true
    auth:
      mode: auto            # auto | api_key | token_file
      # api_key: "..."
      # token_file: "~/.claude-work/.credentials.json"
      # claude_home: "~/.claude-work"   # multi-account root override

  - id: claude-work
    provider: claude
    label: "Claude Work"
    enabled: true
    auth:
      mode: token_file
      token_file: "~/.claude-work/.credentials.json"

  - id: cursor-main
    provider: cursor
    auth: { mode: auto }

  - id: gpt-main
    provider: gpt
    auth: { mode: auto }

  - id: gemini-main
    provider: gemini
    auth: { mode: auto }
```

### Hybrid auth resolution (per account, each poll)

1. Explicit `api_key` / `token_file` / provider-specific paths if set
2. Else auto-discover for that provider
3. Else `logged_in=false` + error string; other accounts continue

### Day-one fetch strategies (subscription quotas)

| Provider | Auto-discover | Fetch |
|----------|---------------|--------|
| claude | Claude Desktop CLI + `~/.claude*`; alternate home/creds for account #2 | `claude -p "/usage"` — parse all meters present (session, week, fable, optional api) |
| cursor | Access token from Cursor `state.vscdb` | Cursor usage endpoints (included $ / request buckets) |
| gpt | `~/.codex/auth.json` | ChatGPT/Codex quota windows (5h + weekly) |
| gemini | Gemini CLI / Google ADC | Gemini CLI / Code Assist style daily quotas |

**Extending later:** add `providers/<name>.py`, register it, add an account entry. No tray rewrite.

**Prototype note:** Claude should work first and solidly (including 2 accounts). Cursor/GPT/Gemini can land as best-effort plugins that degrade to a clear “not configured / fetch failed” state if auth or endpoints aren’t ready yet — still behind the same interface so they don’t block the tray shell.

## Display (fully configurable)

### Slot value modes

Reset times are first-class, same importance as %.

```yaml
# shorthand: "claude-personal.session" → show: percent
- ref: claude-personal.session
  show: percent_and_reset   # percent | remaining_pct | reset | percent_and_reset | used_of_limit
  label: "P"                # optional short label
```

| `show` | Example |
|--------|---------|
| percent | `42` |
| remaining_pct | `58` |
| reset | `2h14m` |
| percent_and_reset | `42·2h` |
| used_of_limit | `$12/$20` |

### Icon / tooltip / details / profiles

```yaml
display:
  active_profile: workday
  profiles:
    workday:
      icon:
        mode: composite          # single | composite | rotate
        layout: split            # split | stacked_bars | badge_grid | primary_only
        max_slots: 3
        rotate_seconds: 8
        color_by: percent        # percent | remaining_pct | none
        thresholds: { warn: 60, critical: 85 }
        show_labels: false
        slots:
          - { ref: claude-personal.session, show: percent_and_reset, label: "P" }
          - { ref: claude-work.session, show: reset, label: "W" }
      tooltip:
        format: compact          # compact | lines
        max_chars: 127
        slots:
          - { ref: claude-personal.session, show: percent_and_reset }
          - { ref: claude-work.session, show: percent_and_reset }
          - { ref: cursor-main.included, show: used_of_limit }
      details:
        show: all_enabled_accounts
        group_by: account
        metric_order: as_returned
        always_include_resets: true
        show_errors: true
        show_plan: true
        show_fetched_at: true
    reset-watch:
      icon:
        mode: rotate
        slots:
          - { ref: claude-personal.session, show: reset }
          - { ref: claude-personal.session, show: percent }
```

**Defaults on first run:** discover accounts; enable what we find; seed icon with up to 2 primary session-like metrics using `percent_and_reset` so countdown isn’t invisible by default.

## Tray UX & polling

- System tray only (no always-on-top window) — same rationale as v1
- Menu: Show details, Refresh now, Display profile →, Accounts → (enable/disable), Always visible, Open config, Quit
- `poll_seconds: 60` default; optional per-account override later if needed
- Parallel fetch per account; stale-last-good on error
- Manual refresh forces immediate re-fetch

## Packaging

- Copy project to sibling folder or `UsageWidget-v2/` subtree; leave v1 sources/exe alone
- PyInstaller → `UsageWidget-v2.exe` (windowless)
- Secrets stay in existing provider credential files / optional `token_file` paths — never baked into the exe

## Prototype plan (fast path)

1. **Scaffold** — copy v1 into v2 layout; split models/config/tray/display shells; Claude provider extracted from current `widget.py`
2. **Config + multi-account Claude** — YAML accounts, hybrid auth, two Claude roots poll independently
3. **Display engine** — slot refs, value modes (especially `reset` / `percent_and_reset`), composite/split + single + rotate; profiles switchable from menu
4. **Stub/real plugins** — Cursor, GPT, Gemini behind the same protocol (best-effort fetch; clear errors if unavailable)
5. **Package** — spec/exe + short README (setup notes per provider)

No formal tests in this prototype track. Add tests later once the UX and provider seams feel right.

## Success criteria (prototype)

- Two Claude accounts can be configured and polled independently
- Icon slots can show %, reset countdown, or both
- Display is profile/slot driven from config (not hardcoded Claude keys)
- New provider = new module + registry + account entry
- v1 remains untouched and runnable side-by-side
