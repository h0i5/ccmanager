"""
Enumerate live Claude Code CLI sessions.

Data flow:
  ~/.claude/sessions/<PID>.json  →  Session dataclass
    ↳ liveness guard via /proc/<pid>/stat starttime == procStart
    ↳ title from ~/.claude/projects/*/<sessionId>.jsonl  (ai-title line)
    ↳ git_repo from cwd via git rev-parse
    ↳ context_paths from transcript @/path user message references
    ↳ window address via /proc parent-walk + hyprctl clients -j
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


CLAUDE_DIR = Path.home() / ".claude"
SESSIONS_DIR = CLAUDE_DIR / "sessions"
PROJECTS_DIR = CLAUDE_DIR / "projects"
_CACHE_PATH = Path("/tmp/ccmanager-sessions.json")
_CACHE_MAX_AGE = 10  # seconds — bar polls every 2s so cache is usually <2s old

# Matches @/abs/path or @~/path references in user messages
_CTX_PATH_RE = re.compile(r'@((?:/|~/)[^\s\'"`,;>\])\}]+)')


def rel_time(epoch_ms: int) -> str:
    """Human-readable age: 'now', '4m', '2h', '3d'."""
    secs = int(time.time()) - epoch_ms // 1000
    if secs < 60:
        return "now"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h"
    return f"{secs // 86400}d"


@dataclass
class Session:
    pid: int
    session_id: str
    cwd: str
    status: str           # "idle" | "busy" | "waiting"
    title: str
    name: str             # user-set short name (may be empty)
    version: str
    address: Optional[str]   # hyprland window address (0x...)
    workspace: Optional[str]
    status_updated_at: int   # epoch ms — when status last changed
    updated_at: int          # epoch ms — last activity heartbeat
    started_at: int          # epoch ms — session start
    git_repo: str            # basename of git root, or ""
    context_paths: list[str] = field(default_factory=list)  # @-referenced dirs


# ── /proc helpers ─────────────────────────────────────────────────────────────

def _proc_starttime(pid: int) -> Optional[str]:
    """Return starttime field (field 22, 1-indexed) from /proc/<pid>/stat."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        rp = stat.rfind(")")
        fields = stat[rp + 2:].split()
        return fields[19]
    except (OSError, IndexError):
        return None


