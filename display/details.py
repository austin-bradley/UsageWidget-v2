from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from core.models import AppSnapshot, DisplayProfile, Metric
from display.format_value import format_slot


def _status_mark(pct: int | None) -> str:
    if pct is None:
        return "·"
    if pct >= 85:
        return "●"
    if pct >= 60:
        return "◐"
    return "○"


def _format_metric(metric: Metric, always_include_resets: bool) -> str:
    percent = "?" if metric.used_pct is None else f"{metric.used_pct}%"
    mark = _status_mark(metric.used_pct)
    if metric.used is not None and metric.limit is not None and metric.unit == "usd":
        text = f"{mark} {metric.label}: ${metric.used:g} / ${metric.limit:g}"
        if metric.used_pct is not None:
            text += f" ({metric.used_pct}%)"
    elif metric.used is None and metric.limit is not None and metric.unit == "usd":
        text = f"{mark} {metric.label}: cap ${metric.limit:g}"
    elif metric.used is not None and metric.unit == "usd":
        text = f"{mark} {metric.label}: ${metric.used:g}"
        if metric.used_pct is not None:
            text += f" ({metric.used_pct}%)"
    elif metric.used_pct is not None:
        text = f"{mark} {metric.label}: {percent} used"
    elif metric.extra.get("remaining_bonus"):
        text = f"{mark} {metric.label}"
    else:
        text = f"{mark} {metric.label}: ?"
    if always_include_resets and metric.resets_at is not None:
        text += f"  ·  resets {format_slot('reset', metric)}"
    return text


def _relative_fetched(fetched_at: datetime) -> str:
    now = datetime.now()
    stamp = fetched_at.replace(tzinfo=None) if fetched_at.tzinfo else fetched_at
    seconds = int((now - stamp).total_seconds())
    if seconds < 0:
        return fetched_at.strftime("%Y-%m-%d %H:%M")
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return fetched_at.strftime("%Y-%m-%d %H:%M")


def _slot_metric_ids(profile: DisplayProfile) -> set[tuple[str, str]]:
    refs: set[tuple[str, str]] = set()
    for slot in list(profile.icon.slots) + list(profile.tooltip.slots):
        try:
            account_id, metric_id = slot.ref.rsplit(".", 1)
        except ValueError:
            continue
        refs.add((account_id, metric_id))
    return refs


def build_details(profile: DisplayProfile, snapshot: AppSnapshot) -> str:
    settings = profile.details
    slot_refs = _slot_metric_ids(profile) if settings.show == "slots_only" else None

    accounts = list(snapshot.accounts)
    if settings.group_by == "provider":
        by_provider: dict[str, list] = defaultdict(list)
        for account in accounts:
            by_provider[account.provider_id].append(account)
        ordered_groups = sorted(by_provider.items(), key=lambda item: item[0])
    else:
        ordered_groups = [("", accounts)]

    sections: list[str] = []
    for provider_id, group in ordered_groups:
        group_sections: list[str] = []
        for account in group:
            heading = account.display_name
            if settings.show_plan and account.plan:
                heading += f"  ·  {account.plan}"
            if not account.logged_in and not account.error:
                heading += "  ·  signed out"

            lines = [heading]
            metrics = account.metrics
            if slot_refs is not None:
                metrics = [
                    metric
                    for metric in metrics
                    if (account.account_id, metric.id) in slot_refs
                ]
            if settings.metric_order == "label":
                metrics = sorted(metrics, key=lambda metric: metric.label.casefold())
            elif settings.metric_order == "id":
                metrics = sorted(metrics, key=lambda metric: metric.id.casefold())
            elif settings.metric_order == "percent_desc":
                metrics = sorted(
                    metrics,
                    key=lambda metric: (
                        metric.used_pct is None,
                        -(metric.used_pct or 0),
                    ),
                )

            for metric in metrics:
                lines.append(f"  {_format_metric(metric, settings.always_include_resets)}")
            if not metrics and not (settings.show_errors and account.error):
                lines.append("  (no metrics yet)")
            if settings.show_errors and account.error:
                lines.append(f"  ⚠ {account.error}")
            group_sections.append("\n".join(lines))

        if provider_id and group_sections:
            title = provider_id.upper() if len(provider_id) <= 4 else provider_id.title()
            sections.append(f"{title}\n" + "\n\n".join(group_sections))
        else:
            sections.extend(group_sections)

    if not sections:
        sections.append("No accounts enabled.\n\nOpen Accounts in the tray menu to turn some on.")
    if settings.show_fetched_at:
        sections.append(f"Updated {_relative_fetched(snapshot.fetched_at)}")
    return "\n\n".join(sections)
