"""Tiny rotating log under %APPDATA%\\UsageWidget\\widget.log."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

_MAX_BYTES = 512_000


def log_path() -> Path:
    return Path(os.environ["APPDATA"]) / "UsageWidget" / "widget.log"


def log_event(message: str) -> None:
    path = log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.stat().st_size > _MAX_BYTES:
            rotated = path.with_suffix(".log.1")
            try:
                if rotated.exists():
                    rotated.unlink()
                path.replace(rotated)
            except OSError:
                pass
        line = f"{datetime.now().isoformat(sep=' ', timespec='seconds')} {message}\n"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass
