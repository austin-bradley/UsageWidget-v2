from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from core.auth_errors import is_auth_error
from core.models import AccountConfig, AccountSnapshot


@dataclass
class DiscoveredAccount:
    suggested_id: str
    display_name: str
    auth_hints: dict


class Provider(Protocol):
    id: str

    def discover_accounts(self) -> list[DiscoveredAccount]: ...
    def fetch(self, account: AccountConfig) -> AccountSnapshot: ...


def resolve_auth_path(path: str | None) -> str | None:
    if not path:
        return None
    return os.path.expanduser(path)


def auth_mode(auth) -> str:
    return (getattr(auth, "mode", None) or "auto").strip().lower()


def auth_preflight(auth) -> str | None:
    """Return an error string if auth.mode requirements are unmet."""
    mode = auth_mode(auth)
    if mode not in ("auto", "api_key", "token_file"):
        return f"Unknown auth.mode: {getattr(auth, 'mode', None)!r}"
    if mode == "api_key" and not getattr(auth, "api_key", None):
        return "auth.mode is api_key but no api_key is set"
    if mode == "token_file" and not getattr(auth, "token_file", None):
        return "auth.mode is token_file but no token_file is set"
    return None


def error_snapshot(
    account: AccountConfig,
    provider_id: str,
    error: object,
    *,
    display_name: str | None = None,
    plan: str | None = None,
    had_credentials: bool = False,
) -> AccountSnapshot:
    """Build a failed fetch snapshot with auth-aware ``logged_in``."""
    message = str(error)
    auth_fail = is_auth_error(message)
    return AccountSnapshot(
        account_id=account.id,
        provider_id=provider_id,
        display_name=display_name or account.label or account.id,
        logged_in=bool(had_credentials) and not auth_fail,
        plan=plan,
        metrics=[],
        error=message,
    )
