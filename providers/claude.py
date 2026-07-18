from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from core.models import AccountConfig, AccountSnapshot, AuthConfig, Metric
from providers.base import (
    DiscoveredAccount,
    auth_mode,
    auth_preflight,
    resolve_auth_path,
)


METER_PATTERNS = [
    ("session", "Session", r"Current session"),
    ("week", "Week (all models)", r"Current week \(all models\)"),
    ("fable_week", "Week (Fable)", r"Current week \(Fable\)"),
    # Optional API meter — labels vary by CLI/plan; match common forms.
    ("api", "API", r"(?:Current\s+)?API(?:\s+usage)?(?:\s+limit)?"),
    ("api", "API", r"Extra usage"),
    ("api", "API", r"Pay-as-you-go"),
]


def _version_key(path: str) -> tuple[int, ...]:
    version = os.path.basename(os.path.dirname(path))
    parts = []
    for part in version.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def find_claude_exe() -> str | None:
    """Locate Claude Code, including Claude Desktop's virtualized install."""
    roots = []
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        roots.append(os.path.join(appdata, "Claude", "claude-code"))
    localappdata = os.environ.get("LOCALAPPDATA", "")
    if localappdata:
        roots.extend(
            glob.glob(
                os.path.join(
                    localappdata,
                    "Packages",
                    "Claude_*",
                    "LocalCache",
                    "Roaming",
                    "Claude",
                    "claude-code",
                )
            )
        )

    candidates = []
    for root in roots:
        candidates.extend(glob.glob(os.path.join(root, "*", "claude.exe")))
    if candidates:
        candidates.sort(key=_version_key, reverse=True)
        return candidates[0]
    return shutil.which("claude")


_claude_exe_cache = find_claude_exe()


def get_claude_exe() -> str | None:
    """Return the CLI path, re-resolving after Claude Desktop updates."""
    global _claude_exe_cache
    if _claude_exe_cache and os.path.exists(_claude_exe_cache):
        return _claude_exe_cache
    _claude_exe_cache = find_claude_exe()
    return _claude_exe_cache


def _meter_re(label: str) -> re.Pattern[str]:
    return re.compile(
        label
        + r":\s*(\d+)%\s*used"
        + r"(?:\s*·\s*resets\s*"
        + r"([A-Za-z]{3,9} \d{1,2},\s*\d{1,2}(?::\d{2})?\s*[ap]m)\s*\(([^)]+)\))?"
    )


def _parse_reset(date_str: str, tz_name: str) -> datetime | None:
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = None
    now = datetime.now(tz)
    for fmt in ("%b %d, %I:%M%p", "%b %d, %I%p"):
        try:
            reset_at = datetime.strptime(date_str, fmt)
            break
        except ValueError:
            continue
    else:
        return None
    reset_at = reset_at.replace(year=now.year)
    if tz is not None:
        reset_at = reset_at.replace(tzinfo=tz)
    if reset_at < now - timedelta(days=1):
        reset_at = reset_at.replace(year=now.year + 1)
    return reset_at


def _auth_paths(auth: AuthConfig) -> tuple[Path, Path, list[Path]]:
    claude_home = resolve_auth_path(auth.claude_home)
    token_file = resolve_auth_path(auth.token_file)
    environment_home = resolve_auth_path(os.environ.get("CLAUDE_CONFIG_DIR"))

    if token_file:
        credentials_path = Path(token_file)
        config_dir = Path(claude_home) if claude_home else credentials_path.parent
        expected_path = config_dir / ".credentials.json"
        if credentials_path.resolve() != expected_path.resolve():
            raise ValueError(
                "Claude token_file must be the .credentials.json file inside claude_home"
            )
    elif claude_home:
        config_dir = Path(claude_home)
        credentials_path = config_dir / ".credentials.json"
    elif environment_home:
        config_dir = Path(environment_home)
        credentials_path = config_dir / ".credentials.json"
    else:
        config_dir = Path.home() / ".claude"
        credentials_path = config_dir / ".credentials.json"

    if claude_home or token_file or environment_home:
        account_paths = [config_dir / "claude.json", config_dir / ".claude.json"]
    else:
        account_paths = [Path.home() / ".claude.json"]
    return config_dir, credentials_path, account_paths


