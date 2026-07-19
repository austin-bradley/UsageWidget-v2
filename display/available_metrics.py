"""Metric refs available for Display Options pickers."""
from __future__ import annotations

from core.models import AppConfig, AppSnapshot

SHOW_MODES = (
    "percent",
    "remaining_pct",
    "reset",
    "percent_and_reset",
    "used_of_limit",
)

# Fallback meter ids when the latest snapshot has not returned metrics yet.
_PROVIDER_FALLBACKS: dict[str, tuple[tuple[str, str], ...]] = {
    "claude": (
        ("session", "Session"),
        ("week", "Week (all models)"),
        ("fable_week", "Week (Fable)"),
        ("api", "API"),
    ),
    "cursor": (
        ("overall", "Overall usage"),
        ("included", "Monthly $"),
        ("bonus", "Bonus"),
        ("auto", "Auto pool"),
        ("api", "API pool"),
        ("total", "Total spend"),
        ("on_demand", "On-demand cap"),
        ("pooled", "Team pool"),
        ("included_requests", "Monthly requests"),
    ),
    "gpt": (
        ("session", "Session"),
        ("week", "Week"),
        ("included", "Included"),
    ),
    "gemini": (
        ("session", "Session"),
        ("week", "Week"),
        ("included", "Included"),
    ),
}


def list_available_metric_refs(
    config: AppConfig,
    snapshot: AppSnapshot,
) -> list[tuple[str, str]]:
    """Return ``(ref, label)`` pairs for enabled accounts."""
    by_ref: dict[str, str] = {}
    accounts_by_id = {a.id: a for a in config.accounts if a.enabled}

    for account in snapshot.accounts:
        if account.account_id not in accounts_by_id:
            continue
        base = account.display_name or account.account_id
        for metric in account.metrics:
            ref = f"{account.account_id}.{metric.id}"
            by_ref[ref] = f"{base} · {metric.label}"

    for account in config.accounts:
        if not account.enabled:
            continue
        base = account.label or account.id
        for metric_id, metric_label in _PROVIDER_FALLBACKS.get(account.provider, ()):
            ref = f"{account.id}.{metric_id}"
            by_ref.setdefault(ref, f"{base} · {metric_label}")

    return sorted(by_ref.items(), key=lambda item: item[1].casefold())
