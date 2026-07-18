from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Metric:
    id: str
    label: str
    used_pct: int | None = None
    used: float | None = None
    limit: float | None = None
    unit: str | None = None
    resets_at: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class AccountSnapshot:
    account_id: str
    provider_id: str
    display_name: str
    logged_in: bool
    plan: str | None
    metrics: list[Metric]
    error: str | None = None


@dataclass
class AppSnapshot:
    fetched_at: datetime
    accounts: list[AccountSnapshot]


@dataclass
class AuthConfig:
    mode: str = "auto"  # auto | api_key | token_file
    api_key: str | None = None
    token_file: str | None = None  # expanded for runtime
    claude_home: str | None = None  # expanded for runtime
    # Original YAML tokens (e.g. "~/...") so save_config can round-trip without expanding.
    token_file_raw: str | None = None
    claude_home_raw: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class AccountConfig:
    id: str
    provider: str
    label: str | None = None
    enabled: bool = True
    auth: AuthConfig = field(default_factory=AuthConfig)
    poll_seconds: int | None = None


@dataclass
class DisplaySlot:
    ref: str  # "account_id.metric_id"
    show: str = "percent"
    label: str | None = None


@dataclass
class IconDisplay:
    mode: str = "composite"
    layout: str = "split"
    max_slots: int = 3
    rotate_seconds: int = 8
    color_by: str = "percent"
    thresholds: dict[str, int] = field(default_factory=lambda: {"warn": 60, "critical": 85})
    show_labels: bool = False
    slots: list[DisplaySlot] = field(default_factory=list)


@dataclass
class TooltipDisplay:
    format: str = "compact"
    max_chars: int = 127
    slots: list[DisplaySlot] = field(default_factory=list)


@dataclass
class DetailsDisplay:
    show: str = "all_enabled_accounts"
    group_by: str = "account"
    metric_order: str = "as_returned"
    always_include_resets: bool = True
    show_errors: bool = True
    show_plan: bool = True
    show_fetched_at: bool = True


@dataclass
class DisplayProfile:
    icon: IconDisplay = field(default_factory=IconDisplay)
    tooltip: TooltipDisplay = field(default_factory=TooltipDisplay)
    details: DetailsDisplay = field(default_factory=DetailsDisplay)


@dataclass
class AppConfig:
    poll_seconds: int = 60
    app_name: str = "Usage Widget v2"
    accounts: list[AccountConfig] = field(default_factory=list)
    active_profile: str = "default"
    profiles: dict[str, DisplayProfile] = field(default_factory=dict)