def _read_account(auth: AuthConfig) -> dict[str, str | bool | None]:
    _, credentials_path, account_paths = _auth_paths(auth)
    info: dict[str, str | bool | None] = {
        "name": None,
        "email": None,
        "plan": None,
        "logged_in": False,
    }
    for account_path in account_paths:
        try:
            with account_path.open(encoding="utf-8") as file:
                account = (json.load(file) or {}).get("oauthAccount") or {}
            info["name"] = account.get("displayName")
            info["email"] = account.get("emailAddress")
            break
        except Exception:
            continue
    try:
        with credentials_path.open(encoding="utf-8") as file:
            oauth = (json.load(file) or {}).get("claudeAiOauth") or {}
        info["plan"] = oauth.get("subscriptionType")
        info["logged_in"] = bool(oauth.get("accessToken"))
    except Exception:
        pass
    return info


def _account_display_name(info: dict[str, str | bool | None]) -> str:
    name = info.get("name")
    email = info.get("email")
    if name and email:
        return f"{name} ({email})"
    return str(name or email or "Claude")


def _usage_environment(auth: AuthConfig) -> dict[str, str]:
    config_dir, credentials_path, _ = _auth_paths(auth)
    env = os.environ.copy()
    if auth.claude_home or auth.token_file:
        if auth.token_file and not credentials_path.is_file():
            raise FileNotFoundError(f"Claude token file not found: {credentials_path}")
        env["CLAUDE_CONFIG_DIR"] = str(config_dir)
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
    if auth.api_key:
        env["ANTHROPIC_API_KEY"] = auth.api_key
        env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
    return env


def _run_usage(claude_exe: str, auth: AuthConfig) -> str:
    run_kwargs: dict = {
        "capture_output": True,
        "encoding": "utf-8",
        "timeout": 20,
        "stdin": subprocess.DEVNULL,
        "env": _usage_environment(auth),
    }
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        run_kwargs["startupinfo"] = startupinfo

    proc = subprocess.run(
        [claude_exe, "-p", "/usage", "--output-format", "json"],
        **run_kwargs,
    )
    if not proc.stdout or not proc.stdout.strip():
        error = (proc.stderr or "").strip()
        raise RuntimeError(
            error or f"claude exited with code {proc.returncode} and no output"
        )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        snippet = (proc.stderr or proc.stdout or "").strip()[:300]
        raise RuntimeError(snippet or "Unexpected (non-JSON) output from claude")
    text = data.get("result", "")
    if not isinstance(text, str):
        raise RuntimeError("Claude usage response did not contain text")
    if "not logged in" in text.lower():
        raise RuntimeError("Not logged in to Claude Code")
    return text


def _parse_metrics(text: str) -> list[Metric]:
    metrics = []
    seen_ids: set[str] = set()
    for metric_id, label, label_re in METER_PATTERNS:
        if metric_id in seen_ids:
            continue
        match = _meter_re(label_re).search(text)
        if not match:
            continue
        seen_ids.add(metric_id)
        metrics.append(
            Metric(
                id=metric_id,
                label=label,
                used_pct=int(match.group(1)),
                unit="percent",
                resets_at=(
                    _parse_reset(match.group(2), match.group(3))
                    if match.group(2)
                    else None
                ),
            )
        )
    return metrics


class ClaudeProvider:
    id = "claude"

    def discover_accounts(self) -> list[DiscoveredAccount]:
        auth = AuthConfig()
        _, credentials_path, account_paths = _auth_paths(auth)
        if not get_claude_exe() and not credentials_path.exists() and not any(
            path.exists() for path in account_paths
        ):
            return []
        info = _read_account(auth)
        return [
            DiscoveredAccount(
                suggested_id="claude-personal",
                display_name=_account_display_name(info),
                auth_hints={},
            )
        ]

    def fetch(self, account: AccountConfig) -> AccountSnapshot:
        info: dict[str, str | bool | None] = {}
        try:
            preflight = auth_preflight(account.auth)
            if preflight:
                raise RuntimeError(preflight)
            if auth_mode(account.auth) == "api_key":
                raise RuntimeError(
                    "Claude subscription usage uses the CLI login; "
                    "set auth.mode to auto or token_file"
                )
            info = _read_account(account.auth)
            claude_exe = get_claude_exe()
            if not claude_exe:
                raise RuntimeError(
                    "Couldn't find the Claude Code CLI. Install Claude Desktop, "
                    "then run it at least once."
                )
            metrics = _parse_metrics(_run_usage(claude_exe, account.auth))
            return AccountSnapshot(
                account_id=account.id,
                provider_id=self.id,
                display_name=account.label or _account_display_name(info),
                logged_in=True,
                plan=str(info["plan"]) if info.get("plan") else None,
                metrics=metrics,
            )
        except Exception as error:
            return AccountSnapshot(
                account_id=account.id,
                provider_id=self.id,
                display_name=account.label or _account_display_name(info),
                logged_in=False,
                plan=str(info["plan"]) if info.get("plan") else None,
                metrics=[],
                error=str(error),
            )
