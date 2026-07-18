from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml

from core.models import (
    AccountConfig,
    AppConfig,
    AuthConfig,
    DetailsDisplay,
    DisplayProfile,
    DisplaySlot,
    IconDisplay,
    TooltipDisplay,
)
from providers.registry import PROVIDERS


def config_path() -> Path:
    return Path(os.environ["APPDATA"]) / "UsageWidget" / "config.yaml"


def example_config_path() -> Path:
    if getattr(sys, "frozen", False):
        # One-file PyInstaller extracts bundled datas into _MEIPASS.
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / "config.example.yaml"
        return Path(sys.executable).parent / "config.example.yaml"
    return Path(__file__).resolve().parent.parent / "config.example.yaml"


def parse_slot(raw: Any) -> DisplaySlot:
    if isinstance(raw, str):
        return DisplaySlot(ref=raw, show="percent")
    return DisplaySlot(
        ref=raw["ref"],
        show=raw.get("show", "percent"),
        label=raw.get("label"),
    )


def _expand_path(value: str | None) -> str | None:
    if value is None:
        return None
    return os.path.expanduser(value)


def _parse_auth(raw: dict[str, Any] | None) -> AuthConfig:
    if not raw:
        return AuthConfig()
    known = {"mode", "api_key", "token_file", "claude_home"}
    extra = {k: v for k, v in raw.items() if k not in known}
    token_raw = raw.get("token_file")
    home_raw = raw.get("claude_home")
    return AuthConfig(
        mode=raw.get("mode", "auto"),
        api_key=raw.get("api_key"),
        token_file=_expand_path(token_raw),
        claude_home=_expand_path(home_raw),
        token_file_raw=token_raw,
        claude_home_raw=home_raw,
        extra=extra,
    )


def _parse_account(raw: dict[str, Any]) -> AccountConfig:
    return AccountConfig(
        id=raw["id"],
        provider=raw["provider"],
        label=raw.get("label"),
        enabled=raw.get("enabled", True),
        auth=_parse_auth(raw.get("auth")),
        poll_seconds=raw.get("poll_seconds"),
    )


def _parse_icon(raw: dict[str, Any] | None) -> IconDisplay:
    if not raw:
        return IconDisplay()
    return IconDisplay(
        mode=raw.get("mode", "composite"),
        layout=raw.get("layout", "split"),
        max_slots=raw.get("max_slots", 3),
        rotate_seconds=raw.get("rotate_seconds", 8),
        color_by=raw.get("color_by", "percent"),
        thresholds=raw.get("thresholds", {"warn": 60, "critical": 85}),
        show_labels=raw.get("show_labels", False),
        slots=[parse_slot(s) for s in raw.get("slots", [])],
    )


def _parse_tooltip(raw: dict[str, Any] | None) -> TooltipDisplay:
    if not raw:
        return TooltipDisplay()
    return TooltipDisplay(
        format=raw.get("format", "compact"),
        max_chars=raw.get("max_chars", 127),
        slots=[parse_slot(s) for s in raw.get("slots", [])],
    )


def _parse_details(raw: dict[str, Any] | None) -> DetailsDisplay:
    if not raw:
        return DetailsDisplay()
    return DetailsDisplay(
        show=raw.get("show", "all_enabled_accounts"),
        group_by=raw.get("group_by", "account"),
        metric_order=raw.get("metric_order", "as_returned"),
        always_include_resets=raw.get("always_include_resets", True),
        show_errors=raw.get("show_errors", True),
        show_plan=raw.get("show_plan", True),
        show_fetched_at=raw.get("show_fetched_at", True),
    )


def _parse_profile(raw: dict[str, Any] | None) -> DisplayProfile:
    if not raw:
        return DisplayProfile()
    return DisplayProfile(
        icon=_parse_icon(raw.get("icon")),
        tooltip=_parse_tooltip(raw.get("tooltip")),
        details=_parse_details(raw.get("details")),
    )


