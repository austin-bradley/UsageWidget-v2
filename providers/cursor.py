from __future__ import annotations

import calendar
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.models import AccountConfig, AccountSnapshot, AuthConfig, Metric
from providers.base import DiscoveredAccount, auth_preflight, resolve_auth_path


API_BASE = "https://api2.cursor.sh"
CURRENT_USAGE_URL = (
    API_BASE + "/aiserver.v1.DashboardService/GetCurrentPeriodUsage"
)
LEGACY_USAGE_URL = API_BASE + "/auth/usage"


def _state_db_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Cursor" / "User" / "globalStorage" / "state.vscdb"
    if os.name == "nt":
        return (
            Path.home()
            / "AppData"
            / "Roaming"
            / "Cursor"
            / "User"
            / "globalStorage"
            / "state.vscdb"
        )
    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "Cursor"
            / "User"
            / "globalStorage"
            / "state.vscdb"
        )
    return Path.home() / ".config" / "Cursor" / "User" / "globalStorage" / "state.vscdb"


def _normalize_token(value: str) -> str:
    value = value.strip()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return value
    if isinstance(parsed, str):
        return parsed.strip()
    if isinstance(parsed, dict):
        for key in ("accessToken", "access_token", "token"):
            token = parsed.get(key)
            if isinstance(token, str):
                return token.strip()
    return value


def _read_token_file(path: str) -> str:
    token_path = Path(resolve_auth_path(path) or path)
    with token_path.open(encoding="utf-8") as file:
        token = _normalize_token(file.read())
    if not token:
        raise RuntimeError("Cursor token file is empty")
    return token


def _read_sqlite_token(path: Path | None = None) -> str:
    db_path = path or _state_db_path()
    if not db_path.is_file():
        raise RuntimeError("Cursor token not found")
    connection = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT value FROM ItemTable WHERE key = ?",
            ("cursorAuth/accessToken",),
        ).fetchone()
    finally:
        connection.close()
    if not row or not row[0]:
        raise RuntimeError("Cursor token not found")
    raw = row[0]
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    token = _normalize_token(str(raw))
    if not token:
        raise RuntimeError("Cursor token not found")
    return token


def _resolve_token(auth: AuthConfig) -> str:
    if auth.api_key:
        return auth.api_key.strip()
    if auth.token_file:
        return _read_token_file(auth.token_file)
    return _read_sqlite_token()


def _request_json(url: str, token: str, *, post: bool = False) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "UsageWidget-v2",
    }
    data = None
    if post:
        headers["Content-Type"] = "application/json"
        headers["Connect-Protocol-Version"] = "1"
        data = b"{}"
    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method="POST" if post else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"HTTP {error.code} {error.reason}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(str(error.reason)) from error
    except json.JSONDecodeError as error:
        raise RuntimeError("usage endpoint returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise RuntimeError("usage endpoint returned an unexpected response")
    return payload


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


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


def _current_metric(data: dict[str, Any]) -> Metric | None:
    usage = data.get("planUsage")
    if not isinstance(usage, dict):
        return None
    limit_cents = _number(usage.get("limit"))
    used_pct = _number(usage.get("totalPercentUsed"))
    used_cents = _number(usage.get("used"))
    if used_cents is None and used_pct is not None and limit_cents is not None:
        used_cents = limit_cents * used_pct / 100
    if used_cents is None:
        used_cents = _number(usage.get("totalSpend"))
    if used_pct is None and used_cents is not None and limit_cents:
        used_pct = used_cents / limit_cents * 100
    if used_cents is None and used_pct is None:
        return None
    return Metric(
        id="included",
        label="Included",
        used_pct=round(used_pct) if used_pct is not None else None,
        used=used_cents / 100 if used_cents is not None else None,
        limit=limit_cents / 100 if limit_cents is not None else None,
        unit="usd" if used_cents is not None or limit_cents is not None else "percent",
        resets_at=_timestamp(data.get("billingCycleEnd")),
    )


def _next_month(value: Any) -> datetime | None:
    start = _timestamp(value)
    if start is None:
        return None
    year = start.year + (1 if start.month == 12 else 0)
    month = 1 if start.month == 12 else start.month + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return start.replace(year=year, month=month, day=day)


def _legacy_metric(data: dict[str, Any]) -> Metric | None:
    candidates: list[tuple[str, dict[str, Any]]] = []
    for key, value in data.items():
        if isinstance(value, dict) and _number(value.get("maxRequestUsage")):
            candidates.append((key, value))
    if not candidates:
        return None
    model, usage = next(
        (item for item in candidates if item[0] == "gpt-4"),
        candidates[0],
    )
    used = _number(usage.get("numRequests"))
    limit = _number(usage.get("maxRequestUsage"))
    if used is None or not limit:
        return None
    return Metric(
        id="included",
        label="Included",
        used_pct=round(used / limit * 100),
        used=used,
        limit=limit,
        unit="requests",
        resets_at=_next_month(data.get("startOfMonth")),
        extra={"model": model},
    )


class CursorProvider:
    id = "cursor"

    def discover_accounts(self) -> list[DiscoveredAccount]:
        try:
            _read_sqlite_token()
        except Exception:
            return []
        return [
            DiscoveredAccount(
                suggested_id="cursor-main",
                display_name="Cursor",
                auth_hints={},
            )
        ]

    def fetch(self, account: AccountConfig) -> AccountSnapshot:
        try:
            preflight = auth_preflight(account.auth)
            if preflight:
                raise RuntimeError(preflight)
            token = _resolve_token(account.auth)
            current_error = None
            try:
                current = _request_json(CURRENT_USAGE_URL, token, post=True)
                metric = _current_metric(current)
            except Exception as error:
                current_error = str(error)
                metric = None
            if metric is None:
                try:
                    metric = _legacy_metric(_request_json(LEGACY_USAGE_URL, token))
                except Exception as error:
                    detail = str(error)
                    if current_error:
                        detail = f"{current_error}; fallback: {detail}"
                    raise RuntimeError(f"Cursor usage API failed: {detail}") from error
            if metric is None:
                raise RuntimeError("Cursor usage API failed: no supported quota data")
            return AccountSnapshot(
                account_id=account.id,
                provider_id=self.id,
                display_name=account.label or "Cursor",
                logged_in=True,
                plan=None,
                metrics=[metric],
            )
        except Exception as error:
            return AccountSnapshot(
                account_id=account.id,
                provider_id=self.id,
                display_name=account.label or "Cursor",
                logged_in=False,
                plan=None,
                metrics=[],
                error=str(error),
            )
