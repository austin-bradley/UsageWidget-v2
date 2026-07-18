from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.models import AccountConfig, AccountSnapshot, AuthConfig, Metric
from providers.base import (
    DiscoveredAccount,
    auth_mode,
    auth_preflight,
    resolve_auth_path,
)


USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"


def _auth_path(auth: AuthConfig) -> Path:
    if auth.token_file:
        return Path(resolve_auth_path(auth.token_file) or auth.token_file)
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        return Path(codex_home).expanduser() / "auth.json"
    return Path.home() / ".codex" / "auth.json"


def _read_auth(auth: AuthConfig) -> tuple[str, str | None]:
    if auth.api_key:
        raise RuntimeError(
            "GPT subscription quota requires Codex OAuth; run `codex login`"
        )
    path = _auth_path(auth)
    if not path.is_file():
        raise RuntimeError("GPT auth not found; run `codex login`")
    try:
        with path.open(encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(
            "GPT auth file could not be read; run `codex login`"
        ) from error
    tokens = data.get("tokens") if isinstance(data, dict) else None
    if not isinstance(tokens, dict):
        tokens = {}
    token = tokens.get("access_token") or data.get("access_token")
    account_id = tokens.get("account_id") or data.get("account_id")
    if not isinstance(token, str) or not token.strip():
        raise RuntimeError("GPT access token not found; run `codex login`")
    return token.strip(), account_id if isinstance(account_id, str) else None


def _request_usage(token: str, account_id: str | None) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "UsageWidget-v2",
    }
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id
    request = urllib.request.Request(USAGE_URL, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"HTTP {error.code} {error.reason}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(str(error.reason)) from error
    except json.JSONDecodeError as error:
        raise RuntimeError("quota endpoint returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise RuntimeError("quota endpoint returned an unexpected response")
    return payload


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _reset_at(window: dict[str, Any]) -> datetime | None:
    reset = _number(window.get("reset_at"))
    if reset is not None:
        try:
            return datetime.fromtimestamp(reset, timezone.utc)
        except (OSError, OverflowError, ValueError):
            pass
    after = _number(window.get("reset_after_seconds"))
    if after is not None:
        return datetime.now(timezone.utc) + timedelta(seconds=after)
    return None


def _window(
    data: dict[str, Any],
    keys: tuple[str, ...],
) -> dict[str, Any] | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, dict):
            return value
    return None


def _metric(
    metric_id: str,
    label: str,
    window: dict[str, Any] | None,
) -> Metric | None:
    if window is None:
        return None
    used_pct = _number(
        window.get("used_percent", window.get("used_pct", window.get("percent_used")))
    )
    if used_pct is None:
        remaining_pct = _number(
            window.get("remaining_percent", window.get("percent_remaining"))
        )
        if remaining_pct is not None:
            used_pct = 100 - remaining_pct
    if used_pct is None:
        return None
    return Metric(
        id=metric_id,
        label=label,
        used_pct=round(used_pct),
        unit="percent",
        resets_at=_reset_at(window),
    )


def _parse_metrics(data: dict[str, Any]) -> list[Metric]:
    rate_limit = data.get("rate_limit")
    source = rate_limit if isinstance(rate_limit, dict) else data
    five_hour = _window(
        source,
        ("five_hour", "five_hour_limit", "primary_window"),
    )
    week = _window(
        source,
        ("week", "weekly", "weekly_limit", "secondary_window"),
    )
    metrics = [
        _metric("five_hour", "Five hour", five_hour),
        _metric("week", "Week", week),
    ]
    return [metric for metric in metrics if metric is not None]


def _identity(data: dict[str, Any]) -> tuple[str | None, str | None]:
    email = data.get("email")
    plan = data.get("plan_type")
    return (
        email if isinstance(email, str) else None,
        plan if isinstance(plan, str) else None,
    )


class GptProvider:
    id = "gpt"

    def discover_accounts(self) -> list[DiscoveredAccount]:
        try:
            _read_auth(AuthConfig())
        except Exception:
            return []
        return [
            DiscoveredAccount(
                suggested_id="gpt-main",
                display_name="GPT / Codex",
                auth_hints={},
            )
        ]

    def fetch(self, account: AccountConfig) -> AccountSnapshot:
        display_name = account.label or "GPT / Codex"
        plan = None
        try:
            preflight = auth_preflight(account.auth)
            if preflight:
                raise RuntimeError(preflight)
            if auth_mode(account.auth) == "api_key":
                raise RuntimeError(
                    "GPT subscription quota requires Codex OAuth; "
                    "set auth.mode to auto or token_file and run `codex login`"
                )
            token, account_id = _read_auth(account.auth)
            data = _request_usage(token, account_id)
            email, plan = _identity(data)
            if not account.label and email:
                display_name = email
            metrics = _parse_metrics(data)
            if not metrics:
                raise RuntimeError("quota response contained no supported windows")
            return AccountSnapshot(
                account_id=account.id,
                provider_id=self.id,
                display_name=display_name,
                logged_in=True,
                plan=plan,
                metrics=metrics,
            )
        except Exception as error:
            return AccountSnapshot(
                account_id=account.id,
                provider_id=self.id,
                display_name=display_name,
                logged_in=False,
                plan=plan,
                metrics=[],
                error=f"GPT usage API failed: {error}",
            )
