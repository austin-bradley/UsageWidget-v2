from __future__ import annotations

from datetime import datetime

from core.models import AppSnapshot, DisplayProfile
from display.format_value import format_slot, resolve_metric


def build_tooltip(
    profile: DisplayProfile,
    snapshot: AppSnapshot,
    *,
    stale_after_seconds: int | None = None,
) -> str:
    pieces: list[str] = []
    for slot in profile.tooltip.slots:
        match = resolve_metric(snapshot, slot.ref)
        if match is None:
            continue
        _, metric = match
        label = slot.label or metric.label
        # Keep tooltip labels short.
        if len(label) > 10 and " " in label:
            label = label.split()[0]
        pieces.append(f"{label} {format_slot(slot, metric)}")

    if not pieces:
        if any(account.error for account in snapshot.accounts):
            tooltip = "Usage unavailable"
        elif not snapshot.accounts:
            tooltip = "No accounts enabled"
        else:
            tooltip = "Loading…"
    elif profile.tooltip.format == "lines":
        tooltip = "\n".join(pieces)
    else:
        tooltip = " · ".join(pieces)

    if stale_after_seconds and snapshot.accounts:
        age = (datetime.now() - snapshot.fetched_at.replace(tzinfo=None)).total_seconds()
        if age > stale_after_seconds:
            tooltip = f"stale · {tooltip}"

    return tooltip[: max(0, profile.tooltip.max_chars)]
