from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

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
