"""
picker.py — Themed rofi dmenu listing live Claude sessions.
Selecting one focuses its kitty window via hyprctl.

Rows are grouped by tier (waiting → idle → busy). The first row in each
tier carries a dim label prefix so tiers are visually distinct without
adding non-selectable separator rows.

rofi is called with:
  -format i        → returns 0-based index of selected row
  -markup-rows     → Pango markup in display text
  -p "CC"          → prompt label
"""

import subprocess
import sys
from pathlib import Path

from .sessions import list_sessions, read_cache, Session, rel_time
from .glyphs import COLOR_DIM, COLOR_TEXT, COLOR_ACCENT, CLAUDE_LOGO, pango, state_glyph, state_color

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
ROFI_THEME = str(_PROJECT_ROOT / "rofi" / "theme.rasi")

_TIER_LABELS = {
    "waiting": "needs you",
    "busy":    "running",
    "idle":    "idle",
}
_TIER_ORDER = ["waiting", "busy", "idle"]

def _mid_truncate(text: str, max_len: int = 35) -> str:
    if len(text) <= max_len:
        return text
    keep_start = (max_len - 1) // 2
    keep_end   = max_len - 1 - keep_start
    return f"{text[:keep_start]}…{text[-keep_end:]}"



def _shorten(path: str) -> str:
    home = str(Path.home())
    if path == home:
        return "~"
    if path.startswith(home + "/"):
        return "~" + path[len(home):]
    return path


def _cwd_display(cwd: str) -> str:
    """Basename of cwd, truncated. Home dir shown as ~."""
    home = str(Path.home())
    if cwd == home:
        return "~"
    return _mid_truncate(Path(cwd).name, 20)


def _session_row(s: Session, col: str = "") -> str:
    """col: fixed-width prefix string (tier label or spaces), len == _PREFIX_W."""
    glyph    = pango(state_glyph(s.status), state_color(s.status))
    title    = _mid_truncate(s.title or s.session_id[:8])
    cwd_dim  = pango(_cwd_display(s.cwd), COLOR_DIM)
    hint     = (f"waiting {rel_time(s.status_updated_at)}"
                if s.status == "waiting" else rel_time(s.updated_at))
    hint_dim = pango(hint, COLOR_DIM)
    prefix   = pango(col, "#3a3a4e")
    display  = f"{prefix}{glyph}  {title}  {cwd_dim}  {hint_dim}"

    # Hidden meta searched by rofi but not shown
    meta_parts: list[str] = []
    if s.git_repo:
        meta_parts.append(s.git_repo)
    meta_parts.extend(_shorten(p) for p in s.context_paths)
    if meta_parts:
        return f"{display}\x00info\x1f{'  '.join(meta_parts)}"
    return display


def _focus_window(address: str) -> None:
    subprocess.run(
        ["hyprctl", "dispatch", "focuswindow", f"address:{address}"],
        stderr=subprocess.DEVNULL,
    )


def run() -> None:
    sessions = read_cache() or list_sessions()

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

    for tier in _TIER_ORDER:
        tier_sessions = groups[tier]
        if not tier_sessions:
            continue
        label = _TIER_LABELS.get(tier, tier)
        for s in tier_sessions:
            index_map[len(rows)] = s
            rows.append(_session_row(s, col=f"{label}  "))

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
