from __future__ import annotations

from core.models import AppSnapshot, DisplayProfile, Metric
from display.format_value import format_slot


def _format_metric(metric: Metric, always_include_resets: bool) -> str:
    percent = "?" if metric.used_pct is None else str(metric.used_pct)
    text = f"{metric.label}: {percent}% used"
    if always_include_resets or metric.resets_at is not None:
        text += f", resets in {format_slot('reset', metric)}"
    return text


def build_details(profile: DisplayProfile, snapshot: AppSnapshot) -> str:
    settings = profile.details
    sections: list[str] = []

    for account in snapshot.accounts:
        heading = account.display_name
        if settings.show_plan and account.plan:
            heading += f" · {account.plan}"

        lines = [heading]
        metrics = account.metrics
        if settings.metric_order == "label":
            metrics = sorted(metrics, key=lambda metric: metric.label.casefold())
        elif settings.metric_order == "id":
            metrics = sorted(metrics, key=lambda metric: metric.id.casefold())

        for metric in metrics:
            lines.append(f"  {_format_metric(metric, settings.always_include_resets)}")
        if not metrics and not (settings.show_errors and account.error):
            lines.append("  No metrics")
        if settings.show_errors and account.error:
            lines.append(f"  Error: {account.error}")
        sections.append("\n".join(lines))

    if not sections:
        sections.append("No accounts")
    if settings.show_fetched_at:
        fetched = snapshot.fetched_at.isoformat(sep=" ", timespec="seconds")
        sections.append(f"Fetched: {fetched}")
    return "\n\n".join(sections)
