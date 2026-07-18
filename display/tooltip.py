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

    if not pieces:
        tooltip = "Usage unavailable"
    elif profile.tooltip.format == "lines":
        tooltip = "\n".join(pieces)
    else:
        tooltip = " | ".join(pieces)
    return tooltip[: max(0, profile.tooltip.max_chars)]
