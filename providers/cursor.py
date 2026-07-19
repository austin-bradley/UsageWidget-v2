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
from providers.base import (
    DiscoveredAccount,
    auth_preflight,
    error_snapshot,
    resolve_auth_path,
)


API_BASE = "https://api2.cursor.sh"
CURRENT_USAGE_URL = (
    API_BASE + "/aiserver.v1.DashboardService/GetCurrentPeriodUsage"
)
PLAN_INFO_URL = API_BASE + "/aiserver.v1.DashboardService/GetPlanInfo"
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
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
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


def _usd_metric(
    metric_id: str,
    label: str,
    *,
    used_cents: float | None,
    limit_cents: float | None,
    resets_at: datetime | None,
    used_pct: float | None = None,
    extra: dict[str, Any] | None = None,
) -> Metric | None:
    # Limit-only is allowed (cap visible, used unknown) — never invent $0 used.
    if used_cents is None and used_pct is None:
        if limit_cents is None or limit_cents <= 0:
            return None
        return Metric(
            id=metric_id,
            label=label,
            used=None,
            limit=limit_cents / 100,
            unit="usd",
            resets_at=resets_at,
            extra=extra or {},
        )
    if used_pct is None and used_cents is not None and limit_cents:
        used_pct = used_cents / limit_cents * 100
    return Metric(
        id=metric_id,
        label=label,
        used_pct=round(used_pct) if used_pct is not None else None,
        used=used_cents / 100 if used_cents is not None else None,
        limit=limit_cents / 100 if limit_cents is not None else None,
        unit="usd" if used_cents is not None or limit_cents is not None else "percent",
        resets_at=resets_at,
        extra=extra or {},
    )


def _pct_metric(
    metric_id: str,
    label: str,
    pct: float | None,
    resets_at: datetime | None,
    *,
    include_zero: bool = False,
) -> Metric | None:
    if pct is None:
        return None
    if not include_zero and pct <= 0:
        return None
    return Metric(
        id=metric_id,
        label=label,
        used_pct=round(pct),
        unit="percent",
        resets_at=resets_at,
    )


def _current_metrics(data: dict[str, Any]) -> list[Metric]:
    """Map GetCurrentPeriodUsage into monthly / pool / on-demand meters."""
    resets_at = _timestamp(data.get("billingCycleEnd"))
    metrics: list[Metric] = []
    usage = data.get("planUsage")
    if isinstance(usage, dict):
        limit_cents = _number(usage.get("limit"))
        included_cents = _number(usage.get("includedSpend"))
        remaining_cents = _number(usage.get("remaining"))
        if included_cents is None and remaining_cents is not None and limit_cents is not None:
            included_cents = max(0.0, limit_cents - remaining_cents)

        # Plan dollar allowance (includedSpend / limit). Distinct from
        # totalPercentUsed ("Overall usage") and Auto/API pool percents.
        monthly = _usd_metric(
            "included",
            "Monthly $",
            used_cents=included_cents,
            limit_cents=limit_cents,
            resets_at=resets_at,
        )
        if monthly is not None:
            metrics.append(monthly)

        bonus_cents = _number(usage.get("bonusSpend")) or 0.0
        remaining_bonus = bool(usage.get("remainingBonus"))
        # bonusSpend is accrued free-credit spend, not a remaining balance.
        if bonus_cents > 0 or remaining_bonus:
            metrics.append(
                Metric(
                    id="bonus",
                    label="Bonus spend" if bonus_cents > 0 else "Bonus available",
                    used=bonus_cents / 100 if bonus_cents > 0 else None,
                    unit="usd",
                    resets_at=resets_at,
                    extra={"remaining_bonus": remaining_bonus},
                )
            )

        # Keep 0% pools visible so configured slots do not silently drop.
        auto = _pct_metric(
            "auto",
            "Auto pool",
            _number(usage.get("autoPercentUsed")),
            resets_at,
            include_zero=True,
        )
        if auto is not None:
            metrics.append(auto)
        api = _pct_metric(
            "api",
            "API pool",
            _number(usage.get("apiPercentUsed")),
            resets_at,
            include_zero=True,
        )
        if api is not None:
            metrics.append(api)

        # Cursor's own "included total usage" gauge (not dollars/plan limit).
        overall = _pct_metric(
            "overall",
            "Overall usage",
            _number(usage.get("totalPercentUsed")),
            resets_at,
            include_zero=True,
        )
        if overall is not None:
            metrics.append(overall)

        total_spend = _number(usage.get("totalSpend"))
        # Dollar amount only — do not attach totalPercentUsed (different basis).
        if total_spend is not None:
            metrics.append(
                Metric(
                    id="total",
                    label="Total spend",
                    used=total_spend / 100,
                    unit="usd",
                    resets_at=resets_at,
                )
            )

    spend = data.get("spendLimitUsage")
    if isinstance(spend, dict):
        pooled_limit = _number(spend.get("pooledLimit"))
        pooled_used = _number(spend.get("pooledUsed"))
        pooled_remaining = _number(spend.get("pooledRemaining"))
        if pooled_used is None and pooled_limit is not None and pooled_remaining is not None:
            pooled_used = max(0.0, pooled_limit - pooled_remaining)
        # Used alone, or a positive cap (usage may be unknown).
        if pooled_used is not None or (
            pooled_limit is not None and pooled_limit > 0
        ):
            pooled = _usd_metric(
                "pooled",
                "Team pool",
                used_cents=pooled_used,
                limit_cents=pooled_limit,
                resets_at=resets_at,
                extra={"limit_type": spend.get("limitType")},
            )
            if pooled is not None:
                metrics.append(pooled)

        ind_limit = _number(spend.get("individualLimit"))
        ind_used = _number(spend.get("individualUsed"))
        ind_remaining = _number(spend.get("individualRemaining"))
        if ind_used is None and ind_limit is not None and ind_remaining is not None:
            ind_used = max(0.0, ind_limit - ind_remaining)
        # Cap alone is fine (used unknown); do not invent $0 spend.
        if ind_limit is not None and ind_limit > 0:
            on_demand = _usd_metric(
                "on_demand",
                "On-demand cap",
                used_cents=ind_used,
                limit_cents=ind_limit,
                resets_at=resets_at,
                extra={"limit_type": spend.get("limitType")},
            )
            if on_demand is not None:
                metrics.append(on_demand)

    return metrics


