"""Persist last-good AppSnapshot so restarts show prior metrics immediately."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from core.models import AccountSnapshot, AppSnapshot, Metric


def cache_path() -> Path:
    return Path(os.environ["APPDATA"]) / "UsageWidget" / "last_snapshot.json"


def _metric_to_dict(metric: Metric) -> dict[str, Any]:
    return {
        "id": metric.id,
        "label": metric.label,
        "used_pct": metric.used_pct,
        "used": metric.used,
        "limit": metric.limit,
        "unit": metric.unit,
        "resets_at": metric.resets_at.isoformat() if metric.resets_at else None,
        "extra": metric.extra,
    }


def _metric_from_dict(data: dict[str, Any]) -> Metric:
    resets_raw = data.get("resets_at")
    resets_at = None
    if isinstance(resets_raw, str) and resets_raw:
        try:
            resets_at = datetime.fromisoformat(resets_raw)
        except ValueError:
            resets_at = None
    return Metric(
        id=str(data.get("id") or "unknown"),
        label=str(data.get("label") or data.get("id") or "unknown"),
        used_pct=data.get("used_pct"),
        used=data.get("used"),
        limit=data.get("limit"),
        unit=data.get("unit"),
        resets_at=resets_at,
        extra=dict(data.get("extra") or {}),
    )


def save_snapshot(snapshot: AppSnapshot, path: Path | None = None) -> None:
    path = path or cache_path()
    payload = {
        "fetched_at": snapshot.fetched_at.isoformat(),
        "accounts": [
            {
                "account_id": account.account_id,
                "provider_id": account.provider_id,
                "display_name": account.display_name,
                "logged_in": account.logged_in,
                "plan": account.plan,
                "error": account.error,
                "metrics": [_metric_to_dict(metric) for metric in account.metrics],
            }
            for account in snapshot.accounts
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_snapshot(
    path: Path | None = None,
    *,
    max_age_seconds: int | None = None,
) -> AppSnapshot | None:
    path = path or cache_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    try:
        fetched_raw = data.get("fetched_at")
        fetched_at = (
            datetime.fromisoformat(fetched_raw)
            if isinstance(fetched_raw, str)
            else datetime.now()
        )
        if max_age_seconds is not None:
            fetched_naive = (
                fetched_at.replace(tzinfo=None) if fetched_at.tzinfo else fetched_at
            )
            age = (datetime.now() - fetched_naive).total_seconds()
            if age < 0 or age > max_age_seconds:
                return None
        accounts: list[AccountSnapshot] = []
        for raw in data.get("accounts") or []:
            if not isinstance(raw, dict):
                continue
            accounts.append(
                AccountSnapshot(
                    account_id=str(raw.get("account_id") or "unknown"),
                    provider_id=str(raw.get("provider_id") or "unknown"),
                    display_name=str(raw.get("display_name") or raw.get("account_id") or "unknown"),
                    logged_in=bool(raw.get("logged_in")),
                    plan=raw.get("plan"),
                    metrics=[
                        _metric_from_dict(metric)
                        for metric in (raw.get("metrics") or [])
                        if isinstance(metric, dict)
                    ],
                    error=raw.get("error"),
                )
            )
        return AppSnapshot(fetched_at=fetched_at, accounts=accounts)
    except Exception:
        return None
