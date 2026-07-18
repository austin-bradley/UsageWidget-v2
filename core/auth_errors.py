"""Shared auth-failure heuristics for poll merge and providers."""
from __future__ import annotations

import re

# Prefer specific phrases — avoid bare "login" matching unrelated messages.
_AUTH_ERROR_MARKERS = (
    "not logged in",
    "not signed in",
    "signed out",
    "unauthorized",
    "forbidden",
    "authentication",
    "access token",
    "token not found",
    "token file not found",
    "token expired",
    "couldn't find the claude",
    "auth not found",
    "no api_key",
    "api_key but no",
    "api key is set",
    "codex login",
    "gemini cli not found",
    "gpt auth not found",
)

_AUTH_STATUS_RE = re.compile(
    r"(?:^|[\s:;\(\[\{])(?:http\s*)?(?:status\s*)?(?:error\s*)?40[13](?:\b|[\s:;\.,\)\]\}]|$)",
    re.IGNORECASE,
)


def is_auth_error(error: str | None) -> bool:
    """True when the failure likely means credentials are gone/invalid."""
    if not error:
        return False
    text = error.casefold()
    if any(marker in text for marker in _AUTH_ERROR_MARKERS):
        return True
    return bool(_AUTH_STATUS_RE.search(error))
