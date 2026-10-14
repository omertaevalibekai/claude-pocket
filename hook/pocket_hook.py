"""Claude Code hook: sends a short, sanitised event to the Claude Pocket server.

Registered for SessionStart, UserPromptSubmit, PreToolUse, PostToolUse,
Notification, Stop and SessionEnd with "async": true, so Claude Code never
waits for it. Whatever happens, it exits 0 and prints nothing.

Only this leaves the computer: the project folder name, the event, a short
action ("edits funnel.py", "git push origin main") with anything that looks
like a key or password cut off, and the local UTC offset for the daily chart.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

CONFIG = Path(os.environ.get("CLAUDE_POCKET_HOME") or Path.home() / ".claude-pocket") / "config.json"

SECRETISH = re.compile(
    r"(key|token|secret|passw|bearer|authorization|api[_-]?key|sk-|ghp_|github_pat|xox[bp]-)", re.IGNORECASE)
VERBS = {"Read": "читает", "Edit": "правит", "MultiEdit": "правит", "Write": "пишет", "Bash": "запускает",
         "Grep": "ищет", "Glob": "ищет файлы", "WebFetch": "читает страницу", "WebSearch": "ищет в сети",
         "Task": "запустил агента", "Agent": "запустил агента", "NotebookEdit": "правит"}


def safe_words(text: str, words: int = 4, limit: int = 48) -> str:
    """First words only; stop at the first thing that looks like a secret."""
    kept = []
    for word in (text or "").split():
        if len(kept) >= words:
            break
        blob = len(word) >= 24 and re.search(r"[A-Za-z]", word) and re.search(r"\d", word)
        if SECRETISH.search(word) or blob or ("://" in word and "@" in word):
            break
        kept.append(word)
    out = " ".join(kept)
    return out if len(out) <= limit else out[: limit - 1] + "…"


def action(tool: str, data: dict) -> str:
    data = data or {}
    verb = VERBS.get(tool, tool[:24])
    if tool == "Bash":
        detail = safe_words(str(data.get("command", "")), words=4)
    else:
        detail = ""
        for key in ("file_path", "notebook_path", "path"):
            if data.get(key):
                detail = safe_words(os.path.basename(str(data[key]).rstrip("\\/")), words=1)
                break
        else:
            for key in ("pattern", "query", "description"):
                if data.get(key):
                    detail = safe_words(str(data[key]), words=3)
                    break
    return f"{verb} {detail}".strip()


def project(cwd: str) -> str:
    cwd = (cwd or "").rstrip("\\/")
    if not cwd:
        return "Claude"
    if os.path.normcase(cwd) == os.path.normcase(str(Path.home())):
        return "~"
    return os.path.basename(cwd)[:40]


def compact(payload: dict) -> dict | None:
    if payload.get("agent_id"):
        return None                                   # subagents don't change the session state
    event = payload.get("hook_event_name") or ""
    out = {
        "sid": str(payload.get("session_id") or "?")[:64],
        "event": event,
        "project": project(payload.get("cwd") or ""),
        "ts": round(time.time()),
        "tz": time.localtime().tm_gmtoff,
    }
    if event in ("PreToolUse", "PostToolUse"):
        tool = payload.get("tool_name") or ""
        out["detail"] = action(tool, payload.get("tool_input") or {})
        command = str((payload.get("tool_input") or {}).get("command") or "") if tool == "Bash" else ""
        out["commit"] = event == "PreToolUse" and bool(re.search(r"\bgit\b.*\bcommit\b", command))
    elif event == "Notification":
        out["kind"] = payload.get("notification_type") or ""
    return out


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        event = compact(payload)
        if event is None:
            return 0
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        request = urllib.request.Request(
            config["url"].rstrip("/") + "/event", data=json.dumps(event, ensure_ascii=False).encode("utf-8"),
            method="POST", headers={"Content-Type": "application/json", "X-Pocket-Key": config["push_key"]},
        )
        urllib.request.urlopen(request, timeout=4).read()
    except Exception:
        pass                                          # a widget must never break Claude Code
    return 0


if __name__ == "__main__":
    sys.exit(main())