def _parse_config(data: dict[str, Any]) -> AppConfig:
    profiles_raw = data.get("profiles", {})
    profiles = {name: _parse_profile(prof) for name, prof in profiles_raw.items()}
    return AppConfig(
        poll_seconds=data.get("poll_seconds", 60),
        app_name=data.get("app_name", "Usage Widget v2"),
        accounts=[_parse_account(a) for a in data.get("accounts", [])],
        active_profile=data.get("active_profile", "default"),
        profiles=profiles,
    )


def load_config(path: Path | None = None) -> AppConfig:
    path = path or config_path()
    try:
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as error:
        raise RuntimeError(f"Invalid YAML in {path}: {error}") from error
    except OSError as error:
        raise RuntimeError(f"Couldn't read config {path}: {error}") from error
    if not isinstance(data, dict):
        raise RuntimeError(f"Config root must be a mapping: {path}")
    try:
        cfg = _parse_config(data)
    except KeyError as error:
        raise RuntimeError(
            f"Config {path} is missing required field {error}"
        ) from error
    except (TypeError, ValueError) as error:
        raise RuntimeError(f"Config {path} is invalid: {error}") from error

    account_ids = [account.id for account in cfg.accounts]
    if len(account_ids) != len(set(account_ids)):
        raise RuntimeError(f"Config {path} has duplicate account ids")
    if cfg.profiles and cfg.active_profile not in cfg.profiles:
        raise RuntimeError(
            f"Config {path}: active_profile {cfg.active_profile!r} "
            f"not found in profiles"
        )
    for account in cfg.accounts:
        if account.poll_seconds is not None and int(account.poll_seconds) < 1:
            raise RuntimeError(
                f"Config {path}: account {account.id} poll_seconds must be >= 1"
            )
    return cfg


def _slot_to_dict(slot: DisplaySlot) -> dict[str, Any] | str:
    if slot.show == "percent" and slot.label is None:
        return slot.ref
    result: dict[str, Any] = {"ref": slot.ref, "show": slot.show}
    if slot.label is not None:
        result["label"] = slot.label
    return result


def _auth_to_dict(auth: AuthConfig) -> dict[str, Any]:
    result: dict[str, Any] = {"mode": auth.mode}
    if auth.api_key is not None:
        result["api_key"] = auth.api_key
    token_out = auth.token_file_raw if auth.token_file_raw is not None else auth.token_file
    home_out = auth.claude_home_raw if auth.claude_home_raw is not None else auth.claude_home
    if token_out is not None:
        result["token_file"] = token_out
    if home_out is not None:
        result["claude_home"] = home_out
    result.update(auth.extra)
    return result


def _account_to_dict(account: AccountConfig) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": account.id,
        "provider": account.provider,
        "enabled": account.enabled,
        "auth": _auth_to_dict(account.auth),
    }
    if account.label is not None:
        result["label"] = account.label
    if account.poll_seconds is not None:
        result["poll_seconds"] = account.poll_seconds
    return result


def _icon_to_dict(icon: IconDisplay) -> dict[str, Any]:
    return {
        "mode": icon.mode,
        "layout": icon.layout,
        "max_slots": icon.max_slots,
        "rotate_seconds": icon.rotate_seconds,
        "color_by": icon.color_by,
        "thresholds": dict(icon.thresholds),
        "show_labels": icon.show_labels,
        "slots": [_slot_to_dict(s) for s in icon.slots],
    }


def _tooltip_to_dict(tooltip: TooltipDisplay) -> dict[str, Any]:
    return {
        "format": tooltip.format,
        "max_chars": tooltip.max_chars,
        "slots": [_slot_to_dict(s) for s in tooltip.slots],
    }


def _details_to_dict(details: DetailsDisplay) -> dict[str, Any]:
    return {
        "show": details.show,
        "group_by": details.group_by,
        "metric_order": details.metric_order,
        "always_include_resets": details.always_include_resets,
        "show_errors": details.show_errors,
        "show_plan": details.show_plan,
        "show_fetched_at": details.show_fetched_at,
    }


