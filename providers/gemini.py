from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any, Iterator

from core.models import AccountConfig, AccountSnapshot, Metric
from providers.base import DiscoveredAccount, auth_preflight


USED_KEYS = ("used_percent", "usedPercent", "usedPercentage", "percentUsed")
REMAINING_KEYS = (
    "remaining_percent",
    "remainingPercent",
    "remainingPercentage",
    "percentRemaining",
)
FRACTION_KEYS = ("remaining_fraction", "remainingFraction")
RESET_KEYS = ("reset_at", "resetAt", "reset_time", "resetTime", "pooledResetTime")


def _find_gemini() -> str | None:
    return shutil.which("gemini")


def _run_stats(executable: str) -> str:
    run_kwargs: dict[str, Any] = {
        "capture_output": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": 20,
        "stdin": subprocess.DEVNULL,
        "env": os.environ.copy(),
    }
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        run_kwargs["startupinfo"] = startupinfo
    process = subprocess.run(
        [executable, "-p", "/stats model", "--output-format", "json"],
        **run_kwargs,
    )
    output = (process.stdout or "").strip()
    if not output:
        detail = (process.stderr or "").strip()[:300]
        raise RuntimeError(
            detail or f"Gemini CLI exited with code {process.returncode} and no output"
        )
    if process.returncode != 0:
        detail = (process.stderr or output).strip()[:300]
        raise RuntimeError(detail or f"Gemini CLI exited with code {process.returncode}")
    return output


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _first_number(data: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _number(data.get(key))
        if value is not None:
            return value
    return None


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            numeric = float(value)
        except ValueError:
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        numeric = float(value)
    else:
        return None
    if numeric > 10_000_000_000:
        numeric /= 1000
    try:
        return datetime.fromtimestamp(numeric, timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


def _walk_dicts(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _quota_candidate(
    data: dict[str, Any],
) -> tuple[float, datetime | None, str | None] | None:
    used_pct = _first_number(data, USED_KEYS)
    if used_pct is None:
        remaining_pct = _first_number(data, REMAINING_KEYS)
        if remaining_pct is not None:
            used_pct = 100 - remaining_pct
    if used_pct is None:
        remaining_fraction = _first_number(data, FRACTION_KEYS)
        if remaining_fraction is not None:
            used_pct = (1 - remaining_fraction) * 100
    if used_pct is None:
        remaining = _first_number(data, ("pooledRemaining", "remainingAmount"))
        limit = _first_number(data, ("pooledLimit", "limit"))
        if remaining is not None and limit:
            used_pct = (limit - remaining) / limit * 100
    if used_pct is None:
        return None
    reset_at = None
    for key in RESET_KEYS:
        reset_at = _timestamp(data.get(key))
        if reset_at is not None:
            break
    label = next(
        (
            value
            for key in ("modelId", "model", "name", "label")
            if isinstance((value := data.get(key)), str)
        ),
        None,
    )
    return max(0, min(100, used_pct)), reset_at, label


def _parse_json_metric(output: str) -> Metric | None:
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return None
    candidates = [
        candidate
        for item in _walk_dicts(data)
        if (candidate := _quota_candidate(item)) is not None
    ]
    if not candidates:
        return None
    used_pct, reset_at, label = max(candidates, key=lambda item: item[0])
    return Metric(
        id="daily",
        label="Daily",
        used_pct=round(used_pct),
        unit="percent",
        resets_at=reset_at,
        extra={"model": label} if label else {},
    )


def _parse_text_metric(output: str) -> Metric | None:
    used_matches = re.findall(r"(\d+(?:\.\d+)?)\s*%\s*used", output, re.IGNORECASE)
    if used_matches:
        used_pct = max(float(value) for value in used_matches)
    else:
        remaining_matches = re.findall(
            r"(\d+(?:\.\d+)?)\s*%\s*(?:remaining|left)",
            output,
            re.IGNORECASE,
        )
        if not remaining_matches:
            return None
        used_pct = max(100 - float(value) for value in remaining_matches)
    return Metric(
        id="daily",
        label="Daily",
        used_pct=round(max(0, min(100, used_pct))),
        unit="percent",
    )


class GeminiProvider:
    id = "gemini"

    def discover_accounts(self) -> list[DiscoveredAccount]:
        if not _find_gemini():
            return []
        return [
            DiscoveredAccount(
                suggested_id="gemini-main",
                display_name="Gemini CLI",
                auth_hints={},
            )
        ]

    def fetch(self, account: AccountConfig) -> AccountSnapshot:
        display_name = account.label or "Gemini CLI"
        try:
            preflight = auth_preflight(account.auth)
            if preflight:
                raise RuntimeError(preflight)
            executable = _find_gemini()
            if not executable:
                if account.auth.api_key:
                    raise RuntimeError(
                        "API-key quota support is not available yet; "
                        "install the Gemini CLI for subscription quota."
                    )
                raise RuntimeError(
                    "Gemini CLI not found; install it and log in."
                )
            output = _run_stats(executable)
            metric = _parse_json_metric(output) or _parse_text_metric(output)
            if metric is None:
                raise RuntimeError(
                    "Gemini CLI returned no quota data; update the CLI and log in"
                )
            return AccountSnapshot(
                account_id=account.id,
                provider_id=self.id,
                display_name=display_name,
                logged_in=True,
                plan=None,
                metrics=[metric],
            )
        except Exception as error:
            return AccountSnapshot(
                account_id=account.id,
                provider_id=self.id,
                display_name=display_name,
                logged_in=False,
                plan=None,
                metrics=[],
                error=str(error),
            )