def _proc_ppid(pid: int) -> Optional[int]:
    """Return parent PID from /proc/<pid>/stat."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        rp = stat.rfind(")")
        fields = stat[rp + 2:].split()
        return int(fields[1])
    except (OSError, IndexError, ValueError):
        return None


def _is_alive(pid: int, proc_start: str) -> bool:
    """True if pid is alive and procStart matches (guards against PID reuse)."""
    start = _proc_starttime(pid)
    if start is None:
        return False
    return str(start) == str(proc_start)


# ── Window resolution ─────────────────────────────────────────────────────────

def _hyprctl_clients() -> dict[int, dict]:
    """Return {pid: client_dict} from hyprctl clients -j."""
    try:
        out = subprocess.check_output(
            ["hyprctl", "clients", "-j"],
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
        clients = json.loads(out)
        return {c["pid"]: c for c in clients if isinstance(c.get("pid"), int)}
    except Exception:
        return {}


def _find_window(claude_pid: int, clients: dict[int, dict]) -> Optional[dict]:
    """
    Walk /proc parent chain from claude_pid until hitting a hyprland client
    (the kitty terminal). Chain: claude → zsh → kitty → ...
    """
    pid = claude_pid
    seen: set[int] = set()
    while pid and pid not in seen and pid > 1:
        seen.add(pid)
        if pid in clients:
            return clients[pid]
        pid = _proc_ppid(pid) or 0
    return None


# ── Git repo resolution ───────────────────────────────────────────────────────

def _git_repo(cwd: str) -> str:
    """Return the basename of the git root for cwd, or '' if not in a repo."""
    if not cwd:
        return ""
    try:
        root = subprocess.check_output(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).decode().strip()
        return Path(root).name
    except Exception:
        return ""


# ── Context path extraction ───────────────────────────────────────────────────

def _context_paths(transcript: Path, cwd: str) -> list[str]:
    """
    Scan transcript for @/abs/path or @~/path references in user messages.
    Returns unique existing paths (files or dirs) that differ from cwd.
    """
    home = str(Path.home())
    cwd_norm = str(Path(cwd).resolve()) if cwd else ""
    seen: set[str] = set()
    results: list[str] = []

    try:
        size = transcript.stat().st_size
        # Only scan first 32 KB — context refs typically appear early in sessions
        with transcript.open("r", encoding="utf-8", errors="replace") as f:
            data = f.read(32768)
    except OSError:
        return []

    for line in data.splitlines():
        if '"user"' not in line and '"attachment"' not in line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") not in ("user", "attachment"):
            continue

        text = json.dumps(obj.get("message") or obj.get("attachment") or "")
        for raw in _CTX_PATH_RE.findall(text):
            # Expand ~/
            expanded = raw.replace("~/", home + "/", 1) if raw.startswith("~/") else raw
            # Strip trailing punctuation noise
            expanded = expanded.rstrip(".,;:)'\"")
            p = Path(expanded)
            norm = str(p.resolve())
            if norm in seen or norm == cwd_norm:
                continue
            if p.exists():
                seen.add(norm)
                # Store shortened form
                if norm.startswith(home):
                    results.append("~" + norm[len(home):])
                else:
                    results.append(norm)

    return results


# ── Title resolution ──────────────────────────────────────────────────────────

def _resolve_title(session_id: str, cwd: str, name: str) -> str:
    """
    Best human-readable title: ai-title → session name → cwd/uuid fallback.
    """
    matches = list(PROJECTS_DIR.glob(f"*/{session_id}.jsonl"))
    if matches:
        try:
            ai_title = _scan_ai_title(matches[0])
            if ai_title:
                return ai_title
        except OSError:
            pass

    if name:
        return name

    home = str(Path.home())
    p = Path(cwd)
    if str(p) == home or p.name in ("", "proxima"):
        return session_id[:8]
    parts = p.parts
    if len(parts) >= 2:
        return "/".join(parts[-2:])
    return p.name or session_id[:8]


def _scan_ai_title(path: Path) -> Optional[str]:
    """Get the last ai-title from a jsonl transcript (tail scan, 8 KB)."""
    TAIL = 8192
    last_title = None

    size = path.stat().st_size
    with path.open("rb") as f:
        if size > TAIL:
            f.seek(-TAIL, 2)
            f.readline()
        data = f.read().decode("utf-8", errors="replace")

    for line in data.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            if obj.get("type") == "ai-title":
                t = obj.get("aiTitle", "")
                if t:
                    last_title = t
        except json.JSONDecodeError:
            continue

    if last_title:
        return last_title

    if size > TAIL:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"ai-title"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get("type") == "ai-title":
                        t = obj.get("aiTitle", "")
                        if t:
                            last_title = t
                except json.JSONDecodeError:
                    continue

    return last_title


# ── Cache ─────────────────────────────────────────────────────────────────────

def _session_to_dict(s: Session) -> dict:
    return {
        "pid": s.pid, "session_id": s.session_id, "cwd": s.cwd,
        "status": s.status, "title": s.title, "name": s.name,
        "version": s.version, "address": s.address, "workspace": s.workspace,
        "status_updated_at": s.status_updated_at, "updated_at": s.updated_at,
        "started_at": s.started_at, "git_repo": s.git_repo,
        "context_paths": s.context_paths,
    }


def _session_from_dict(d: dict) -> Session:
    return Session(
        pid=d["pid"], session_id=d["session_id"], cwd=d["cwd"],
        status=d["status"], title=d["title"], name=d.get("name", ""),
        version=d.get("version", ""), address=d.get("address"),
        workspace=d.get("workspace"),
        status_updated_at=d["status_updated_at"], updated_at=d["updated_at"],
        started_at=d.get("started_at", d["updated_at"]),
        git_repo=d.get("git_repo", ""),
        context_paths=d.get("context_paths", []),
    )


def write_cache(sessions: list[Session]) -> None:
    try:
        payload = {"ts": time.time(), "sessions": [_session_to_dict(s) for s in sessions]}
        _CACHE_PATH.write_text(json.dumps(payload))
    except OSError:
        pass


def read_cache() -> Optional[list[Session]]:
    """Return cached sessions if cache exists and is fresh, else None."""
    try:
        payload = json.loads(_CACHE_PATH.read_text())
        if time.time() - payload["ts"] > _CACHE_MAX_AGE:
            return None
        return [_session_from_dict(d) for d in payload["sessions"]]
    except Exception:
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def list_sessions() -> list[Session]:
    """
    Return all live interactive Claude Code CLI sessions, enriched with
    title, git repo, context paths, and window address.
    Sorted: busy → waiting → idle, most-recent first within each group.
    """
    if not SESSIONS_DIR.exists():
        return []

    clients = _hyprctl_clients()
    sessions: list[Session] = []

    for f in SESSIONS_DIR.glob("*.json"):
        try:
            pid = int(f.stem)
        except ValueError:
            continue

        try:
            data = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue

        if data.get("entrypoint") != "cli":
            continue

        proc_start = data.get("procStart", "")
        if not _is_alive(pid, proc_start):
            continue

        status = data.get("status", "idle")
        if status not in ("idle", "busy", "waiting"):
            status = "idle"
        cwd = data.get("cwd", "")
        name = data.get("name", "")
        session_id = data.get("sessionId", "")
        version = data.get("version", "")
        status_updated_at = data.get("statusUpdatedAt", 0)
        updated_at = data.get("updatedAt", status_updated_at)
        started_at = data.get("startedAt", status_updated_at)

        title = _resolve_title(session_id, cwd, name)
        repo = _git_repo(cwd)

        transcript_matches = list(PROJECTS_DIR.glob(f"*/{session_id}.jsonl"))
        ctx_paths = _context_paths(transcript_matches[0], cwd) if transcript_matches else []

        client = _find_window(pid, clients)
        address = client["address"] if client else None
        workspace = client["workspace"]["name"] if client else None

        sessions.append(Session(
            pid=pid,
            session_id=session_id,
            cwd=cwd,
            status=status,
            title=title,
            name=name,
            version=version,
            address=address,
            workspace=workspace,
            status_updated_at=status_updated_at,
            updated_at=updated_at,
            started_at=started_at,
            git_repo=repo,
            context_paths=ctx_paths,
        ))

    # Tier: waiting (needs you) → idle (free) → busy (working)
    # Within waiting: oldest wait first (anti-starvation).
    # Within idle/busy: most-recently-active first.
    TIER = {"waiting": 0, "busy": 1, "idle": 2}

    def _rank(s: Session) -> tuple:
        tier = TIER.get(s.status, 3)
        if s.status == "waiting":
            return (tier, s.status_updated_at)   # ascending — longest wait on top
        return (tier, -s.updated_at)             # descending — most recent on top

    sessions.sort(key=_rank)
    return sessions