def _profile_to_dict(profile: DisplayProfile) -> dict[str, Any]:
    return {
        "icon": _icon_to_dict(profile.icon),
        "tooltip": _tooltip_to_dict(profile.tooltip),
        "details": _details_to_dict(profile.details),
    }


def _config_to_dict(cfg: AppConfig) -> dict[str, Any]:
    return {
        "poll_seconds": cfg.poll_seconds,
        "app_name": cfg.app_name,
        "accounts": [_account_to_dict(a) for a in cfg.accounts],
        "active_profile": cfg.active_profile,
        "profiles": {name: _profile_to_dict(prof) for name, prof in cfg.profiles.items()},
    }


def save_config(cfg: AppConfig, path: Path | None = None) -> None:
    """Persist config.

    Tray toggles should prefer ``patch_config_toggles`` so hand-edited YAML
    (paths with ``~``, display sections) is not rebuilt from dataclasses.
    Full dumps still write original path tokens via ``*_raw`` fields when present.
    Comments are not preserved (PyYAML); edit carefully or avoid tray toggles
    if you rely on comments.
    """
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _config_to_dict(cfg)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def patch_config_toggles(cfg: AppConfig, path: Path | None = None) -> None:
    """Update only ``active_profile`` and per-account ``enabled`` in existing YAML.

    Loads the on-disk document, patches those fields, and writes it back so
    ``token_file`` / ``claude_home`` strings (including ``~``) and display
    sections are not reconstructed from runtime-expanded dataclasses.
    """
    path = path or config_path()
    if not path.exists():
        save_config(cfg, path)
        return
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    data["active_profile"] = cfg.active_profile
    enabled_by_id = {a.id: a.enabled for a in cfg.accounts}
    for acct in data.get("accounts") or []:
        if isinstance(acct, dict) and acct.get("id") in enabled_by_id:
            acct["enabled"] = enabled_by_id[acct["id"]]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def patch_config_profile_display(cfg: AppConfig, path: Path | None = None) -> None:
    """Update only the active profile's ``icon`` and ``tooltip`` in existing YAML."""
    path = path or config_path()
    if not path.exists():
        save_config(cfg, path)
        return
    profile = cfg.profiles.get(cfg.active_profile)
    if profile is None:
        return
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    profiles = data.setdefault("profiles", {})
    if not isinstance(profiles, dict):
        profiles = {}
        data["profiles"] = profiles
    name = cfg.active_profile
    entry = profiles.get(name) if isinstance(profiles.get(name), dict) else {}
    entry = dict(entry)
    entry["icon"] = _icon_to_dict(profile.icon)
    entry["tooltip"] = _tooltip_to_dict(profile.tooltip)
    if "details" not in entry:
        entry["details"] = _details_to_dict(profile.details)
    profiles[name] = entry
    data["active_profile"] = cfg.active_profile
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def _enable_discovered_accounts(cfg: AppConfig, path: Path) -> AppConfig:
    """On first-run seed, enable optional accounts whose providers are discoverable.

    Keeps the example quiet by default, but turns on Cursor/GPT/Gemini (etc.)
    when local login evidence is already present.
    """
    changed = False
    for account in cfg.accounts:
        if account.enabled:
            continue
        provider = PROVIDERS.get(account.provider)
        if provider is None:
            continue
        try:
            found = provider.discover_accounts()
        except Exception:
            continue
        # Only enable when discovery returns this exact account id
        # (avoids turning on claude-work just because personal Claude is logged in).
        suggested_ids = {item.suggested_id for item in found}
        if account.id in suggested_ids:
            account.enabled = True
            changed = True
    if changed:
        patch_config_toggles(cfg, path)
    return cfg


def ensure_config() -> AppConfig:
    path = config_path()
    created = False
    if not path.exists():
        example = example_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not example.exists():
            raise FileNotFoundError(f"Example config not found: {example}")
        shutil.copy2(example, path)
        created = True
    cfg = load_config(path)
    if created:
        cfg = _enable_discovered_accounts(cfg, path)
    return cfg
