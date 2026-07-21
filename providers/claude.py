from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from core.models import AccountConfig, AccountSnapshot, AuthConfig, Metric
from providers.base import (
    DiscoveredAccount,
    auth_mode,
    auth_preflight,
    error_snapshot,
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


def _normalize_tier_blob(*parts: str) -> str:
    """Lowercase and collapse separators to ``_`` for boundary-safe matching."""
    raw = "_".join(part for part in parts if part).lower()
    return re.sub(r"[^a-z0-9]+", "_", raw).strip("_")


def _blob_has(blob: str, *needles: str) -> bool:
    """True if any needle is a full ``_``-delimited segment in blob."""
    if not blob:
        return False
    padded = f"_{blob}_"
    return any(f"_{needle}_" in padded for needle in needles)


def _plan_from_tiers(org_type: str, tiers: str) -> str | None:
    org_type = org_type.lower().strip()
    blob = _normalize_tier_blob(org_type, tiers)
    is_max = org_type in {"claude_max", "max"} or _blob_has(
        blob, "max", "claude_max"
    )
    if is_max:
        if _blob_has(blob, "20x", "max_20", "max20", "max_20x", "claude_max_20x"):
            return "Max (20x)"
        # Boundary-safe: max_5 matches, max_50 does not.
        if _blob_has(blob, "5x", "max_5", "max5", "max_5x", "claude_max_5x"):
            return "Max (5x)"
        if org_type in {"claude_max", "max"} or _blob_has(blob, "claude_max"):
            return "Max"
        return None
    if org_type in {"claude_pro", "claude_ai", "pro"} or _blob_has(
        blob,
        "default_claude_ai",
        "default_claude_pro",
        "pro",
        "claude_pro",
        "claude_ai",
    ):
        return "Pro"
    return None


def _plan_from_oauth_account(account: dict[str, Any]) -> str | None:
    """Plan from ``~/.claude.json`` oauthAccount (updates after upgrades)."""
    # Prefer the more specific of org vs user tier strings (e.g. max_5 over
    # a generic org marker), not a simple ``or`` that can hide 5x/20x.
    org_tiers = str(account.get("organizationRateLimitTier") or "")
    user_tiers = str(account.get("userRateLimitTier") or "")
    tiers = " ".join(part for part in (org_tiers, user_tiers) if part)
    return _plan_from_tiers(str(account.get("organizationType") or ""), tiers)


def _plan_from_credentials_oauth(oauth: dict[str, Any]) -> str | None:
    """Plan from ``.credentials.json`` claudeAiOauth (often stale after upgrades)."""
    sub = oauth.get("subscriptionType")
    tiers = str(oauth.get("rateLimitTier") or "")
    labeled = _plan_from_tiers(str(sub or ""), tiers)
    if labeled:
        return labeled
    return str(sub) if isinstance(sub, str) and sub else None


def _plan_family(plan: str | None) -> str | None:
    """Coarse plan identity for drift — Max / Max 5x / Max 20x are distinct."""
    if not plan:
        return None
    lower = plan.casefold()
    if "max" in lower and "20" in lower:
        return "max20"
    if "max" in lower and "5" in lower:
        return "max5"
    if "max" in lower:
        return "max"
    if "pro" in lower:
        return "pro"
    return lower


def _plan_specificity(plan: str | None) -> int:
    family = _plan_family(plan)
    if family == "max20":
        return 3
    if family == "max5":
        return 2
    if family == "max":
        return 1
    if family == "pro":
        return 1
    return 0


def read_plan_sources(auth: AuthConfig) -> tuple[str | None, str | None]:
    """Return ``(profile_plan, credential_plan)`` from local Claude files."""
    _, credentials_path, account_paths = _auth_paths(auth)
    # Prefer more specific plans across candidates; prefer ``.claude.json``
    # over ``claude.json`` when specificity ties (name ends with .claude.json).
    profile_plan: str | None = None
    profile_score = -1
    for account_path in account_paths:
        try:
            with account_path.open(encoding="utf-8") as file:
                account = (json.load(file) or {}).get("oauthAccount") or {}
            if not isinstance(account, dict) or not account:
                continue
            plan = _plan_from_oauth_account(account)
            if not plan:
                continue
            score = _plan_specificity(plan) * 10
            if account_path.name == ".claude.json":
                score += 1
            if score > profile_score:
                profile_plan = plan
                profile_score = score
        except Exception:
            continue
    cred_plan: str | None = None
    try:
        with credentials_path.open(encoding="utf-8") as file:
            oauth = (json.load(file) or {}).get("claudeAiOauth") or {}
        if isinstance(oauth, dict):
            cred_plan = _plan_from_credentials_oauth(oauth)
    except Exception:
        pass
    return profile_plan, cred_plan


def plan_drift(auth: AuthConfig) -> tuple[str, str] | None:
    """If profile and credentials disagree on plan family, return both labels."""
    profile_plan, cred_plan = read_plan_sources(auth)
    if profile_plan and cred_plan:
        if _plan_family(profile_plan) == _plan_family(cred_plan):
            return None
        return profile_plan, cred_plan
    # One-sided: profile shows Max* but credentials have no Max plan yet.
    if profile_plan and _plan_family(profile_plan) in {"max", "max5", "max20"}:
        if not cred_plan or _plan_family(cred_plan) == "pro":
            return profile_plan, cred_plan or "unknown"
    return None


def claude_accounts_with_drift(
    accounts: list[AccountConfig],
) -> list[tuple[AccountConfig, str, str]]:
    drifted: list[tuple[AccountConfig, str, str]] = []
    for account in accounts:
        if account.provider != "claude" or not account.enabled:
            continue
        if auth_mode(account.auth) == "api_key":
            continue
        drift = plan_drift(account.auth)
        if drift is not None:
            drifted.append((account, drift[0], drift[1]))
    return drifted


def read_account_email(auth: AuthConfig) -> str | None:
    info = _read_account(auth)
    email = info.get("email")
    return email if isinstance(email, str) and email else None


def claude_auth_root(auth: AuthConfig) -> str:
    """Stable key so shared Claude homes are only logged in once."""
    config_dir, credentials_path, _ = _auth_paths(auth)
    try:
        return str(credentials_path.resolve())
    except OSError:
        return str(config_dir)


def run_subscription_login(auth: AuthConfig, *, email: str | None = None) -> None:
    """Open Claude Code subscription login (browser). Does not force logout first."""
    claude_exe = get_claude_exe()
    if not claude_exe:
        raise RuntimeError("Couldn't find the Claude Code CLI")
    cmd = [claude_exe, "auth", "login", "--claudeai"]
    if email:
        cmd.extend(["--email", email])
    # New console for the windowed tray build (console=False); browser OAuth.
    # Do not redirect stdio — the console may need keyboard (copy URL / Enter).
    # Caller must not run this on the Tk UI thread.
    run_kwargs: dict[str, Any] = {
        "timeout": 300,
        "env": _usage_environment(auth),
    }
    if os.name == "nt":
        run_kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
    proc = subprocess.run(cmd, **run_kwargs)
    if proc.returncode != 0:
        raise RuntimeError(f"claude auth login exited {proc.returncode}")


def _read_account(auth: AuthConfig) -> dict[str, str | bool | None]:
    _, credentials_path, account_paths = _auth_paths(auth)
    info: dict[str, str | bool | None] = {
        "name": None,
        "email": None,
        "plan": None,
        "logged_in": False,
    }
    profile_plan: str | None = None
    for account_path in account_paths:
        try:
            with account_path.open(encoding="utf-8") as file:
                account = (json.load(file) or {}).get("oauthAccount") or {}
            if not isinstance(account, dict) or not account:
                continue
            if info["name"] is None and account.get("displayName"):
                info["name"] = account.get("displayName")
            if info["email"] is None and account.get("emailAddress"):
                info["email"] = account.get("emailAddress")
            if profile_plan is None:
                profile_plan = _plan_from_oauth_account(account)
        except Exception:
            continue
    try:
        with credentials_path.open(encoding="utf-8") as file:
            oauth = (json.load(file) or {}).get("claudeAiOauth") or {}
        cred_plan = (
            _plan_from_credentials_oauth(oauth) if isinstance(oauth, dict) else None
        )
        # Profile Max/Pro beats a stale token subscriptionType after upgrades.
        info["plan"] = profile_plan or cred_plan
        info["logged_in"] = bool(oauth.get("accessToken"))
    except Exception:
        if profile_plan:
            info["plan"] = profile_plan
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
        # Cold starts / busy Claude Desktop can exceed 20s on Store builds.
        "timeout": 45,
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
            had_creds = False
            try:
                _, credentials_path, _ = _auth_paths(account.auth)
                had_creds = credentials_path.is_file()
            except Exception:
                had_creds = False
            return error_snapshot(
                account,
                self.id,
                error,
                display_name=account.label or _account_display_name(info),
                plan=str(info["plan"]) if info.get("plan") else None,
                had_credentials=had_creds,
            )
