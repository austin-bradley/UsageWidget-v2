from __future__ import annotations

from core.models import AppSnapshot, DisplayProfile
from display.format_value import format_slot, resolve_metric


def build_tooltip(profile: DisplayProfile, snapshot: AppSnapshot) -> str:
    pieces: list[str] = []
    for slot in profile.tooltip.slots:
        match = resolve_metric(snapshot, slot.ref)
        if match is None:
            continue
        _, metric = match
        label = slot.label or metric.label
        pieces.append(f"{label} {format_slot(slot, metric)}")

    tooltip = " | ".join(pieces) if pieces else "Usage unavailable"
    return tooltip[: max(0, profile.tooltip.max_chars)]
