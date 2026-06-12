# ccmanager

Claude Code sessions widget for Waybar. Shows a live count of running Claude
Code CLI sessions; clicking opens a themed session picker to focus any session's
terminal window.

<img width="1440" height="793" alt="image" src="https://github.com/user-attachments/assets/ec81d4be-a0ad-4252-a160-15bd0d1a982a" />


## What it does

- **Bar module**: displays a robot icon + session count. Color reflects the
  most urgent state across all sessions (green=busy, amber=waiting, grey=idle).
  Collapses to nothing when no sessions are running.
- **Picker**: a rofi dmenu with colored state glyphs, session title, and cwd for
  each session. Selecting one focuses the session's kitty window via hyprctl.

## State glyph legend

| Glyph | Color  | Meaning                          |
|-------|--------|----------------------------------|
| ⚡    | green  | `busy` — Claude is actively working |
| 🔔    | amber  | `waiting` — needs your input    |
| ○     | grey   | `idle` — running, awaiting prompt |

## Project layout

```
ccmanager/
  ccmanager/__init__.py     package root
  ccmanager/glyphs.py       Nerd Font glyphs + color constants
  ccmanager/sessions.py     enumerate & enrich live sessions
  ccmanager/bar.py          emit Waybar JSON
  ccmanager/picker.py       rofi session picker + hyprctl focus
  bin/ccmanager             CLI entrypoint (bar | pick)
  rofi/theme.rasi          rofi theme matching waybar palette
```

## How it works

1. **Session detection**: reads `~/.claude/sessions/<PID>.json` (one file per
   live session). Filters to `entrypoint=cli` (interactive TUI only). Verifies
   liveness via `/proc/<pid>/stat` starttime matching `procStart` (guards against
   PID reuse after a session ends).

2. **Title resolution**: scans the session transcript
   `~/.claude/projects/*/<sessionId>.jsonl` for the last `ai-title` line.
   Falls back to the user-set `name` field, then a UUID prefix.

3. **Window routing**: walks `/proc` parent chain from the claude PID until
   finding a process that matches a `hyprctl clients -j` window (the kitty
   terminal). Uses `hyprctl dispatch focuswindow address:0x...` to focus it.

## Requirements

- Python 3.10+ (stdlib only, no pip installs)
- `hyprctl` (bundled with Hyprland)
- `rofi` (for the picker)
- `JetBrains Mono Nerd Font` (for glyphs in the bar and picker)

## Waybar wiring

Already in `~/.config/waybar/config` and `~/.config/waybar/style.css`.
After any config edit: `pkill -SIGUSR2 waybar` to hot-reload.

## Limitations

- **2s poll cadence**: `interval: 2` in the waybar module config. The module
  updates within 2 seconds of a session starting, ending, or changing state.
  A future enhancement: use inotify on `~/.claude/sessions/` + waybar signal
  (speakit-style `interval:"once"` + `signal: N`) for instant updates.

- **kitty tabs**: if multiple sessions run in different kitty *tabs* of the same
  kitty *window*, they resolve to the same hyprctl window address. Focus lands
  on the window, not the specific tab (hyprctl cannot switch kitty tabs). Kitty
  *windows* (separate OS windows) work correctly.
