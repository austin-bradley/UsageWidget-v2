# Usage Widget v2

Windows system-tray usage widget for **Claude** (solid), plus best-effort **Cursor / GPT / Gemini** plugins. Multi-account, hybrid auth, configurable icon/tooltip slots and display profiles.

Prototype — no formal test suite. Manual smoke is enough.

## Run from source

```powershell
cd C:\Users\austi\UsageWidget-v2
pip install -r requirements.txt
python widget.py
```

On first run, config is seeded to `%APPDATA%\UsageWidget\config.yaml` from `config.example.yaml`. Only **Claude Personal** is enabled in the example; if Cursor/GPT/Gemini local login is already discoverable, those accounts are flipped on automatically at seed time. Use tray **Reload config** after editing the YAML.

## Build exe

```powershell
pip install pyinstaller
python -m PyInstaller UsageWidget-v2.spec
```

Output: `dist\UsageWidget-v2.exe` (windowed, no console). The example config is bundled and copied on first run via PyInstaller’s `_MEIPASS`.

## Two Claude accounts

Edit `%APPDATA%\UsageWidget\config.yaml`. Each account is a separate poll target:

```yaml
accounts:
  - id: claude-personal
    provider: claude
    label: Claude Personal
    enabled: true
    auth:
      mode: auto

  - id: claude-work
    provider: claude
    label: Claude Work
    enabled: true   # was false in the first-run example — turn on when ready
    auth:
      mode: token_file
      token_file: ~/.claude-work/.credentials.json
      claude_home: ~/.claude-work
```

Point `claude_home` / `token_file` at a second Claude config root so personal and work stay isolated. Or toggle accounts from the tray **Accounts** menu.

## Hybrid auth

Per account, each poll:

1. Use explicit `api_key`, `token_file`, or provider paths if set
2. Else auto-discover local login for that provider
3. Else mark `logged_in=false` with an error — other accounts keep updating

Modes: `auto` | `api_key` | `token_file`. Secrets stay in credential files / paths you set — never baked into the exe.

## Display slots and profiles

Slots reference `account_id.metric_id`. Value modes:

| `show` | Example |
|--------|---------|
| `percent` | `42` |
| `remaining_pct` | `58` |
| `reset` | `2h14m` (icon uses compact `2h`) |
| `percent_and_reset` | `42·2h` |
| `used_of_limit` | `$12/$20` |

Icon layouts: `primary_only` / `split` / `stacked_bars` / `badge_grid`. `color_by`: `percent` | `remaining_pct` | `none`.

```yaml
active_profile: default
profiles:
  default:
    icon:
      mode: composite   # composite | single | rotate
      slots:
        - ref: claude-personal.session
          show: percent_and_reset
          label: P
        - ref: claude-work.session
          show: percent_and_reset
          label: W
    tooltip:
      slots:
        - ref: claude-personal.session
          show: percent_and_reset
```

Switch profiles from the tray menu (**Display profile**). Enable/disable accounts under **Accounts**.

## Cursor / GPT / Gemini (best-effort)

These providers share the same plugin interface but are **prototype / best-effort**:

- **Cursor** — may need Cursor desktop login / local state DB access
- **GPT** — looks for Codex/ChatGPT-style local auth (e.g. `~/.codex/auth.json`)
- **Gemini** — Gemini CLI / Google ADC style quotas when available

If auth or endpoints aren’t ready, the account degrades to a clear error and does **not** kill the tray. Claude multi-account is the primary path.

## Tray menu

Show details · Refresh now · Display profile · Accounts · Always visible · Open config · Quit

## Extending providers

Add `providers/<name>.py`, register in `providers/registry.py`, add a YAML account entry. No tray rewrite.

## Notes

- Leaves v1 `ClaudeUsageWidget` / `ClaudeUsage.exe` untouched
- Config path: `%APPDATA%\UsageWidget\config.yaml`
- One failing provider must not blank the others (last-good metrics when possible)
