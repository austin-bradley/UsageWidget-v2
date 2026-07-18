"""Claude Code usage widget: a live system tray icon showing current
session usage at a glance, with week/Fable detail on hover and click.

Data source: `claude -p "/usage" --output-format json`, a zero-cost,
client-side built-in command (no model call, no tokens spent).

Deliberately NOT a floating always-on-top window: a normal tray icon can't
render over fullscreen games and needs no z-order fighting.
"""
import ctypes
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import winreg
from datetime import datetime, timedelta

from PIL import Image, ImageDraw, ImageFont
import pystray

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

POLL_SECONDS = 60
NOTIFY_ICON_SETTINGS = r"Control Panel\NotifyIconSettings"


def _version_key(path):
    ver = os.path.basename(os.path.dirname(path))
    parts = []
    for p in ver.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def find_claude_exe():
    """Locate the Claude Code CLI. Prefers the version bundled with Claude
    Desktop (newest version folder wins); falls back to PATH.

    Claude Desktop ships as an MSIX/Store package, so its writes to %APPDATA%
    are virtualized into a private per-package store. A process launched from
    inside the package's context (e.g. a shell spawned by Claude Desktop) sees
    the CLI at %APPDATA%\\Claude\\claude-code; a normally-launched process --
    which is what this widget is -- sees nothing there and must look in the
    package store instead. Search both, newest version across all roots wins.
    """
    roots = []
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        roots.append(os.path.join(appdata, "Claude", "claude-code"))
    localappdata = os.environ.get("LOCALAPPDATA", "")
    if localappdata:
        roots.extend(glob.glob(os.path.join(
            localappdata, "Packages", "Claude_*", "LocalCache",
            "Roaming", "Claude", "claude-code")))

    candidates = []
    for root in roots:
        candidates.extend(glob.glob(os.path.join(root, "*", "claude.exe")))
    if candidates:
        candidates.sort(key=_version_key, reverse=True)
        return candidates[0]
    on_path = shutil.which("claude")
    if on_path:
        return on_path
    return None


_claude_exe_cache = find_claude_exe()


def get_claude_exe():
    """Return the CLI path, re-resolving if the cached one has vanished
    (Claude Desktop auto-updates and removes old version folders, which
    would otherwise leave us pointing at a deleted claude.exe)."""
    global _claude_exe_cache
    if _claude_exe_cache and os.path.exists(_claude_exe_cache):
        return _claude_exe_cache
    _claude_exe_cache = find_claude_exe()
    return _claude_exe_cache

# The "· resets ..." clause is omitted entirely when a meter reads 0%, so it
# has to be optional -- requiring it made the whole line fail to match and the
# reading silently come back as "?".
def _meter_re(label):
    return re.compile(
        label + r":\s*(\d+)%\s*used"
        r"(?:\s*·\s*resets\s*"
        r"([A-Za-z]{3,9} \d{1,2},\s*\d{1,2}(?::\d{2})?\s*[ap]m)\s*\(([^)]+)\))?"
    )


SESSION_RE = _meter_re(r"Current session")
WEEK_RE = _meter_re(r"Current week \(all models\)")
FABLE_WEEK_RE = _meter_re(r"Current week \(Fable\)")

CLAUDE_JSON = os.path.join(os.path.expanduser("~"), ".claude.json")
CREDENTIALS_JSON = os.path.join(os.path.expanduser("~"), ".claude", ".credentials.json")


def read_account():
    """Read which account the CLI is currently signed in as, straight from the
    CLI's own config. Re-read every poll so switching accounts is reflected
    without restarting the widget.

    These live in the real profile root (not under %APPDATA%), so unlike the
    CLI itself they are readable regardless of package-context virtualization.
    """
    info = {"name": None, "email": None, "plan": None, "logged_in": False}
    try:
        with open(CLAUDE_JSON, encoding="utf-8") as f:
            acct = (json.load(f) or {}).get("oauthAccount") or {}
        info["name"] = acct.get("displayName")
        info["email"] = acct.get("emailAddress")
    except Exception:
        pass
    try:
        with open(CREDENTIALS_JSON, encoding="utf-8") as f:
            oauth = (json.load(f) or {}).get("claudeAiOauth") or {}
        info["plan"] = oauth.get("subscriptionType")
        # expiresAt is epoch milliseconds; the CLI refreshes it on use, so an
        # expired token means stale-but-present creds, not a hard logout.
        info["logged_in"] = bool(oauth.get("accessToken"))
    except Exception:
        pass
    return info


def format_account(info):
    if not info or not info.get("logged_in"):
        return "Not signed in"
    name = info.get("name") or info.get("email") or "Unknown account"
    bits = name
    if info.get("email") and info.get("name"):
        bits += " (%s)" % info["email"]
    if info.get("plan"):
        bits += " · %s" % info["plan"]
    return bits


