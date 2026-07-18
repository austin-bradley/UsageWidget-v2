"""Usage Widget v2 entrypoint."""
from core.config import ensure_config
from tray.app import UsageTray


def main():
    cfg = ensure_config()
    UsageTray(cfg).run()


if __name__ == "__main__":
    main()
