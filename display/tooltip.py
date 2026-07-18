from __future__ import annotations

from datetime import datetime

from core.models import AppSnapshot, DisplayProfile
from display.format_value import format_slot, resolve_metric


def _join_truncated(pieces: list[str], max_chars: int, sep: str = " · ") -> str:
    """Keep whole pieces when possible instead of cutting mid-token."""
    if max_chars <= 0:
        return ""
    if not pieces:
        return ""
    out = pieces[0]
    if len(out) > max_chars:
        return out[: max_chars - 1] + "…" if max_chars > 1 else out[:max_chars]
    for piece in pieces[1:]:
        candidate = f"{out}{sep}{piece}"
        if len(candidate) > max_chars:
            break
        out = candidate
    return out


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

    max_chars = max(0, profile.tooltip.max_chars)
    if not pieces:
        if any(account.error for account in snapshot.accounts):
            tooltip = "Usage unavailable"
        elif not snapshot.accounts:
            tooltip = "No accounts enabled"
        else:
            tooltip = "Loading…"
    elif profile.tooltip.format == "lines":
        # Windows tray titles usually flatten newlines; still prefer piece-aware trim.
        tooltip = _join_truncated(pieces, max_chars, sep="\n")
    else:
        tooltip = _join_truncated(pieces, max_chars)

    if stale_after_seconds and snapshot.accounts:
        age = (datetime.now() - snapshot.fetched_at.replace(tzinfo=None)).total_seconds()
        if age > stale_after_seconds:
            prefix = "stale · "
            room = max_chars - len(prefix)
            tooltip = prefix + (
                _join_truncated(pieces, room) if pieces else tooltip[: max(0, room)]
            )

    return tooltip[:max_chars]
