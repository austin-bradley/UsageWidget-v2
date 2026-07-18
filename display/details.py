from __future__ import annotations

from collections import defaultdict

from core.models import AppSnapshot, DisplayProfile, Metric
from display.format_value import format_slot


def _format_metric(metric: Metric, always_include_resets: bool) -> str:
    percent = "?" if metric.used_pct is None else str(metric.used_pct)
    text = f"{metric.label}: {percent}% used"
    # Only show countdown when we have a real reset time (never "resets in ?").
    if always_include_resets and metric.resets_at is not None:
        text += f", resets in {format_slot('reset', metric)}"
    return text


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
                heading += f" · {account.plan}"

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
                lines.append("  No metrics")
            if settings.show_errors and account.error:
                lines.append(f"  Error: {account.error}")
            group_sections.append("\n".join(lines))

        if provider_id and group_sections:
            sections.append(f"[{provider_id}]\n" + "\n\n".join(group_sections))
        else:
            sections.extend(group_sections)

    if not sections:
        sections.append("No accounts")
    if settings.show_fetched_at:
        fetched = snapshot.fetched_at.isoformat(sep=" ", timespec="seconds")
        sections.append(f"Fetched: {fetched}")
    return "\n\n".join(sections)
