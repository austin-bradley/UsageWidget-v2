from __future__ import annotations

from datetime import datetime

from core.models import AccountSnapshot, AppSnapshot, DisplaySlot, Metric


def _fmt_countdown(reset_at: datetime | None, *, compact: bool = False) -> str:
    if reset_at is None:
        return "?"
    now = datetime.now(reset_at.tzinfo) if reset_at.tzinfo else datetime.now()
    seconds = int((reset_at - now).total_seconds())
    if seconds <= 0:
        return "now"
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if hours >= 48:
        days, rem_h = divmod(hours, 24)
        if compact:
            return f"{days}d"
        return f"{days}d{rem_h}h" if rem_h else f"{days}d"
    if hours > 0:
        # Icon cells are tiny — prefer "2h" over "2h14m".
        if compact:
            return f"{hours}h"
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m"


def resolve_metric(
    snapshot: AppSnapshot, ref: str
) -> tuple[AccountSnapshot, Metric] | None:
    try:
        account_id, metric_id = ref.rsplit(".", 1)
    except ValueError:
        return None
    for account in snapshot.accounts:
        if account.account_id != account_id:
            continue
        for metric in account.metrics:
            if metric.id == metric_id:
                return account, metric
        return None
    return None


def format_slot(
    slot: DisplaySlot | str,
    metric: Metric,
    *,
    compact: bool = False,
) -> str:
    show = slot.show if isinstance(slot, DisplaySlot) else slot
    pct = metric.used_pct
    countdown = _fmt_countdown(metric.resets_at, compact=compact)

    bonus_open = (
        metric.used is None
        and bool(metric.extra.get("remaining_bonus"))
    )
    if show == "percent":
        if pct is None and bonus_open:
            return "ok"
        return "?" if pct is None else str(pct)
    elif show == "remaining_pct":
        # Unused bonus credits ⇒ full remaining headroom (numeric, not "ok").
        if pct is None and bonus_open:
            return "100"
        return "?" if pct is None else str(max(0, 100 - pct))
    elif show == "reset":
        return countdown
    elif show == "percent_and_reset":
        if pct is None and bonus_open:
            return f"ok·{countdown}"
        percent = "?" if pct is None else str(pct)
        return f"{percent}·{countdown}"
    elif show == "used_of_limit":
        if metric.used is not None and metric.limit is not None:
            if metric.unit == "usd":
                used = f"${metric.used:.0f}" if compact else f"${metric.used:g}"
                limit = f"${metric.limit:.0f}" if compact else f"${metric.limit:g}"
                return f"{used}/{limit}"
            if compact:
                return f"{metric.used:.0f}/{metric.limit:.0f}"
            return f"{metric.used:g}/{metric.limit:g}"
        if metric.used is None and metric.limit is not None:
            # Cap known, usage unknown — do not invent $0.
            if metric.unit == "usd":
                limit = f"${metric.limit:.0f}" if compact else f"${metric.limit:g}"
            else:
                limit = f"{metric.limit:.0f}" if compact else f"{metric.limit:g}"
            return f"—/{limit}"
        if metric.used is not None and metric.unit == "usd":
            # Bonus / total spend without a hard cap.
            return f"${metric.used:.0f}" if compact else f"${metric.used:g}"
        if bonus_open:
            return "avail"
        return "?" if pct is None else f"{pct}%"
    if pct is None and bonus_open:
        return "ok"
    return "?" if pct is None else str(pct)
