# Final fix report — Important #1 / #2

Date: 2026-07-17

## Important #1 — Per-account last-good metrics

**Problem:** Tray only kept the prior snapshot on total `fetch_all` failure. A single account error returned `metrics=[]`, so that account’s slots showed `?`.

**Fix:**
- Added `merge_last_good(previous, new)` in `core/poller.py`.
- On account `error` with prior metrics for the same `account_id`, retain previous `metrics`, `logged_in`, and `plan`; keep the new `error` string.
- Successful accounts replace normally; new accounts with no prior state stay as-is.
- `UsageTray._refresh_once` merges after each successful poll; total fetch failure still keeps the prior snapshot.

## Important #2 — save_config clobbering hand-edited YAML

**Problem:** Tray toggles called full `save_config` → `safe_dump` of rebuilt dataclasses, expanding `~` and rewriting display sections (comments still lost with PyYAML).

**Fix (no new dependency):**
- `AuthConfig` keeps `token_file_raw` / `claude_home_raw` from load; runtime fields stay expanded; `_auth_to_dict` writes raw tokens when present.
- Tray profile/account toggles use `patch_config_toggles`, which loads on-disk YAML, patches only `active_profile` and account `enabled`, and writes back — preserving `~` paths and existing display structure.
- Documented in `save_config` docstring: comments are not preserved under PyYAML.

## Smoke

Unit-style smoke (no full tray UI):
- `merge_last_good` retains metrics + plan + logged_in on failed account; success updates; new failed account unchanged.
- Mocked `UsageTray._refresh_once` applies merge.
- Raw path round-trip and `patch_config_toggles` keep `~/.claude-work…` and display slots.