def _merge_legacy_if_needed(
    metrics: list[Metric], legacy: list[Metric]
) -> list[Metric]:
    """Fill missing primary meters from legacy without overwriting current ids."""
    have_ids = {metric.id for metric in metrics}
    if "included" in have_ids and "overall" in have_ids:
        return metrics
    merged = list(metrics)
    for metric in legacy:
        if metric.id not in have_ids:
            merged.append(metric)
            have_ids.add(metric.id)
    return merged


def _next_month(value: Any) -> datetime | None:
    start = _timestamp(value)
    if start is None:
        return None
    year = start.year + (1 if start.month == 12 else 0)
    month = 1 if start.month == 12 else start.month + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return start.replace(year=year, month=month, day=day)


def _legacy_metrics(data: dict[str, Any]) -> list[Metric]:
    candidates: list[tuple[str, dict[str, Any]]] = []
    for key, value in data.items():
        if isinstance(value, dict) and _number(value.get("maxRequestUsage")):
            candidates.append((key, value))
    if not candidates:
        return []
    model, usage = next(
        (item for item in candidates if item[0] == "gpt-4"),
        candidates[0],
    )
    used = _number(usage.get("numRequests"))
    limit = _number(usage.get("maxRequestUsage"))
    if used is None or not limit:
        return []
    resets_at = _next_month(data.get("startOfMonth"))
    used_pct = round(used / limit * 100)
    # Explicit requests id, compat included, and overall so migrated
    # percent slots (*.overall) still resolve on the legacy API.
    return [
        Metric(
            id="included_requests",
            label="Monthly requests",
            used_pct=used_pct,
            used=used,
            limit=limit,
            unit="requests",
            resets_at=resets_at,
            extra={"model": model},
        ),
        Metric(
            id="included",
            label="Monthly requests",
            used_pct=used_pct,
            used=used,
            limit=limit,
            unit="requests",
            resets_at=resets_at,
            extra={"model": model, "legacy_alias": True},
        ),
        Metric(
            id="overall",
            label="Overall usage",
            used_pct=used_pct,
            unit="percent",
            resets_at=resets_at,
            extra={"model": model, "legacy_proxy": True},
        ),
    ]


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
            plan_name: str | None = None
            try:
                plan_payload = _request_json(PLAN_INFO_URL, token, post=True)
                info = plan_payload.get("planInfo")
                if isinstance(info, dict) and isinstance(info.get("planName"), str):
                    plan_name = info["planName"]
            except Exception:
                plan_name = None

            current_error = None
            metrics: list[Metric] = []
            try:
                current = _request_json(CURRENT_USAGE_URL, token, post=True)
                metrics = _current_metrics(current)
            except Exception as error:
                current_error = str(error)
                metrics = []
            # Hole-fill included/overall from legacy when either is missing.
            metric_ids = {metric.id for metric in metrics}
            if "included" not in metric_ids or "overall" not in metric_ids:
                try:
                    metrics = _merge_legacy_if_needed(
                        metrics,
                        _legacy_metrics(_request_json(LEGACY_USAGE_URL, token)),
                    )
                except Exception as error:
                    if not metrics:
                        detail = str(error)
                        if current_error:
                            detail = f"{current_error}; fallback: {detail}"
                        raise RuntimeError(
                            f"Cursor usage API failed: {detail}"
                        ) from error
            if not metrics:
                raise RuntimeError("Cursor usage API failed: no supported quota data")
            return AccountSnapshot(
                account_id=account.id,
                provider_id=self.id,
                display_name=account.label or "Cursor",
                logged_in=True,
                plan=plan_name,
                metrics=metrics,
            )
        except Exception as error:
            had_creds = False
            try:
                had_creds = bool(_resolve_token(account.auth))
            except Exception:
                had_creds = _state_db_path().is_file()
            return error_snapshot(
                account,
                self.id,
                error,
                display_name=account.label or "Cursor",
                had_credentials=had_creds,
            )