def _parse_reset(date_str, tz_name):
    # Resolve the timezone, but degrade to naive local time if it can't be
    # found (e.g. tzdata unavailable) rather than failing the whole fetch —
    # the usage percentages matter more than an exact countdown.
    tz = None
    if ZoneInfo:
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = None
    now = datetime.now(tz)
    for fmt in ("%b %d, %I:%M%p", "%b %d, %I%p"):
        try:
            dt = datetime.strptime(date_str, fmt)
            break
        except ValueError:
            continue
    else:
        return None
    dt = dt.replace(year=now.year)
    if tz is not None:
        dt = dt.replace(tzinfo=tz)
    if dt < now - timedelta(days=1):
        dt = dt.replace(year=now.year + 1)
    return dt


def _fmt_countdown(reset_dt):
    if reset_dt is None:
        return "?"
    now = datetime.now(reset_dt.tzinfo) if reset_dt.tzinfo else datetime.now()
    delta = reset_dt - now
    secs = int(delta.total_seconds())
    if secs <= 0:
        return "now"
    h, rem = divmod(secs, 3600)
    m = rem // 60
    if h > 0:
        return f"{h}h{m:02d}m"
    return f"{m}m"


def fetch_usage():
    """Call the zero-cost `/usage` built-in and parse the result text."""
    claude_exe = get_claude_exe()
    if not claude_exe:
        raise RuntimeError(
            "Couldn't find the Claude Code CLI. Install Claude Desktop, "
            "then run it at least once."
        )
    # Belt-and-suspenders no-console-window handling: CREATE_NO_WINDOW alone
    # can fail to spawn from a --windowed (no-console) parent process, since
    # the parent's own stdio handles are null in that case. An explicit
    # hidden STARTUPINFO avoids that.
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    proc = subprocess.run(
        [claude_exe, "-p", "/usage", "--output-format", "json"],
        capture_output=True,
        encoding="utf-8",
        timeout=20,
        stdin=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
        startupinfo=startupinfo,
    )

    if not proc.stdout or not proc.stdout.strip():
        err = (proc.stderr or "").strip()
        raise RuntimeError(err or f"claude exited with code {proc.returncode} and no output")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        snippet = (proc.stderr or proc.stdout or "").strip()[:300]
        raise RuntimeError(snippet or "Unexpected (non-JSON) output from claude")
    text = data.get("result", "")

    if "not logged in" in text.lower():
        raise RuntimeError(
            'Not logged in. Open a terminal and run:\n'
            f'"{claude_exe}" auth login'
        )

    result = {
        "session_pct": None, "session_reset": None,
        "week_pct": None, "week_reset": None,
        "fable_pct": None, "fable_reset": None,
    }

    for key, regex in (("session", SESSION_RE), ("week", WEEK_RE), ("fable", FABLE_WEEK_RE)):
        m = regex.search(text)
        if not m:
            continue
        result[key + "_pct"] = int(m.group(1))
        if m.group(2):
            result[key + "_reset"] = _parse_reset(m.group(2), m.group(3))

    return result


def _find_font(size):
    for path in (r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _color_for_pct(pct):
    if pct is None:
        return (140, 140, 140, 255)
    if pct >= 85:
        return (224, 90, 90, 255)
    if pct >= 60:
        return (224, 180, 70, 255)
    return (110, 200, 120, 255)


def render_icon(session_pct):
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bg = (30, 30, 30, 255)
    d.rounded_rectangle((2, 2, size - 2, size - 2), radius=14, fill=bg)

    text = str(session_pct) if session_pct is not None else "?"
    font_size = 40 if len(text) <= 2 else 30
    font = _find_font(font_size)
    color = _color_for_pct(session_pct)

    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size - tw) / 2 - bbox[0]
    y = (size - th) / 2 - bbox[1]
    d.text((x, y), text, font=font, fill=color)
    return img


def build_tooltip(state, account=None):
    sp = state["session_pct"]
    wp = state["week_pct"]
    fp = state["fable_pct"]
    sc = _fmt_countdown(state["session_reset"])
    who = (account or {}).get("name") or (account or {}).get("email") or "Claude usage"
    lines = [
        who,
        f"Session: {sp if sp is not None else '?'}%  (resets {sc})",
        f"Week: {wp if wp is not None else '?'}%  /  Fable: {fp if fp is not None else '?'}%",
    ]
    return "\n".join(lines)[:127]  # Windows tray tooltip length limit


