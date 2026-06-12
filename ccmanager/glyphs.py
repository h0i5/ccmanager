"""
Nerd Font glyphs — emitted via explicit UTF-8 byte sequences.
Matches the speakit convention: private-use-area chars survive editors /
copy-paste that strip them when written as literal Unicode characters.

Codepoints chosen:
  BAR_ICON   U+F06D2  nf-md-robot              bytes: f3 b0 9b 92
  GLYPH_BUSY U+0F0E7  nf-fa-bolt               bytes: ef 83 a7
  GLYPH_WAIT U+0F0A2  nf-fa-bell               bytes: ef 82 a2
  GLYPH_IDLE U+0F10C  nf-fa-circle-o           bytes: ef 84 8c
"""

# Claude sunburst logomark at U+E900 in ClaudeLogo font (assets/ClaudeLogo.ttf)
CLAUDE_LOGO  = b"\xee\xa4\x80".decode("utf-8")
COLOR_CLAUDE = "#d97757"  # Claude orange

# State glyphs
GLYPH_BUSY    = b"\xef\x83\xa7".decode("utf-8")  # nf-fa-bolt    U+F0E7
GLYPH_WAITING = b"\xef\x82\xa2".decode("utf-8")  # nf-fa-bell    U+F0A2
GLYPH_IDLE    = b"\xef\x84\x8c".decode("utf-8")  # nf-fa-circle  U+F10C

# Colors (matching waybar style.css)
COLOR_BUSY    = "#50fa7b"  # green  — actively working
COLOR_WAITING = "#e5a04b"  # amber  — needs your input
COLOR_IDLE    = "#6c7086"  # muted  — alive but quiet
COLOR_TEXT    = "#d5d5e0"  # default text
COLOR_ACCENT  = "#e55064"  # bar icon accent
COLOR_DIM     = "#6c7086"  # dim cwd text in picker


def state_glyph(status: str) -> str:
    return {
        "busy":    GLYPH_BUSY,
        "waiting": GLYPH_WAITING,
    }.get(status, GLYPH_IDLE)


def state_color(status: str) -> str:
    return {
        "busy":    COLOR_BUSY,
        "waiting": COLOR_WAITING,
    }.get(status, COLOR_IDLE)


def pango(text: str, color: str) -> str:
    """Wrap text in a Pango <span color='...'> tag."""
    return f"<span color='{color}'>{text}</span>"
