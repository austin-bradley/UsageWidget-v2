"""Usage Widget v2 entrypoint."""
from __future__ import annotations

import ctypes
import sys
import traceback

from core.app_log import log_event
from core.config import ensure_config
from core.version import APP_NAME
from tray.app import UsageTray
from tray.single_instance import ensure_single_instance, release_single_instance


def _fatal(title: str, message: str) -> None:
    try:
        log_event(f"fatal: {message}")
    except Exception:
        pass
    ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)


def main() -> int:
    if not ensure_single_instance(APP_NAME):
        return 0
    try:
        cfg = ensure_config()
        UsageTray(cfg).run()
        return 0
    except Exception as error:
        detail = f"{error}\n\n{traceback.format_exc()[-1200:]}"
        _fatal(APP_NAME, f"Couldn't start:\n\n{error}")
        try:
            log_event(detail.replace("\n", " | "))
        except Exception:
            pass
        return 1
    finally:
        release_single_instance()


if __name__ == "__main__":
    sys.exit(main())
