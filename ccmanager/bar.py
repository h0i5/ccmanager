"""
bar.py — Emit a single Waybar JSON line for the custom/claude module.

Output schema (return-type: json):
  { "text": "...", "class": "busy|waiting|idle", "tooltip": "..." }

text:    "<bar-icon> N"  (Pango markup, colored icon)
class:   aggregate state (most urgent session wins)
tooltip: one line per session: «glyph»  title  ·  ~/cwd
"""

import json
import os
from pathlib import Path

from .sessions import list_sessions, write_cache, rel_time
from .glyphs import (
    BAR_ICON,
    COLOR_ACCENT,
    COLOR_TEXT,
    COLOR_DIM,
    pango,
    state_glyph,
    state_color,
)


def _shorten_cwd(cwd: str) -> str:
    """Replace $HOME prefix with ~ for display."""
    home = str(Path.home())
    if cwd == home:
        return "~"
    if cwd.startswith(home + "/"):
        return "~" + cwd[len(home):]
    return cwd


def run() -> None:
    sessions = list_sessions()
    write_cache(sessions)
    n = len(sessions)

    if n == 0:
        # Empty text → waybar auto-collapses the module
        print(json.dumps({"text": "", "class": "idle", "tooltip": "no active sessions"}))
        return

    # Aggregate class: waiting (needs you) > busy > idle
    statuses = {s.status for s in sessions}
    if "waiting" in statuses:
        agg_class = "waiting"
    elif "busy" in statuses:
        agg_class = "busy"
    else:
        agg_class = "idle"

    # Bar text: colored icon + count
    icon = pango(BAR_ICON, COLOR_ACCENT)
    count_color = COLOR_TEXT if agg_class == "idle" else (
        "#e5a04b" if agg_class == "waiting" else "#50fa7b"
    )
    text = f"{icon} <span color='{count_color}'>{n}</span>"

    # Tooltip: one line per session, matching modal order + time hint
    lines = []
    for s in sessions:
        glyph = pango(state_glyph(s.status), state_color(s.status))
        title = s.title or s.session_id[:8]
        cwd = _shorten_cwd(s.cwd)
        if s.status == "waiting":
            hint = f"waiting {rel_time(s.status_updated_at)}"
        else:
            hint = rel_time(s.updated_at)
        lines.append(f"{glyph}  {title}  ·  {cwd}  {pango(hint, COLOR_DIM)}")
    tooltip = "\n".join(lines)

    print(json.dumps({
        "text": text,
        "class": agg_class,
        "tooltip": tooltip,
        "alt": str(n),
    }))
