"""
picker.py — Themed rofi dmenu listing live Claude sessions.
Selecting one focuses its kitty window via hyprctl.

Rows are grouped by tier (waiting → busy → idle); the coloured state glyph
marks the tier, so no text label column is spent on it.

rofi is called with:
  -format i        → returns 0-based index of selected row
  -markup-rows     → Pango markup in display text
  -p "CC"          → prompt label
"""

import subprocess
from html import escape
from zlib import crc32
import sys
import time
from pathlib import Path

from .sessions import list_sessions, read_cache, Session, rel_time
from .glyphs import COLOR_DIM, COLOR_TEXT, COLOR_ACCENT, CLAUDE_LOGO, pango, state_glyph, state_color

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
ROFI_THEME = str(_PROJECT_ROOT / "rofi" / "theme.rasi")

_TIER_ORDER = ["waiting", "busy", "idle"]

# ponytail: row is a fixed-width monospace grid. ROW_CHARS must match the
# theme's window width (rofi/theme.rasi: width in ch, minus element padding).
# Widen both together if titles feel cramped.
ROW_CHARS = 70
_CWD_W    = 14   # folder basename, mid-truncated
_AGE_W    = 4    # rel_time(): "now" / "59m" / "23h" / "120d"

# Config tag colours. Avoids the state colours (green/amber/grey) and the red accent.
# ponytail: crc32 % len, so two configs can collide; reorder or add colours if yours do.
_CONFIG_COLORS = ["#89b4fa", "#cba6f7", "#94e2d5", "#f5c2e7", "#89dceb", "#b4befe"]


def _config_color(label: str) -> str:
    return _CONFIG_COLORS[crc32(label.encode()) % len(_CONFIG_COLORS)]  # stable across runs, unlike hash()


def _mid_truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    keep_start = (max_len - 1) // 2
    keep_end   = max_len - 1 - keep_start
    return f"{text[:keep_start]}…{text[-keep_end:]}"


def _end_truncate(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[:max_len - 1] + "…"


def _shorten(path: str) -> str:
    home = str(Path.home())
    if path == home:
        return "~"
    if path.startswith(home + "/"):
        return "~" + path[len(home):]
    return path


def _cwd_display(cwd: str) -> str:
    """Basename of cwd. Home dir shown as ~."""
    return "~" if cwd == str(Path.home()) else Path(cwd).name


def _session_row(s: Session, cfg_w: int) -> str:
    """
    One grid row:  glyph  title…  cwd  age  config
    Never truncated: glyph, age, config (short, and what tells rows apart).
    Truncated: cwd (mid, keeps both ends of the name), title (end, reads like a sentence)
    and title takes whatever width is left.
    """
    title_w = ROW_CHARS - (1 + 2) - 2 - _CWD_W - 2 - _AGE_W - 2 - cfg_w
    title = _end_truncate(s.title or s.session_id[:8], title_w).ljust(title_w)
    cwd   = _mid_truncate(_cwd_display(s.cwd), _CWD_W).ljust(_CWD_W)
    age   = rel_time(s.status_updated_at if s.status == "waiting" else s.updated_at).rjust(_AGE_W)

    display = "  ".join([
        pango(state_glyph(s.status), state_color(s.status)),
        escape(title),
        pango(escape(cwd), COLOR_DIM),
        pango(age, COLOR_DIM),
        pango(escape(s.config.ljust(cfg_w)), _config_color(s.config)),
    ])

    # Hidden meta searched by rofi but not shown
    meta_parts: list[str] = []
    if s.git_repo:
        meta_parts.append(s.git_repo)
    meta_parts.extend(_shorten(p) for p in s.context_paths)
    if meta_parts:
        return f"{display}\x00info\x1f{'  '.join(meta_parts)}"
    return display


def _demo_sessions() -> list[Session]:
    """Sample sessions with realistic staggered ages, for screenshots/testing."""
    now = int(time.time() * 1000)
    mins = 60_000
    hw = "/home/proxima/Desktop/saas/healthyweek"
    # (status, title, name, cwd, git_repo, age_ms)  age → status_updated_at/updated_at
    specs = [
        ("waiting", "Wire Dodo Payments checkout webhook",     "hw-api-3f",  f"{hw}/apps/api",       "healthyweek", 18 * mins),
        ("waiting", "Confirm D1 migration for pantry table",   "hw-db-a1",   f"{hw}/packages/db",    "healthyweek",  6 * mins),
        ("busy",    "Implement meal assembler algorithm",      "hw-core-1c", f"{hw}/packages/core",  "healthyweek",  25_000),
        ("busy",    "Build onboarding diet/taste flow",        "hw-web-9d",  f"{hw}/apps/web",       "healthyweek",  3 * mins),
        ("idle",    "Draft Instamart MCP integration doc",     "hw-docs-77", f"{hw}/docs",           "healthyweek", 42 * mins),
        ("idle",    "Tune Gemini Flash chat assistant prompt", "hw-chat-b4", f"{hw}/apps/api",       "healthyweek",  4 * 60 * mins),
    ]
    out: list[Session] = []
    for i, (status, title, name, cwd, repo, age) in enumerate(specs):
        t = now - age
        out.append(Session(
            pid=100000 + i, session_id=f"demo-{i:04d}-demo-demo-demodemodemo",
            cwd=cwd, status=status, title=title, name=name, version="2.1.199",
            address=None, workspace=str((i % 3) + 1),
            status_updated_at=t, updated_at=t, started_at=t - 30 * mins,
            git_repo=repo, context_paths=[],
        ))
    return out


def _focus_window(address: str) -> None:
    subprocess.run(
        ["hyprctl", "dispatch", "focuswindow", f"address:{address}"],
        stderr=subprocess.DEVNULL,
    )


def run(demo: bool = False) -> None:
    sessions = _demo_sessions() if demo else (read_cache() or list_sessions())

    if not sessions:
        _show_rofi([pango("no active claude sessions", COLOR_DIM)], {})
        return

    # Group sessions by tier, preserving sorted order
    groups: dict[str, list[Session]] = {t: [] for t in _TIER_ORDER}
    for s in sessions:
        groups.get(s.status, groups["idle"]).append(s)

    # Build flat row list + index map: row_idx → Session | None (None = header)
    rows: list[str] = []
    index_map: dict[int, Session | None] = {}
    cfg_w = max(len(s.config) for s in sessions)

    for tier in _TIER_ORDER:
        for s in groups[tier]:
            index_map[len(rows)] = s
            rows.append(_session_row(s, cfg_w))

    idx = _show_rofi(rows, index_map)
    if idx is None:
        return

    s = index_map.get(idx)
    if s is None:
        return

    if s.address:
        _focus_window(s.address)
    else:
        _notify(f"ccmanager: no window found for '{s.title}'")


def _show_rofi(rows: list[str], index_map: dict) -> int | None:
    """Pipe rows to rofi -dmenu, return selected index or None."""
    cmd = [
        "rofi", "-dmenu",
        "-i",
        "-markup-rows",
        "-format", "i",
        "-p", CLAUDE_LOGO,
        "-theme", ROFI_THEME,
    ]

    try:
        result = subprocess.run(
            cmd,
            input="\n".join(rows),
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return None
    except FileNotFoundError:
        sys.exit("ccmanager: rofi not found")

    if result.returncode != 0:
        return None

    out = result.stdout.strip()
    if not out:
        return None

    try:
        return int(out)
    except ValueError:
        return None


def _notify(msg: str) -> None:
    try:
        subprocess.run(["notify-send", "ccmanager", msg], timeout=3, stderr=subprocess.DEVNULL)
    except Exception:
        pass
