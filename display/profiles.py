from __future__ import annotations

from core.models import AppConfig, DisplayProfile


def get_active_profile(config: AppConfig) -> DisplayProfile:
    active = config.profiles.get(config.active_profile)
    if active is not None:
        return active
    default = config.profiles.get("default")
    if default is not None:
        return default
    return DisplayProfile()