def build_details_text(state, account=None):
    sp = state["session_pct"]
    wp = state["week_pct"]
    fp = state["fable_pct"]
    sc = _fmt_countdown(state["session_reset"])
    wc = _fmt_countdown(state["week_reset"])
    fc = _fmt_countdown(state["fable_reset"])
    return (
        f"Account: {format_account(account)}\n\n"
        f"Session: {sp if sp is not None else '?'}% used, resets in {sc}\n"
        f"Week (all models): {wp if wp is not None else '?'}% used, resets in {wc}\n"
        f"Week (Fable): {fp if fp is not None else '?'}% used, resets in {fc}"
    )


def _notify_icon_key():
    """Find this exe's entry under Windows 11's tray-icon settings. The key is
    created by Explorer the first time the icon appears, and keyed by the exe
    path that registered it."""
    me = os.path.normcase(os.path.abspath(
        sys.executable if getattr(sys, "frozen", False) else __file__))
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, NOTIFY_ICON_SETTINGS) as root:
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(root, i)
            except OSError:
                return None
            i += 1
            try:
                with winreg.OpenKey(root, sub) as k:
                    path, _ = winreg.QueryValueEx(k, "ExecutablePath")
                if os.path.normcase(path) == me:
                    return sub
            except OSError:
                continue


def get_always_visible():
    try:
        sub = _notify_icon_key()
        if not sub:
            return False
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, NOTIFY_ICON_SETTINGS + "\\" + sub) as k:
            return bool(winreg.QueryValueEx(k, "IsPromoted")[0])
    except OSError:
        return False


def set_always_visible(value):
    """Toggle whether the icon sits on the taskbar or in the overflow drawer.
    Explorer owns this setting; it re-reads the key when the tray is next
    rebuilt, so the icon may not move until the icon is re-registered."""
    sub = _notify_icon_key()
    if not sub:
        return False
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, NOTIFY_ICON_SETTINGS + "\\" + sub,
                        0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "IsPromoted", 0, winreg.REG_DWORD, 1 if value else 0)
    return True


class UsageTray:
    def __init__(self):
        self.state = {
            "session_pct": None, "session_reset": None,
            "week_pct": None, "week_reset": None,
            "fable_pct": None, "fable_reset": None,
        }
        self.last_error = None
        self.account = read_account()
        self._stop = False

        menu = pystray.Menu(
            pystray.MenuItem("Show details", self._on_details, default=True),
            pystray.MenuItem("Refresh now", self._on_refresh),
            pystray.MenuItem(
                "Always visible",
                self._on_toggle_visible,
                checked=lambda item: get_always_visible(),
            ),
            pystray.MenuItem("Quit", self._on_quit),
        )
        self.icon = pystray.Icon("claude-usage", render_icon(None), "Claude usage: loading…", menu)

    def _on_details(self, icon, item):
        if self.last_error and self.state["session_pct"] is None:
            text = (f"Account: {format_account(self.account)}\n\n"
                    f"Couldn't fetch usage:\n{self.last_error}")
        else:
            text = build_details_text(self.state, self.account)
        threading.Thread(target=self._show_messagebox, args=(text,), daemon=True).start()

    def _on_toggle_visible(self, icon, item):
        want = not get_always_visible()
        if not set_always_visible(want):
            self._show_messagebox(
                "Couldn't find this app's tray-icon setting yet.\n\n"
                "Windows creates it the first time the icon appears. Try again "
                "in a moment, or set it via Settings > Personalization > "
                "Taskbar > Other system tray icons.")

    def _show_messagebox(self, text):
        ctypes.windll.user32.MessageBoxW(0, text, "Claude usage", 0x40)  # MB_ICONINFORMATION

    def _on_refresh(self, icon, item):
        self.refresh_async()

    def _on_quit(self, icon, item):
        self._stop = True
        icon.stop()

    def refresh_async(self):
        threading.Thread(target=self._refresh_once, daemon=True).start()

    def _refresh_once(self):
        try:
            self.account = read_account()
        except Exception:
            pass
        try:
            data = fetch_usage()
            self.last_error = None
            self.state = data
        except Exception as e:
            self.last_error = str(e)
        self._render()

    def _render(self):
        sp = self.state["session_pct"]
        self.icon.icon = render_icon(sp)
        if self.last_error and sp is None:
            self.icon.title = "Claude usage: unavailable"
        else:
            self.icon.title = build_tooltip(self.state, self.account)

    def _poll_loop(self):
        while not self._stop:
            # A failure here must never kill the poll thread: a dead thread
            # freezes the first error on screen forever, with no way back.
            try:
                self._refresh_once()
            except Exception as e:
                self.last_error = str(e)
            for _ in range(POLL_SECONDS):
                if self._stop:
                    return
                time.sleep(1)

    def run(self):
        threading.Thread(target=self._poll_loop, daemon=True).start()
        self.icon.run()


def main():
    UsageTray().run()


if __name__ == "__main__":
    main()
